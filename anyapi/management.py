"""Authenticated project and endpoint management REST API."""
from flask import Blueprint, jsonify, request
from anyapi.auth import current_user, verify_csrf
from anyapi.services import supabase, runner, referenced_connector_ids
from anyapi.runtime.engine import snapshot_config, validate_config
from anyapi.slugs import normalize_username, username_error
from anyapi.supabase import SupabaseError

bp = Blueprint("management", __name__, url_prefix="/_api")

def catalog_ids(db):
    return {row["slug"] for row in db.select("edge_function_catalog",{"select":"slug","enabled":"eq.true"})}

@bp.get("/edge-functions")
def available_edge_functions():
    u,db=user_client()
    if not u:return error("unauthorized",401)
    rows=supabase().service().select("edge_function_catalog",{"select":"slug,title,description,category,input_schema,output_schema","enabled":"eq.true","order":"category.asc,title.asc"})
    return jsonify(rows)


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
        return jsonify(db.insert("endpoints",{"project_id":project_id,"owner_id":u["id"],"name":name,"slug":slug,"method":data.get("method","POST"),"processor":{"type":"edge_pipeline","steps":[],"output":""}})),201
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
    valid_ids=catalog_ids(supabase().service()) if (endpoint.get("processor") or {}).get("type")=="edge_pipeline" else {str(c["id"]) for c in available}
    failures=validate_config(snapshot_config(endpoint),valid_ids,runner())
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
        return jsonify(db.rpc("rollback_endpoint",{"p_endpoint_id":endpoint_id,"p_version_id":str(data["version_id"])}))
    except (SupabaseError,ValueError,KeyError) as exc:return error(str(exc))

@bp.post("/endpoints/<endpoint_id>/test")
def test_endpoint(endpoint_id):
    verify_csrf()
    u,db=user_client()
    if not u:return error("unauthorized",401)
    endpoint=db.select_one("endpoints",{"id":"eq."+endpoint_id,"owner_id":"eq."+u["id"],"select":"*"})
    if not endpoint:return error("not_found",404)
    from anyapi.services import load_connectors, new_request_id, log_execution
    from anyapi.runtime.engine import execute
    config=snapshot_config(endpoint)
    attached=referenced_connector_ids(config.get("processor"))
    available=db.select("connectors",{"project_id":"eq."+endpoint["project_id"],"owner_id":"eq."+u["id"],"select":"id"})
    valid_ids=catalog_ids(supabase().service()) if (config.get("processor") or {}).get("type")=="edge_pipeline" else {str(row["id"]) for row in available}
    problems=validate_config(config,valid_ids,runner())
    if problems:return jsonify(error="validation_failed",fields=problems),422
    body=request.get_json(silent=True)
    if body is None:return error("JSON body required")
    try:
        connectors=load_connectors(endpoint["project_id"],attached)
        result=execute(config,body,{"source":"test"},connectors=connectors,runner=runner())
        request_id=new_request_id()
        log_execution(endpoint_id=endpoint_id,owner_id=u["id"],version_id=None,version=None,source="test",request_id=request_id,method=endpoint["method"],result=result,request_body=body)
        return jsonify(status=result.status_code,body=result.body,logs=result.logs,duration_ms=result.duration_ms,request_id=request_id)
    except Exception:
        from flask import current_app
        current_app.logger.exception("Endpoint test failed")
        return error("Test execution failed",500)

@bp.get("/endpoints/<endpoint_id>/versions")
def versions(endpoint_id):
    u,db=user_client()
    if not u:return error("unauthorized",401)
    endpoint=db.select_one("endpoints",{"id":"eq."+endpoint_id,"owner_id":"eq."+u["id"],"select":"id"})
    if not endpoint:return error("not_found",404)
    return jsonify(db.select("endpoint_versions",{"endpoint_id":"eq."+endpoint_id,"owner_id":"eq."+u["id"],"select":"id,version,notes,created_at","order":"version.desc"}))

@bp.get("/endpoints/<endpoint_id>/executions")
def executions(endpoint_id):
    u,db=user_client()
    if not u:return error("unauthorized",401)
    endpoint=db.select_one("endpoints",{"id":"eq."+endpoint_id,"owner_id":"eq."+u["id"],"select":"id"})
    if not endpoint:return error("not_found",404)
    return jsonify(db.select("executions",{"endpoint_id":"eq."+endpoint_id,"owner_id":"eq."+u["id"],"select":"id,created_at,status_code,duration_ms,success,error_type,source","order":"created_at.desc","limit":"50"}))

