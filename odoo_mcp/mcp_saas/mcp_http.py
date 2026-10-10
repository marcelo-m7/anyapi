"""Fail-closed stateless MCP Streamable HTTP with JSON-RPC 2.0.

MCP authentication is separate from the Supabase browser cookie. Until the
real OAuth authorizer/context factory is installed, all invocations return 401.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urlsplit

from flask import Blueprint, current_app, jsonify, request

from .errors import AppError
from .oauth_store import OAuthError
from .tools import ToolContext, ToolRegistry

bp = Blueprint("odoo_mcp_http", __name__)
_PUBLIC_ID = re.compile(r"^[a-f0-9]{32,64}$")
_SUPPORTED_VERSIONS = frozenset({"2025-11-25", "2025-06-18", "2025-03-26"})
_LATEST_VERSION = "2025-11-25"
_RPC_VERSION = "2.0"


def _rpc_result(request_id, data: dict) -> dict:
    return {"jsonrpc": _RPC_VERSION, "id": request_id, "result": data}


def _rpc_error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": _RPC_VERSION, "id": request_id,
            "error": {"code": code, "message": message}}


def dispatch_rpc(context: ToolContext, message: dict) -> tuple[dict | None, int]:
    if not isinstance(message, dict) or message.get("jsonrpc") != _RPC_VERSION:
        return _rpc_error(message.get("id") if isinstance(message, dict) else None,
                          -32600, "Invalid JSON-RPC request"), 200
    method = message.get("method")
    if not isinstance(method, str):
        return _rpc_error(message.get("id"), -32600, "Method must be a string"), 200
    if "id" not in message:
        # Transport notifications have no response body.
        return None, 202
    request_id = message["id"]
    if isinstance(request_id, bool) or not isinstance(request_id, (str, int)):
        return _rpc_error(None, -32600, "Invalid request ID"), 200
    params = message.get("params", {})
    if not isinstance(params, dict):
        return _rpc_error(request_id, -32602, "Invalid parameters"), 200
    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in _SUPPORTED_VERSIONS else _LATEST_VERSION
        return _rpc_result(request_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "odoo-mcp-saas", "version": "0.1.0"},
        }), 200
    if method == "ping":
        return _rpc_result(request_id, {}), 200
    if method == "tools/list":
        return _rpc_result(request_id, {"tools": ToolRegistry.list_tools(context)}), 200
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return _rpc_error(request_id, -32602, "Invalid tool call"), 200
        try:
            result = ToolRegistry.invoke(context, name, arguments)
            response = {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                "structuredContent": result,
                "isError": False,
            }
        except AppError as exc:
            response = {
                "content": [{"type": "text", "text": exc.code + ": " + exc.message}],
                "isError": True,
            }
        return _rpc_result(request_id, response), 200
    return _rpc_error(request_id, -32601, "Method not found"), 200


def _oauth_challenge(public_id: str):
    settings = current_app.extensions["odoo_mcp.settings"]
    base = settings.public_url.rstrip("/")
    response = jsonify(error="unauthorized")
    response.status_code = 401
    if base.startswith("https://"):
        metadata = base + "/.well-known/oauth-protected-resource/mcp/" + public_id
        response.headers["WWW-Authenticate"] = f'Bearer resource_metadata="{metadata}"'
    else:
        response.headers["WWW-Authenticate"] = "Bearer"
    return response


def _origin_permitted(origin: str | None) -> bool:
    if not origin:
        return True
    config = current_app.extensions["odoo_mcp.settings"]
    try:
        parsed = urlsplit(origin)
        allowed = urlsplit(config.public_url)
        return (parsed.scheme == "https" and parsed.hostname == allowed.hostname
                and parsed.port == allowed.port and parsed.path in ("", "/")
                and not parsed.query and not parsed.fragment)
    except ValueError:
        return False


@bp.route("/mcp/<public_id>", methods=["GET", "POST", "DELETE"])
def mcp_endpoint(public_id: str):
    if not _PUBLIC_ID.fullmatch(public_id):
        return jsonify(error="not_found"), 404
    if request.method != "POST":
        return "", 405
    if not _origin_permitted(request.headers.get("Origin")):
        return jsonify(error="invalid_origin"), 403
    accepts = request.headers.get("Accept", "").lower()
    if not ("application/json" in accepts and "text/event-stream" in accepts):
        return jsonify(error="not_acceptable"), 406
    if not request.is_json:
        return jsonify(error="invalid_content_type"), 415
    version = request.headers.get("MCP-Protocol-Version")
    if version and version not in _SUPPORTED_VERSIONS:
        return jsonify(error="unsupported_protocol_version"), 400
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="invalid_json_rpc"), 400
    bearer = request.headers.get("Authorization", "")
    if not bearer.startswith("Bearer ") or len(bearer) <= len("Bearer "):
        return _oauth_challenge(public_id)
    authorizer = current_app.extensions.get("odoo_mcp.authorizer")
    context_factory = current_app.extensions.get("odoo_mcp.context_factory")
    if authorizer is None or context_factory is None:
        return _oauth_challenge(public_id)
    resource = (current_app.extensions["odoo_mcp.settings"].public_url.rstrip("/")
                + "/mcp/" + public_id)
    try:
        grant = authorizer.authenticate_access_token(bearer[len("Bearer "):], resource)
        context = context_factory(grant, public_id)
        if not isinstance(context, ToolContext):
            raise AppError("not_authorized", 401, "Unauthorized MCP request")
    except (AppError, OAuthError, ValueError, TypeError):
        return _oauth_challenge(public_id)
    result, status = dispatch_rpc(context, data)
    if result is None:
        return "", status
    response = jsonify(result)
    response.status_code = status
    response.headers["Cache-Control"] = "no-store"
    return response
