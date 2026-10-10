"""Declarative (visual) processor: a vertical list of pre-authorized operations.

State model passed between steps:
    {"input": <request body/query>, "vars": {}, "steps": {<step_id>: result}, "output": {}, "context": {...}}

Writes are only allowed to `output.*` and `vars.*`. The endpoint response is `state["output"]`.
No user code is ever evaluated here: every operation is a fixed Python function.
"""

from __future__ import annotations

import copy
import json
import re
import time
from typing import Any, Callable
from urllib.parse import parse_qs, quote, urljoin, urlparse

from . import safe_http
from .paths import PathError, delete_path, get_path, has_path, render_template, set_path

MAX_STEPS = 50
WRITABLE_ROOTS = ("output", "vars")
_BLOCKED_STEP_HEADERS = {"host", "authorization", "cookie", "content-length", "transfer-encoding", "connection", "proxy-authorization"}


class ProcessorError(Exception):
    def __init__(self, message: str, step: int | None = None, error_type: str = "processor_error"):
        super().__init__(message)
        self.message = message
        self.step = step
        self.error_type = error_type


def _writable(path: str) -> str:
    root = path.split(".", 1)[0].split("[", 1)[0]
    if root not in WRITABLE_ROOTS:
        raise PathError(f"Can only write to output.* or vars.* (got '{path}')")
    return path


def _slugify(value: str) -> str:
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", value.lower())).strip("-")


def _to_number(value: Any) -> float | int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    number = float(str(value).strip())
    return int(number) if number.is_integer() else number


def _to_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on", "y")
    return bool(value)


def _regex(value: Any, pattern: str) -> Any:
    if len(pattern) > 200:
        raise ProcessorError("Regex pattern too long (max 200 chars)")
    match = re.search(pattern, str(value)[:20000])
    if not match:
        return None
    return match.group(1) if match.groups() else match.group(0)


TRANSFORMS: dict[str, Callable[[Any, Any], Any]] = {
    "uppercase": lambda v, a: str(v).upper(),
    "lowercase": lambda v, a: str(v).lower(),
    "trim": lambda v, a: str(v).strip(),
    "slugify": lambda v, a: _slugify(str(v)),
    "to_string": lambda v, a: v if isinstance(v, str) else json.dumps(v, ensure_ascii=False),
    "to_number": lambda v, a: _to_number(v),
    "to_integer": lambda v, a: int(_to_number(v)),
    "to_boolean": lambda v, a: _to_bool(v),
    "length": lambda v, a: len(v) if isinstance(v, (str, list, dict)) else 0,
    "split": lambda v, a: str(v).split(a if a not in (None, "") else ","),
    "join": lambda v, a: (a if a is not None else ",").join(str(x) for x in (v or [])),
    "replace": lambda v, a: str(v).replace(str((a or {}).get("find", "")), str((a or {}).get("with", ""))),
    "regex_extract": lambda v, a: _regex(v, str(a or "")),
    "round": lambda v, a: round(_to_number(v), int(a or 0)),
    "default": lambda v, a: a if v in (None, "") else v,
    "json_parse": lambda v, a: json.loads(v) if isinstance(v, str) else v,
    "url_host": lambda v, a: urlparse(str(v)).hostname,
    "url_path": lambda v, a: urlparse(str(v)).path,
    "url_query": lambda v, a: {k: vs[0] if len(vs) == 1 else vs for k, vs in parse_qs(urlparse(str(v)).query).items()},
    "first": lambda v, a: v[0] if isinstance(v, list) and v else None,
    "last": lambda v, a: v[-1] if isinstance(v, list) and v else None,
    "keys": lambda v, a: list(v.keys()) if isinstance(v, dict) else [],
    "unique": lambda v, a: [json.loads(x) for x in dict.fromkeys(json.dumps(i, sort_keys=True) for i in v)]
    if isinstance(v, list)
    else v,
}

OPERATORS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": lambda a, b: a == b,
    "neq": lambda a, b: a != b,
    "gt": lambda a, b: a is not None and b is not None and _to_number(a) > _to_number(b),
    "gte": lambda a, b: a is not None and b is not None and _to_number(a) >= _to_number(b),
    "lt": lambda a, b: a is not None and b is not None and _to_number(a) < _to_number(b),
    "lte": lambda a, b: a is not None and b is not None and _to_number(a) <= _to_number(b),
    "contains": lambda a, b: a is not None and str(b) in (a if isinstance(a, (list, str)) else str(a)),
    "exists": lambda a, b: a is not None,
    "not_exists": lambda a, b: a is None,
}

STEP_TYPES = ("set", "copy", "rename", "remove", "transform", "filter", "map_array", "merge", "http")


