"""OAuth authorization metadata and SSRF-guarded Client ID Metadata Documents."""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from flask import Blueprint, current_app, jsonify

from .errors import AppError
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
