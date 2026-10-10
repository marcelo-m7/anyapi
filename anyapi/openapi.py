"""OpenAPI 3.1 document and code samples for a published endpoint."""

from __future__ import annotations

import json
from typing import Any

from .runtime.schema import example_for

BODY_METHODS = ("POST", "PUT", "PATCH")


def endpoint_url(base_url: str, username: str, project: str, endpoint: str) -> str:
    return f"{base_url.rstrip('/')}/{username}/{project}/{endpoint}"


def _query_parameters(schema: dict[str, Any]) -> list[dict[str, Any]]:
    required = set(schema.get("required") or [])
    return [
        {
            "name": name,
            "in": "query",
            "required": name in required,
            "description": (sub or {}).get("description", ""),
            "schema": sub or {},
        }
        for name, sub in (schema.get("properties") or {}).items()
    ]


def build_document(resolved: dict[str, Any], base_url: str) -> dict[str, Any]:
    config = resolved["config"]
    method = (config.get("method") or "POST").upper()
    path = f"/{resolved['username']}/{resolved['project_slug']}/{resolved['endpoint_slug']}"
    input_schema = config.get("input_schema") or {"type": "object"}
    output_schema = config.get("output_schema") or {"type": "object"}
    status = str((config.get("response_config") or {}).get("status_code", 200))
    error_schema = {
        "type": "object",
        "properties": {
            "error": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "message": {"type": "string"},
                    "fields": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["type", "message"],
            },
            "request_id": {"type": "string"},
        },
    }
    operation: dict[str, Any] = {
        "operationId": f"{resolved['project_slug']}_{resolved['endpoint_slug']}".replace("-", "_"),
        "summary": config.get("name") or resolved["endpoint_slug"],
        "description": config.get("description") or "",
        "responses": {
            status: {
                "description": "Successful response",
                "content": {"application/json": {"schema": output_schema, "example": example_for(output_schema)}},
            },
            "400": {"description": "Input validation failed", "content": {"application/json": {"schema": error_schema}}},
            "429": {"description": "Rate limit exceeded", "content": {"application/json": {"schema": error_schema}}},
            "500": {"description": "Processing or output validation error", "content": {"application/json": {"schema": error_schema}}},
        },
    }
    if method in BODY_METHODS:
        operation["requestBody"] = {
            "required": True,
            "content": {"application/json": {"schema": input_schema, "example": example_for(input_schema)}},
        }
    else:
        operation["parameters"] = _query_parameters(input_schema)
    document: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {
            "title": f"{resolved['username']}/{resolved['project_slug']}/{resolved['endpoint_slug']}",
            "version": str(resolved.get("version") or 1),
            "description": config.get("description") or f"Published with AnyAPI from project {resolved.get('project_name')}.",
        },
        "servers": [{"url": base_url.rstrip("/")}],
        "paths": {path: {method.lower(): operation}},
    }
    if config.get("visibility") == "private":
        document["components"] = {
            "securitySchemes": {"apiKey": {"type": "http", "scheme": "bearer", "description": "AnyAPI key (aapi_...)"}}
        }
        operation["security"] = [{"apiKey": []}]
        operation["responses"]["401"] = {"description": "Missing or invalid API key", "content": {"application/json": {"schema": error_schema}}}
    return document


def code_samples(url: str, method: str, example: Any, private: bool) -> dict[str, str]:
    method = method.upper()
    body = json.dumps(example if example is not None else {}, indent=2, ensure_ascii=False)
    auth_header_curl = ' \\\n  -H "Authorization: Bearer $ANYAPI_KEY"' if private else ""
    auth_py = '\n    "Authorization": f"Bearer {os.environ[\'ANYAPI_KEY\']}",' if private else ""
    auth_js = "\n    Authorization: `Bearer ${process.env.ANYAPI_KEY}`," if private else ""
    if method in BODY_METHODS:
        curl = f"curl -X {method} '{url}' \\\n  -H 'Content-Type: application/json'{auth_header_curl} \\\n  -d '{json.dumps(example if example is not None else {}, ensure_ascii=False)}'"
        python = (
            f"import os\nimport requests\n\nresponse = requests.{method.lower()}(\n    \"{url}\",\n"
            f"    headers={{{auth_py}\n    }},\n    json={body.replace(chr(10), chr(10) + '    ')},\n    timeout=30,\n)\nprint(response.status_code, response.json())"
        )
        javascript = (
            f"const response = await fetch(\"{url}\", {{\n  method: \"{method}\",\n  headers: {{\n    \"Content-Type\": \"application/json\",{auth_js}\n  }},\n"
            f"  body: JSON.stringify({body.replace(chr(10), chr(10) + '  ')}),\n}});\nconsole.log(response.status, await response.json());"
        )
    else:
        query = ""
        if isinstance(example, dict) and example:
            from urllib.parse import urlencode

            query = "?" + urlencode({k: v if not isinstance(v, (dict, list)) else json.dumps(v) for k, v in example.items()})
        curl = f"curl -X {method} '{url}{query}'{auth_header_curl}"
        python = (
            f"import os\nimport requests\n\nresponse = requests.{method.lower()}(\n    \"{url}\",\n    headers={{{auth_py}\n    }},\n"
            f"    params={body.replace(chr(10), chr(10) + '    ')},\n    timeout=30,\n)\nprint(response.status_code, response.json())"
        )
        javascript = (
            f"const response = await fetch(\"{url}{query}\", {{\n  method: \"{method}\",\n  headers: {{{auth_js}\n  }},\n}});\n"
            "console.log(response.status, await response.json());"
        )
    if not private:
        python = python.replace("import os\n", "")
    return {"curl": curl, "python": python, "javascript": javascript}
