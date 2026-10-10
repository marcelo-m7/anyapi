"""OAuth authorization metadata and SSRF-guarded Client ID Metadata Documents."""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from flask import Blueprint, current_app, jsonify

from .errors import AppError
from .oauth_store import OAuthError
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
        return self.store.authenticate_access_token(token, resource)
