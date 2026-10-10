"""Authenticated project and endpoint management REST API."""
from flask import Blueprint, jsonify, request
from anyapi.auth import current_user, verify_csrf
from anyapi.services import supabase, runner, referenced_connector_ids
from anyapi.runtime.engine import snapshot_config, validate_config
from anyapi.slugs import normalize_username, username_error
from anyapi.supabase import SupabaseError

bp = Blueprint("management", __name__, url_prefix="/_api")

def user_client():
    u = current_user()
    if not u:
        return None, None
    return u, supabase().user(u["access_token"])

def error(message, status=400):
    return jsonify(error=message), status

@bp.get("/projects")
def projects():
    u,db=user_client()
    if not u:return error("unauthorized",401)
    return jsonify(db.select("projects",{"select":"*","owner_id":"eq."+u["id"],"order":"created_at.desc"}))

@bp.post("/projects")
def create_project():
    verify_csrf()
    u,db=user_client()
    if not u:return error("unauthorized",401)
    data=request.get_json(silent=True) or {}
    slug=str(data.get("slug","")).strip().lower()
    if username_error(slug):return error("Invalid project slug")
    name=str(data.get("name","")).strip()[:80]
    if not name:return error("Project name is required")
    try:
        record=db.insert("projects",{"owner_id":u["id"],"name":name,"slug":slug,"description":str(data.get("description",""))[:500]})
        return jsonify(record),201
    except SupabaseError as exc:return error(exc.message,409 if exc.status==409 else 400)

@bp.get("/projects/<project_id>/endpoints")
def endpoints(project_id):
    u,db=user_client()
    if not u:return error("unauthorized",401)
    project=db.select_one("projects",{"id":"eq."+project_id,"owner_id":"eq."+u["id"],"select":"id"})
    if not project:return error("not_found",404)
    return jsonify(db.select("endpoints",{"project_id":"eq."+project_id,"owner_id":"eq."+u["id"],"select":"*","order":"created_at.desc"}))

@bp.post("/projects/<project_id>/endpoints")
def create_endpoint(project_id):
    verify_csrf()
    u,db=user_client()
    if not u:return error("unauthorized",401)
    project=db.select_one("projects",{"id":"eq."+project_id,"owner_id":"eq."+u["id"],"select":"id"})
    if not project:return error("not_found",404)
    data=request.get_json(silent=True) or {}
    slug=str(data.get("slug","")).strip().lower()
    if username_error(slug):return error("Invalid endpoint slug")
    if data.get("method","POST") not in ("GET","POST","PUT","PATCH","DELETE"):return error("Invalid HTTP method")
    name=str(data.get("name","")).strip()[:80]
    if not name:return error("Endpoint name is required")
    try:
        return jsonify(db.insert("endpoints",{"project_id":project_id,"owner_id":u["id"],"name":name,"slug":slug,"method":data.get("method","POST")})),201
    except SupabaseError as exc:return error(exc.message,409 if exc.status==409 else 400)

@bp.route("/endpoints/<endpoint_id>",methods=["GET","PATCH"])
def endpoint_details(endpoint_id):
    if request.method=="PATCH":verify_csrf()
    u,db=user_client()
    if not u:return error("unauthorized",401)
    original=db.select_one("endpoints",{"id":"eq."+endpoint_id,"owner_id":"eq."+u["id"],"select":"*"})
    if not original:return error("not_found",404)
    if request.method=="GET":return jsonify(original)
    payload=request.get_json(silent=True) or {}
    allowed={"name","description","method","visibility","input_schema","output_schema","processor","response_config","settings"}
    values={key:value for key,value in payload.items() if key in allowed}
    if not values:return error("No editable fields")
    if "method" in values and values["method"] not in ("GET","POST","PUT","PATCH","DELETE"):return error("Invalid method")
    if "visibility" in values and values["visibility"] not in ("public","private"):return error("Invalid visibility")
    try:
        rows=db.update("endpoints",{"id":"eq."+endpoint_id,"owner_id":"eq."+u["id"]},values)
        return jsonify(rows[0] if rows else original)
    except SupabaseError as exc:return error(exc.message)

@bp.post("/endpoints/<endpoint_id>/publish")
def publish(endpoint_id):
    verify_csrf()
    u,db=user_client()
    if not u:return error("unauthorized",401)
    endpoint=db.select_one("endpoints",{"id":"eq."+endpoint_id,"owner_id":"eq."+u["id"],"select":"*"})
    if not endpoint:return error("not_found",404)
    ids=referenced_connector_ids(endpoint.get("processor"))
    available=db.select("connectors",{"project_id":"eq."+endpoint["project_id"],"owner_id":"eq."+u["id"],"select":"id"})
    failures=validate_config(snapshot_config(endpoint),{str(c["id"]) for c in available},runner())
    if failures:return jsonify(error="validation_failed",fields=failures),422
    try:
        version=db.rpc("publish_endpoint",{"p_endpoint_id":endpoint_id,"p_config":snapshot_config(endpoint),"p_notes":(request.get_json(silent=True) or {}).get("notes")})
        return jsonify(version),201
    except SupabaseError as exc:return error(exc.message)

@bp.post("/endpoints/<endpoint_id>/rollback")
def rollback(endpoint_id):
    verify_csrf()
    u,db=user_client()
    if not u:return error("unauthorized",401)
    data=request.get_json(silent=True) or {}
    try:
        return jsonify(db.rpc("rollback_endpoint",{"p_endpoint_id":endpoint_id,"p_version":int(data["version"])}))
    except (SupabaseError,ValueError,KeyError) as exc:return error(str(exc))