def _connector_url(base_url: str, path_template: str, state: dict[str, Any]) -> str:
    """Render a path template against the state, URL-encoding every substituted value.

    The host is always the connector's base URL; input values can only become
    encoded path segments, never a new host or scheme.
    """

    def encode(value: Any) -> Any:
        if isinstance(value, str):
            return quote(value, safe="")
        if isinstance(value, (int, float, bool)):
            return quote(str(value), safe="")
        return ""

    rendered = re.sub(
        r"\{\{\s*([a-zA-Z0-9_.\-\[\]]+)\s*\}\}",
        lambda m: str(encode(get_path(state, m.group(1)))),
        path_template or "",
    )
    base = base_url if base_url.endswith("/") else base_url + "/"
    final = urljoin(base, rendered.lstrip("/")) if rendered else base_url
    base_parsed, final_parsed = urlparse(base_url), urlparse(final)
    if (final_parsed.scheme, final_parsed.netloc) != (base_parsed.scheme, base_parsed.netloc):
        raise ProcessorError("Connector path cannot change the destination host")
    base_path = base_parsed.path.rstrip("/")
    if base_path and not final_parsed.path.startswith(base_path):
        raise ProcessorError("Connector path cannot escape the connector base path")
    if ".." in final_parsed.path.split("/"):
        raise ProcessorError("Connector path cannot contain '..'")
    return final


def call_connector(connector: dict[str, Any], step: dict[str, Any], state: dict[str, Any], deadline: float) -> dict[str, Any]:
    config = connector.get("config") or {}
    secret = connector.get("secret") or ""
    base_url = str(config.get("base_url") or "")
    if not base_url:
        raise ProcessorError("Connector has no base URL")
    method = str(step.get("method") or config.get("method") or "GET").upper()
    if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
        raise ProcessorError(f"Unsupported HTTP method {method}")
    url = _connector_url(base_url, str(step.get("path") or ""), state)

    headers: dict[str, str] = {str(k): str(v) for k, v in (config.get("headers") or {}).items()}
    for name, value in (render_template(step.get("headers") or {}, state)).items():
        if str(name).lower() in _BLOCKED_STEP_HEADERS:
            raise ProcessorError(f"Header '{name}' cannot be set from a step")
        headers[str(name)] = "" if value is None else str(value)
    params = {**(config.get("query") or {}), **(render_template(step.get("query") or {}, state))}
    params = {k: v for k, v in params.items() if v is not None}

    auth = config.get("auth") or {}
    auth_type = auth.get("type", "none")
    if auth_type != "none" and not secret:
        raise ProcessorError("Connector credentials are missing")
    if auth_type == "bearer":
        headers["Authorization"] = f"Bearer {secret}"
    elif auth_type == "api_key":
        if auth.get("in") == "query":
            params[str(auth.get("name") or "api_key")] = secret
        else:
            headers[str(auth.get("name") or "X-API-Key")] = secret

    body = None
    if method in ("POST", "PUT", "PATCH", "DELETE"):
        default_body = config.get("body")
        body = render_template(step["body"], state) if step.get("body") is not None else render_template(default_body, state)

    timeout_ms = min(int(step.get("timeout_ms") or config.get("timeout_ms") or 8000), 15000)
    remaining = deadline - time.monotonic()
    if remaining <= 0.2:
        raise ProcessorError("Execution deadline reached before HTTP call", error_type="timeout")
    try:
        result = safe_http.request(
            method, url, headers=headers, params=params, json_body=body, timeout_s=min(timeout_ms / 1000, remaining)
        )
    except safe_http.EgressBlocked as exc:
        raise ProcessorError(f"Blocked outbound request: {exc}", error_type="egress_blocked") from exc
    except TimeoutError as exc:
        raise ProcessorError("Upstream request timed out", error_type="timeout") from exc
    except Exception as exc:  # network errors
        raise ProcessorError(f"Upstream request failed: {type(exc).__name__}", error_type="upstream_error") from exc

    response_body = result.body
    if config.get("response_path"):
        response_body = get_path({"body": response_body}, f"body.{config['response_path']}")
    if step.get("fail_on_error", True) and result.status >= 400:
        raise ProcessorError(f"Upstream returned HTTP {result.status}", error_type="upstream_error")
    return {"status": result.status, "headers": result.headers, "body": response_body, "duration_ms": result.duration_ms}