@bp.route("/projects/<project_id>/connectors", methods=["GET","POST"])
def project_connectors(project_id):
    if request.method=="POST":verify_csrf()
    u,db=user_client()
    if not u:return error("unauthorized",401)
    project=db.select_one("projects",{"id":"eq."+project_id,"owner_id":"eq."+u["id"],"select":"id"})
    if not project:return error("not_found",404)
    if request.method=="GET":
        return jsonify(db.select("connectors",{"project_id":"eq."+project_id,"owner_id":"eq."+u["id"],"select":"id,name,type,config,secret_hint,created_at"}))
    from anyapi.services import secret_box
    values=request.get_json(silent=True) or {}
    name=str(values.get("name") or "").strip()
    config=values.get("config") or {}
    if not name or len(name)>80 or not isinstance(config,dict):return error("Invalid connector")
    if values.get("type","http")!="http":return error("Only HTTP connectors are supported")
    url=config.get("base_url") or config.get("url")
    from urllib.parse import urlparse
    if not isinstance(url,str) or urlparse(url).scheme!="https" or not urlparse(url).hostname:
        return error("HTTPS destination required")
    config={**config,"base_url":url}
    config.pop("url",None)
    secret=values.get("secret") or ""
    if secret and (not isinstance(secret,str) or len(secret)>4096):return error("Invalid secret")
    from anyapi.security import secret_hint
    try:
        payload={"project_id":project_id,"owner_id":u["id"],"name":name,"type":"http","config":config}
        if secret:
            payload["secret_ciphertext"]=secret_box().encrypt(secret)
            payload["secret_hint"]=secret_hint(secret)
        created=db.insert("connectors",payload,select="id,name,type,config,secret_hint,created_at")
        return jsonify(created),201
    except (SupabaseError,RuntimeError) as exc:return error("Could not create connector")

@bp.delete("/connectors/<connector_id>")
def delete_connector(connector_id):
    verify_csrf()
    u,db=user_client()
    if not u:return error("unauthorized",401)
    record=db.select_one("connectors",{"id":"eq."+connector_id,"owner_id":"eq."+u["id"],"select":"id"})
    if not record:return error("not_found",404)
    try:
        db.delete("connectors",{"id":"eq."+connector_id,"owner_id":"eq."+u["id"]})
        return "",204
    except SupabaseError:return error("Connector could not be deleted",409)

@bp.route("/projects/<project_id>/api-keys", methods=["GET","POST"])
def project_api_keys(project_id):
    if request.method=="POST":verify_csrf()
    u,db=user_client()
    if not u:return error("unauthorized",401)
    project=db.select_one("projects",{"id":"eq."+project_id,"owner_id":"eq."+u["id"],"select":"id"})
    if not project:return error("not_found",404)
    if request.method=="GET":
        return jsonify(db.select("api_keys",{"project_id":"eq."+project_id,"owner_id":"eq."+u["id"],"select":"id,name,prefix,endpoint_id,created_at,revoked_at"}))
    from anyapi.security import generate_api_key
    values=request.get_json(silent=True) or {}
    name=str(values.get("name") or "").strip()
    if not name or len(name)>80:return error("Invalid key name")
    endpoint_id=values.get("endpoint_id")
    if endpoint_id:
        record=db.select_one("endpoints",{"id":"eq."+str(endpoint_id),"project_id":"eq."+project_id,"owner_id":"eq."+u["id"],"select":"id"})
        if not record:return error("Endpoint not found",404)
    plain,prefix,digest=generate_api_key()
    try:
        created=db.insert("api_keys",{"project_id":project_id,"owner_id":u["id"],"endpoint_id":endpoint_id,"name":name,"prefix":prefix,"key_hash":digest},select="id,name,prefix,endpoint_id,created_at")
        return jsonify({**created,"key":plain,"warning":"Copy this key now. It will not be shown again."}),201
    except SupabaseError:return error("Could not create API key")

@bp.post("/api-keys/<key_id>/revoke")
def revoke_api_key(key_id):
    verify_csrf()
    u,db=user_client()
    if not u:return error("unauthorized",401)
    original=db.select_one("api_keys",{"id":"eq."+key_id,"owner_id":"eq."+u["id"],"select":"id"})
    if not original:return error("not_found",404)
    rows=db.update("api_keys",{"id":"eq."+key_id,"owner_id":"eq."+u["id"]},{"revoked_at":__import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()},"id,revoked_at")
    return jsonify(rows[0] if rows else {"revoked":True})
