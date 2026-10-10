"""Published AnyAPI endpoint gateway."""
from flask import Blueprint, current_app, jsonify, request
from anyapi.runtime.engine import execute
from anyapi.services import supabase, runner, load_connectors, referenced_connector_ids, log_execution, consume_rate_limit, new_request_id
from anyapi.security import hash_api_key
from anyapi.openapi import build_document

bp = Blueprint("gateway", __name__)

def resolve(username, project, endpoint):
    data = supabase().service().rpc("resolve_endpoint", {"p_username": username, "p_project": project, "p_endpoint": endpoint})
    if isinstance(data, list):
        data = data[0] if data else None
    if not data or data.get("archived") or data.get("status") != "published" or not data.get("version_id"):
        return None
    return data

def authorize(data):
    if data.get("visibility") != "private":
        return True
    supplied = request.headers.get("Authorization", "")
    if not supplied.startswith("Bearer aapi_"):
        return False
    key = supplied[7:]
    if len(key) > 180:
        return False
    rows = supabase().service().select("api_keys", {
        "select": "id", "key_hash": "eq." + hash_api_key(key),
        "project_id": "eq." + data["project_id"], "revoked_at": "is.null",
        "or": "(endpoint_id.is.null,endpoint_id.eq." + data["endpoint_id"] + ")",
        "limit": "1",
    })
    return bool(rows)

@bp.get("/docs/<username>/<project>/<endpoint>/openapi.json")
def openapi_json(username, project, endpoint):
    data = resolve(username, project, endpoint)
    if not data:
        return jsonify(error="not_found"), 404
    if not authorize(data):
        return jsonify(error="unauthorized"), 401
    base = current_app.config.get("ANYAPI_PUBLIC_URL") or request.url_root.rstrip("/")
    return jsonify(build_document(data, base))

@bp.route("/<username>/<project>/<endpoint>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def invoke(username, project, endpoint):
    request_id = new_request_id()
    data = resolve(username, project, endpoint)
    if not data:
        return jsonify(error={"type":"not_found", "message":"Endpoint not published"}, request_id=request_id), 404
    config = data["config"]
    if request.method != config.get("method", "POST"):
        resp = jsonify(error={"type":"method_not_allowed"}, request_id=request_id)
        resp.status_code = 405
        resp.headers["Allow"] = config.get("method", "POST")
        return resp
    if not authorize(data):
        return jsonify(error={"type":"unauthorized", "message":"A valid API key is required"},request_id=request_id), 401
    limit = max(1, min(int((config.get("settings") or {}).get("rate_limit_per_minute") or 60), 1000))
    allowed, remaining, reset = consume_rate_limit(data["endpoint_id"] + ":" + request.remote_addr.__str__(), limit)
    if not allowed:
        return jsonify(error={"type":"rate_limited"},request_id=request_id), 429
    if request.method in ("GET","DELETE"):
        incoming = request.args.to_dict()
    else:
        if not request.is_json:
            return jsonify(error={"type":"invalid_content_type", "message":"Expected application/json"},request_id=request_id), 415
        incoming = request.get_json(silent=True)
        if incoming is None:
            return jsonify(error={"type":"invalid_json"},request_id=request_id), 400
    try:
        connectors = load_connectors(data["project_id"], referenced_connector_ids(config.get("processor")))
        result = execute(config, incoming, {"request_id":request_id}, connectors=connectors, runner=runner())
    except Exception:
        current_app.logger.exception("Gateway request failed: %s", request_id)
        return jsonify(error={"type":"internal_error","message":"Execution failed"},request_id=request_id), 500
    log_execution(endpoint_id=data["endpoint_id"],owner_id=data["owner_id"], version_id=data["version_id"],version=data["version"],source="live",request_id=request_id,method=request.method,result=result,request_body=incoming)
    resp = jsonify(result.body)
    resp.status_code = result.status_code
    for header,value in result.headers.items():
        resp.headers[header] = value
    resp.headers["X-Request-ID"] = request_id
    resp.headers["X-RateLimit-Remaining"] = str(remaining)
    return resp
