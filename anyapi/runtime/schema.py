"""JSON Schema (draft 2020-12) helpers: validation with structured errors and example generation."""

from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

MAX_ERRORS = 25


def schema_problems(schema: Any) -> list[dict[str, str]]:
    """Return problems with the schema document itself (empty list when valid)."""
    if not isinstance(schema, dict):
        return [{"path": "", "message": "Schema must be a JSON object."}]
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        path = "/".join(str(p) for p in exc.absolute_path)
        return [{"path": path, "message": exc.message}]
    return []


def validate(instance: Any, schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate `instance` and return a list of {path, message, keyword} errors."""
    validator = Draft202012Validator(schema)
    errors = []
    for error in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path)):
        path = "/".join(str(p) for p in error.absolute_path)
        errors.append({"path": path or "(root)", "message": error.message, "keyword": error.validator})
        if len(errors) >= MAX_ERRORS:
            break
    return errors


def example_for(schema: Any, depth: int = 0) -> Any:
    """Build a plausible example payload from a schema (uses examples/defaults when present)."""
    if not isinstance(schema, dict) or depth > 8:
        return None
    if "examples" in schema and isinstance(schema["examples"], list) and schema["examples"]:
        return schema["examples"][0]
    if "default" in schema:
        return schema["default"]
    if "const" in schema:
        return schema["const"]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), kind[0] if kind else None)
    if kind == "object" or (kind is None and "properties" in schema):
        props = schema.get("properties") or {}
        return {name: example_for(sub, depth + 1) for name, sub in props.items()}
    if kind == "array":
        item = example_for(schema.get("items") or {"type": "string"}, depth + 1)
        return [item] if item is not None else []
    if kind == "string":
        fmt = schema.get("format")
        return {
            "uri": "https://example.com",
            "url": "https://example.com",
            "email": "user@example.com",
            "date-time": "2026-01-01T00:00:00Z",
            "date": "2026-01-01",
            "uuid": "00000000-0000-4000-8000-000000000000",
        }.get(fmt, "string")
    if kind == "integer":
        return int(schema.get("minimum", 0))
    if kind == "number":
        return float(schema.get("minimum", 0))
    if kind == "boolean":
        return True
    if kind == "null":
        return None
    return None
