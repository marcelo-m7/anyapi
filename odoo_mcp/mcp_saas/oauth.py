"""OAuth authorization metadata and SSRF-guarded Client ID Metadata Documents."""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from flask import Blueprint, current_app, jsonify, request, redirect, render_template_string

from .errors import AppError, OAuthError
from .network import NetworkError, PinnedHttpsTransport, assert_safe_odoo_url

bp = Blueprint("odoo_mcp_oauth", __name__)


def _canonical_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and bool(parsed.hostname)
                and parsed.port in (None, 443)
                and not parsed.username and not parsed.password
                and not parsed.fragment and not parsed.query
                and parsed.path.startswith("/") and parsed.path != "/")
    except (ValueError, TypeError):
        return False


def _redirect_allowed(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            return False
        if parsed.scheme == "https":
            return True
        if parsed.scheme != "http":
            return False
        # Native application loopback redirects are accepted, not arbitrary HTTP.
        return ipaddress.ip_address(parsed.hostname).is_loopback
    except (ValueError, TypeError):
        return False


class ClientMetadataResolver:
    def __init__(self, transport: PinnedHttpsTransport | None = None):
        self._transport = transport if transport is not None else PinnedHttpsTransport()

    def validate_client(self, client_id: str, redirect_uri: str) -> dict:
        if not _canonical_url(client_id) or not _redirect_allowed(redirect_uri):
            raise AppError("invalid_client", 400, "Unsupported OAuth client identifier or redirect URI")
        parsed = urlsplit(client_id)
        try:
            assert_safe_odoo_url(parsed.scheme + "://" + parsed.netloc)
        except NetworkError as exc:
            raise AppError("invalid_client", 400, "Client metadata host is not allowed") from exc
        if len(client_id) > 1024:
            raise AppError("invalid_client", 400, "Client identifier exceeds length limit")
        try:
            data = self._transport.get_metadata_json(client_id, timeout_s=5)
        except (NetworkError, ValueError) as exc:
            raise AppError("invalid_client", 400, "Client metadata could not be verified") from exc
        if (not isinstance(data, dict)
                or data.get("client_id") != client_id
                or not isinstance(data.get("client_name"), str)
                or not data["client_name"].strip()
                or not isinstance(data.get("redirect_uris"), list)
                or len(data["redirect_uris"]) > 20
                or not all(isinstance(x, str) and _redirect_allowed(x)
                           for x in data["redirect_uris"])
                or redirect_uri not in data["redirect_uris"]
                or data.get("token_endpoint_auth_method", "none") != "none"):
            raise AppError("invalid_client", 400, "Client metadata or redirect URI is invalid")
        return {"client_id": client_id, "client_name": data["client_name"][:120],
                "redirect_uris": data["redirect_uris"]}


@bp.get("/.well-known/oauth-protected-resource/mcp/<public_id>")
def protected_resource_metadata(public_id: str):
    from .mcp_http import _PUBLIC_ID
    if not _PUBLIC_ID.fullmatch(public_id):
        return jsonify(error="not_found"), 404
    base = current_app.extensions["odoo_mcp.settings"].public_url.rstrip("/")
    if not base.startswith("https://"):
        return jsonify(error="not_configured"), 503
    resource = base + "/mcp/" + public_id
    response = jsonify({
        "resource": resource,
        "authorization_servers": [base],
        "scopes_supported": ["odoo:read", "odoo:write"],
        "bearer_methods_supported": ["header"],
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/.well-known/oauth-authorization-server")
def authorization_server_metadata():
    base = current_app.extensions["odoo_mcp.settings"].public_url.rstrip("/")
    if not base.startswith("https://"):
        return jsonify(error="not_configured"), 503
    response = jsonify({
        "issuer": base,
        "authorization_endpoint": base + "/oauth/authorize",
        "token_endpoint": base + "/oauth/token",
        "revocation_endpoint": base + "/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["none"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": ["odoo:read", "odoo:write"],
        "client_id_metadata_document_supported": True,
    })
    response.headers["Cache-Control"] = "no-store"
    return response

class AuthorizationService:
    """Authorize PKCE grants before any MCP tool can be invoked.

    Routes are intentionally not registered yet: consent and token exchange
    must be wired with browser login, CSRF and transactional code verification.
    """

    def __init__(self, store, clients: ClientMetadataResolver, issuer: str):
        self.store = store
        self.clients = clients
        self.issuer = issuer.rstrip("/")

    def inspect(self, owner_id: str, parameters: dict) -> dict:
        import re
        if not isinstance(parameters, dict):
            raise OAuthError("invalid_request")
        if parameters.get("response_type") != "code":
            raise OAuthError("unsupported_response_type")
        if parameters.get("code_challenge_method") != "S256":
            raise OAuthError("invalid_request")
        challenge = parameters.get("code_challenge")
        if not isinstance(challenge, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", challenge):
            raise OAuthError("invalid_request")
        resource = parameters.get("resource")
        if not isinstance(resource, str) or not resource.startswith(self.issuer + "/mcp/"):
            raise OAuthError("invalid_target")
        from .mcp_http import _PUBLIC_ID
        public_id = resource[len(self.issuer + "/mcp/"):]
        if not _PUBLIC_ID.fullmatch(public_id):
            raise OAuthError("invalid_target")
        server = self.store.get_authorized_server(public_id, owner_id)
        if not server or not server.get("enabled"):
            raise OAuthError("invalid_target")
        scope = parameters.get("scope")
        if scope != "odoo:read":
            # No implicit write consent, even when the client requests it.
            raise OAuthError("invalid_scope")
        redirect = parameters.get("redirect_uri")
        client_id = parameters.get("client_id")
        try:
            metadata = self.clients.validate_client(client_id, redirect)
        except AppError as exc:
            raise OAuthError("invalid_client") from exc
        if not isinstance(parameters.get("state"), str) or not parameters["state"]:
            raise OAuthError("invalid_request")
        return {"owner_id": owner_id, "server_id": str(server["id"]),
                "client_id": client_id, "client_name": metadata["client_name"],
                "redirect_uri": redirect, "resource": resource, "scopes": ["odoo:read"],
                "pkce_challenge": challenge, "state": parameters["state"]}

    def approve(self, owner_id: str, parameters: dict) -> dict:
        reviewed = self.inspect(owner_id, parameters)
        code = self.store.issue_code(
            reviewed["owner_id"], reviewed["server_id"], reviewed["client_id"],
            reviewed["redirect_uri"], reviewed["resource"], reviewed["scopes"],
            reviewed["pkce_challenge"],
        )
        return {"code": code, "state": reviewed["state"], "redirect_uri": reviewed["redirect_uri"]}

    def exchange_code(self, parameters: dict) -> dict:
        if parameters.get("grant_type") != "authorization_code":
            raise OAuthError("unsupported_grant_type")
        verifier = parameters.get("code_verifier")
        import re
        if not isinstance(verifier, str) or not re.fullmatch(r"[A-Za-z0-9_~.\\-]{43,128}", verifier):
            raise OAuthError("invalid_grant")
        # Atomic store implementation must verify PKCE *inside the code-consuming transaction*.
        grant = self.store.consume_code(
            parameters.get("code"), parameters.get("client_id"),
            parameters.get("redirect_uri"), parameters.get("resource"), verifier,
        )
        if hasattr(self.store, "issue_tokens_from_grant"):
            return self.store.issue_tokens_from_grant(grant)
        return self.store.issue_tokens(grant)

    def authenticate_access_token(self, token: str, resource: str) -> dict:
        try:
            return self.store.authenticate_access_token(token, resource)
        except OAuthError as exc:
            raise AppError("not_authorized", 401, "Unauthorized MCP request") from exc

def _service() -> AuthorizationService:
    provider = current_app.extensions.get("odoo_mcp.oauth_service")
    if provider is None:
        raise OAuthError("temporarily_unavailable")
    return provider


def _safe_oauth_error(code: str = "invalid_request", status: int = 400):
    response = jsonify(error=code if code in {
        "invalid_request", "invalid_client", "invalid_grant", "unsupported_grant_type",
        "invalid_scope", "invalid_target", "unsupported_response_type",
    } else "invalid_request")
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.route("/oauth/authorize", methods=["GET", "POST"])
def authorize_http():
    from .browser_auth import current_identity, _csrf_token, _verify_csrf
    identity = current_identity()
    if identity is None:
        return redirect("/login")
    try:
        svc = _service()
        params = dict(request.args) if request.method == "GET" else dict(request.form)
        params.pop("csrf_token", None)
        params.pop("decision", None)
        inspected = svc.inspect(identity.id, params)
        if request.method == "GET":
            csrf = _csrf_token()
            response = render_template_string(
                """<!doctype html><html lang="en"><meta charset="utf-8">
                <meta name="viewport" content="width=device-width,initial-scale=1">
                <title>Authorize Odoo MCP</title>
                <h1>Authorize client access</h1><p>Client: {{ name }}</p>
                <p>Instance: {{ resource }}</p><p>Scope: {{ scopes }}</p>
                <p>Only authorize clients you recognize.</p>
                <form method="post">
                {% for name,value in params.items() %}
                <input type="hidden" name="{{ name }}" value="{{ value }}">
                {% endfor %}
                <input type="hidden" name="csrf_token" value="{{ csrf }}">
                <button type="submit" name="decision" value="approve">Allow read access</button>
                <button type="submit" name="decision" value="deny">Deny</button>
                </form></html>""",
                name=inspected["client_name"],resource=inspected["resource"],
                scopes=" ".join(inspected["scopes"]),params=params,csrf=csrf,
            )
            return response, 200, {"Cache-Control": "no-store"}
        _verify_csrf()
        if request.form.get("decision") != "approve":
            return _safe_oauth_error("invalid_request")
        approval = svc.approve(identity.id, params)
        from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
        validated = urlsplit(approval["redirect_uri"])
        query = parse_qsl(validated.query, keep_blank_values=True)
        query += [("code",approval["code"]),("state",approval["state"])]
        destination = urlunsplit((validated.scheme,validated.netloc,validated.path,
                                  urlencode(query),validated.fragment))
        return redirect(destination, code=302)
    except OAuthError as exc:
        return _safe_oauth_error(str(exc))


@bp.post("/oauth/token")
def token_http():
    try:
        svc = _service()
        grant_type = request.form.get("grant_type")
        if grant_type == "authorization_code":
            token = svc.exchange_code(dict(request.form))
        elif grant_type == "refresh_token":
            refresh = request.form.get("refresh_token")
            client_id = request.form.get("client_id")
            resource = request.form.get("resource")
            if not refresh or not client_id or not resource:
                raise OAuthError("invalid_grant")
            token = svc.store.rotate_refresh(refresh, client_id, resource)
        else:
            raise OAuthError("unsupported_grant_type")
        response = jsonify(token)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        return response
    except OAuthError as exc:
        return _safe_oauth_error(str(exc))


@bp.post("/oauth/revoke")
def revoke_http():
    try:
        svc = _service()
        token = request.form.get("token")
        if not token:
            raise OAuthError("invalid_request")
        svc.store.revoke_token(token, request.form.get("client_id") or None)
        return "", 200, {"Cache-Control": "no-store"}
    except OAuthError as exc:
        return _safe_oauth_error(str(exc))