def run_steps(
    steps: list[dict[str, Any]],
    state: dict[str, Any],
    *,
    connectors: dict[str, dict[str, Any]],
    deadline: float,
    log: Callable[[str, str], None],
) -> dict[str, Any]:
    if not isinstance(steps, list):
        raise ProcessorError("Processor steps must be a list")
    if len(steps) > MAX_STEPS:
        raise ProcessorError(f"Too many steps (max {MAX_STEPS})")
    for index, step in enumerate(steps):
        if time.monotonic() > deadline:
            raise ProcessorError("Execution timed out", index, "timeout")
        if not isinstance(step, dict):
            raise ProcessorError("Each step must be an object", index)
        if step.get("disabled"):
            continue
        kind = step.get("type")
        label = step.get("label") or kind
        try:
            if kind == "set":
                set_path(state, _writable(step["to"]), render_template(copy.deepcopy(step.get("value")), state))
            elif kind == "copy":
                set_path(state, _writable(step["to"]), copy.deepcopy(get_path(state, step["from"])))
            elif kind == "rename":
                value = copy.deepcopy(get_path(state, step["from"]))
                _writable(step["from"])
                if has_path(state, step["from"]):
                    delete_path(state, step["from"])
                set_path(state, _writable(step["to"]), value)
            elif kind == "remove":
                delete_path(state, _writable(step["path"]))
            elif kind == "transform":
                fn = TRANSFORMS.get(step.get("fn", ""))
                if not fn:
                    raise ProcessorError(f"Unknown transform '{step.get('fn')}'", index)
                value = get_path(state, step["from"])
                if value is None and step.get("fn") != "default":
                    result = None
                else:
                    result = fn(value, render_template(step.get("arg"), state))
                set_path(state, _writable(step.get("to") or step["from"]), result)
            elif kind == "filter":
                items = get_path(state, step["from"]) or []
                if not isinstance(items, list):
                    raise ProcessorError(f"'{step['from']}' is not an array", index)
                op = OPERATORS.get(step.get("operator", "eq"))
                if not op:
                    raise ProcessorError(f"Unknown operator '{step.get('operator')}'", index)
                expected = render_template(step.get("value"), state)
                field = step.get("field")
                kept = [item for item in items if op(get_path(item, field) if field else item, expected)]
                set_path(state, _writable(step.get("to") or step["from"]), kept)
            elif kind == "map_array":
                items = get_path(state, step["from"]) or []
                if not isinstance(items, list):
                    raise ProcessorError(f"'{step['from']}' is not an array", index)
                fields = step.get("fields") or {}
                mapped = [{name: get_path({"item": item}, src) for name, src in fields.items()} for item in items[:5000]]
                set_path(state, _writable(step["to"]), mapped)
            elif kind == "merge":
                source = get_path(state, step["from"])
                target_path = _writable(step.get("to") or "output")
                target = get_path(state, target_path)
                if not isinstance(source, dict):
                    raise ProcessorError(f"'{step['from']}' is not an object", index)
                merged = {**(target if isinstance(target, dict) else {}), **copy.deepcopy(source)}
                if target_path == "output":
                    state["output"] = merged
                else:
                    set_path(state, target_path, merged)
            elif kind == "http":
                connector = connectors.get(str(step.get("connector_id")))
                if not connector:
                    raise ProcessorError("Connector not found or not attached to this project", index)
                result = call_connector(connector, step, state, deadline)
                step_id = step.get("id") or f"step{index + 1}"
                state["steps"][step_id] = result
                if step.get("save_to"):
                    set_path(state, _writable(step["save_to"]), result["body"])
                log("info", f"[{index + 1}] http {connector.get('name')} -> {result['status']} in {result['duration_ms']}ms")
                continue
            else:
                raise ProcessorError(f"Unknown step type '{kind}'", index)
        except ProcessorError as exc:
            exc.step = index if exc.step is None else exc.step
            raise
        except (PathError, KeyError) as exc:
            missing = f"missing field {exc}" if isinstance(exc, KeyError) else str(exc)
            raise ProcessorError(f"Step {index + 1} ({label}): {missing}", index, "invalid_step") from exc
        except (ValueError, TypeError) as exc:
            raise ProcessorError(f"Step {index + 1} ({label}) failed: {exc}", index) from exc
        log("debug", f"[{index + 1}] {kind} ok")
    return state["output"]


def validate_steps(steps: Any, connector_ids: set[str]) -> list[dict[str, str]]:
    """Static validation used before publishing."""
    problems: list[dict[str, str]] = []
    if not isinstance(steps, list):
        return [{"path": "processor.steps", "message": "Steps must be a list"}]
    required = {
        "set": ("to",), "copy": ("from", "to"), "rename": ("from", "to"), "remove": ("path",),
        "transform": ("from", "fn"), "filter": ("from",), "map_array": ("from", "to"), "merge": ("from",),
        "http": ("connector_id",),
    }
    for index, step in enumerate(steps):
        where = f"processor.steps[{index}]"
        if not isinstance(step, dict) or step.get("type") not in STEP_TYPES:
            problems.append({"path": where, "message": "Unknown or missing step type"})
            continue
        for field in required[step["type"]]:
            if not step.get(field):
                problems.append({"path": f"{where}.{field}", "message": f"'{field}' is required"})
        write_fields = ("save_to",) if step["type"] == "http" else ("to", "path")
        if step["type"] == "rename":
            write_fields = ("from", "to")
        for field in write_fields:
            target = step.get(field)
            if not target:
                continue
            try:
                _writable(target)
            except PathError as exc:
                problems.append({"path": f"{where}.{field}", "message": str(exc)})
        if step["type"] == "transform" and step.get("fn") not in TRANSFORMS:
            problems.append({"path": f"{where}.fn", "message": f"Unknown transform '{step.get('fn')}'"})
        if step["type"] == "http" and step.get("connector_id") and str(step["connector_id"]) not in connector_ids:
            problems.append({"path": f"{where}.connector_id", "message": "Connector is not available in this project"})
    return problems
