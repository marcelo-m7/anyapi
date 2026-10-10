"""JSON/YAML conversions for Studio schema editor."""
from flask import Blueprint, jsonify, request
from anyapi.auth import current_user, verify_csrf
from anyapi.runtime.schema import schema_problems
import json
import yaml

bp = Blueprint("schema_editor", __name__, url_prefix="/_api/schema")

@bp.post("/convert")
def convert():
    verify_csrf()
    if not current_user():
        return jsonify(error="unauthorized"),401
    data=request.get_json(silent=True) or {}
    fmt=data.get("format","json")
    text=data.get("text")
    if not isinstance(text,str) or len(text)>200000 or fmt not in ("json","yaml"):
        return jsonify(error="Invalid schema input"),400
    try:
        schema=json.loads(text) if fmt=="json" else yaml.safe_load(text)
    except (ValueError,yaml.YAMLError) as exc:
        return jsonify(error="Could not parse schema",details=str(exc)[:250]),422
    errors=schema_problems(schema)
    if errors:return jsonify(error="Invalid JSON Schema",fields=errors),422
    return jsonify(schema=schema,json=json.dumps(schema,indent=2),yaml=yaml.safe_dump(schema,sort_keys=False,allow_unicode=True))
