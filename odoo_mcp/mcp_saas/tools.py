"""A discoverable, scoped, read-only MCP tool registry backed by Odoo JSON-2."""
from __future__ import annotations

from dataclasses import dataclass

from jsonschema import ValidationError, validate

from .errors import AppError
from .odoo_json2 import OdooJSON2
from .policies import PolicyEngine

_SAFE_FIELD_TYPES = frozenset({
    "integer", "char", "text", "html", "float", "monetary",
    "boolean", "date", "datetime", "selection",
})


@dataclass
class ToolContext:
    owner_id: str
    server_id: str
    server: dict
    scopes: set[str]
    policies: list[dict]
    connection: dict
    api_key: str
    odoo: OdooJSON2


def _schema(props: dict, *, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props, "required": required or [],
            "additionalProperties": False}


_MODEL = {"type": "string", "pattern": "^[a-z_][a-z0-9_.]*$"}
_FIELDS = {"type": "array", "items": {"type": "string"}, "maxItems": 30, "uniqueItems": True}
_DOMAIN = {"type": "array", "items": {"type": "array", "minItems": 3,
                                    "maxItems": 3}, "maxItems": 20}
_IDS = {"type": "array", "items": {"type": "integer", "minimum": 1},
        "minItems": 1, "maxItems": 100, "uniqueItems": True}


def _descriptors() -> list[dict]:
    return [
        {"name": "odoo_list_models", "description": "List explicitly authorized Odoo business models",
         "inputSchema": _schema({})},
        {"name": "odoo_get_model_schema", "description": "Show allowed primitive fields for one authorized model",
         "inputSchema": _schema({"model": _MODEL}, required=["model"])},
        {"name": "odoo_search_records", "description": "Bounded, policy-filtered Odoo record search",
         "inputSchema": _schema({
             "model": _MODEL, "fields": _FIELDS, "domain": _DOMAIN,
             "limit": {"type": "integer", "minimum": 1, "maximum": 100},
             "offset": {"type": "integer", "minimum": 0, "maximum": 10000},
         }, required=["model"])},
        {"name": "odoo_get_record", "description": "Read specific permitted Odoo record IDs",
         "inputSchema": _schema({"model": _MODEL, "ids": _IDS, "fields": _FIELDS},
                                required=["model", "ids"])},
    ]


class ToolRegistry:
    @staticmethod
    def _owned(context: ToolContext) -> bool:
        return (context.server.get("enabled") is True
                and context.server.get("id") == context.server_id
                and context.server.get("owner_id") == context.owner_id)

    @staticmethod
    def _read_models(context: ToolContext) -> list[str]:
        if not ToolRegistry._owned(context) or "odoo:read" not in context.scopes:
            return []
        models = []
        for policy in context.policies:
            model = policy.get("model_name")
            try:
                PolicyEngine.authorize(context.server, context.policies,
                                       context.scopes, "read", model, [])
            except AppError:
                continue
            if model not in models:
                models.append(model)
        return sorted(models)

    @staticmethod
    def list_tools(context: ToolContext) -> list[dict]:
        return _descriptors() if ToolRegistry._read_models(context) else []

    @staticmethod
    def _check_schema(context: ToolContext, model: str, fields: list[str]) -> dict:
        metadata = context.odoo.call(
            context.connection, context.api_key, model, "fields_get",
            {"attributes": ["type", "string"]})
        if not isinstance(metadata, dict):
            raise AppError("upstream_error", 502, "Unexpected Odoo schema response")
        for field in fields:
            if not isinstance(metadata.get(field), dict) or metadata[field].get("type") not in _SAFE_FIELD_TYPES:
                raise AppError("not_authorized", 403, "Field type is not allowed")
        return {field: {"type": metadata[field]["type"],
                        "string": str(metadata[field].get("string", field))[:100]}
                for field in fields}

    @staticmethod
    def invoke(context: ToolContext, name: str, arguments: dict) -> dict:
        descriptor = next((item for item in ToolRegistry.list_tools(context)
                           if item["name"] == name), None)
        if descriptor is None:
            raise AppError("not_authorized", 403, "Tool is not available")
        try:
            validate(instance=arguments, schema=descriptor["inputSchema"])
        except ValidationError as exc:
            raise AppError("invalid_input", 400, "Invalid tool arguments") from exc
        if name == "odoo_list_models":
            return {"models": ToolRegistry._read_models(context)}
        model = arguments["model"]
        fields = arguments.get("fields", [])
        permit = PolicyEngine.authorize(
            context.server, context.policies, context.scopes, "read", model, fields)
        if name == "odoo_get_model_schema":
            metadata = context.odoo.call(
                context.connection, context.api_key, model, "fields_get",
                {"attributes": ["type", "string"]})
            if not isinstance(metadata, dict):
                raise AppError("upstream_error", 502, "Unexpected Odoo schema response")
            safe = {field: {"type": metadata[field]["type"],
                            "string": str(metadata[field].get("string", field))[:100]}
                    for field in permit.fields
                    if isinstance(metadata.get(field), dict)
                    and metadata[field].get("type") in _SAFE_FIELD_TYPES}
            return {"model": model, "fields": safe}
        if name == "odoo_search_records":
            request_domain = PolicyEngine.validate_filter(
                arguments.get("domain", []), permit.fields)
            combined = list(permit.domain) + request_domain
            ToolRegistry._check_schema(context, model, permit.fields)
            records = context.odoo.call(
                context.connection, context.api_key, model, "search_read",
                {"domain": combined, "fields": permit.fields,
                 "limit": arguments.get("limit", 20), "offset": arguments.get("offset", 0)})
            return {"records": PolicyEngine.sanitize_records(records, permit.fields)}
        if name == "odoo_get_record":
            ToolRegistry._check_schema(context, model, permit.fields)
            records = context.odoo.call(
                context.connection, context.api_key, model, "read",
                {"ids": arguments["ids"], "fields": permit.fields})
            return {"records": PolicyEngine.sanitize_records(records, permit.fields)}
        raise AppError("not_authorized", 403, "Tool is not available")
