"""Endpoint execution pipeline: validate input -> process -> validate output -> response."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from . import declarative, schema, edge_pipeline
from .code_runner import CodeRunner, RunnerError, RunnerUnavailable

ALLOWED_RESPONSE_HEADER_PREFIXES = ("x-",)
ALLOWED_RESPONSE_HEADERS = {"cache-control", "content-language"}
BLOCKED_RESPONSE_HEADERS = {"x-frame-options", "x-content-type-options", "x-powered-by", "x-request-id"}


@dataclass
class ExecutionResult:
    status_code: int
    body: Any
    headers: dict[str, str] = field(default_factory=dict)
    logs: list[dict[str, Any]] = field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None
    duration_ms: int = 0

    @property
    def success(self) -> bool:
        return self.error_type is None and self.status_code < 400


def snapshot_config(endpoint: dict[str, Any]) -> dict[str, Any]:
    """The immutable config stored in endpoint_versions and executed by the gateway."""
    return {
        "name": endpoint.get("name"),
        "description": endpoint.get("description"),
        "method": endpoint.get("method"),
        "visibility": endpoint.get("visibility"),
        "input_schema": endpoint.get("input_schema") or {"type": "object"},
        "output_schema": endpoint.get("output_schema") or {"type": "object"},
        "processor": endpoint.get("processor") or {"type": "visual", "steps": []},
        "response_config": endpoint.get("response_config") or {"status_code": 200, "headers": {}},
        "settings": endpoint.get("settings") or {},
    }


def safe_response_headers(headers: Any) -> dict[str, str]:
    if not isinstance(headers, dict):
        return {}
    result: dict[str, str] = {}
    for name, value in headers.items():
        lower = str(name).lower().strip()
        if lower in BLOCKED_RESPONSE_HEADERS:
            continue
        if lower in ALLOWED_RESPONSE_HEADERS or lower.startswith(ALLOWED_RESPONSE_HEADER_PREFIXES):
            text = str(value)
            if "\n" not in text and "\r" not in text and len(text) <= 500:
                result[str(name)] = text
    return result


def validate_config(config: dict[str, Any], connector_ids: set[str], runner: CodeRunner) -> list[dict[str, str]]:
    problems: list[dict[str, str]] = []
    for key in ("input_schema", "output_schema"):
        for problem in schema.schema_problems(config.get(key)):
            problems.append({"path": f"{key}{'/' + problem['path'] if problem['path'] else ''}", "message": problem["message"]})
    processor = config.get("processor") or {}
    kind = processor.get("type")
    if kind == "edge_pipeline":
        problems.extend(edge_pipeline.validate_pipeline(processor, connector_ids))
    elif kind == "visual":
        problems.append({"path":"processor.type","message":"Legacy visual processors cannot be newly published; use Edge Function pipeline"})
    elif kind == "code":
        problems.append({"path":"processor.type","message":"Code processors are not available in V1"})
        if processor.get("language") not in ("python", "javascript"):
            problems.append({"path": "processor.language", "message": "Choose python or javascript"})
        if not str(processor.get("code") or "").strip():
            problems.append({"path": "processor.code", "message": "Code is empty"})
        if not runner.available:
            problems.append(
                {
                    "path": "processor",
                    "message": "Code processors cannot be published: no isolated runner is configured.",
                }
            )
    else:
        problems.append({"path": "processor.type", "message": "Unsupported processor type"})
    status_code = (config.get("response_config") or {}).get("status_code", 200)
    if not isinstance(status_code, int) or not 200 <= status_code <= 299:
        problems.append({"path": "response_config.status_code", "message": "Success status must be between 200 and 299"})
    return problems


def execute(
    config: dict[str, Any],
    input_data: Any,
    context: dict[str, Any],
    *,
    connectors: dict[str, dict[str, Any]],
    runner: CodeRunner,
) -> ExecutionResult:
    started = time.monotonic()
    settings = config.get("settings") or {}
    timeout_ms = max(500, min(int(settings.get("timeout_ms") or 10000), 25000))
    deadline = started + timeout_ms / 1000
    logs: list[dict[str, Any]] = []

    def log(level: str, message: str) -> None:
        logs.append({"t": int((time.monotonic() - started) * 1000), "level": level, "message": message[:1000]})

    def finish(result: ExecutionResult) -> ExecutionResult:
        result.logs = logs + result.logs
        result.duration_ms = int((time.monotonic() - started) * 1000)
        return result

    input_errors = schema.validate(input_data, config.get("input_schema") or {"type": "object"})
    if input_errors:
        log("warn", f"Input validation failed with {len(input_errors)} error(s)")
        return finish(
            ExecutionResult(
                400,
                {"error": {"type": "input_validation", "message": "Request does not match the input schema", "fields": input_errors}},
                error_type="input_validation",
                error_message="Request does not match the input schema",
            )
        )
    log("info", "Input validated")

    processor = config.get("processor") or {}
    try:
        if processor.get("type") == "edge_pipeline":
            from anyapi.services import supabase
            from anyapi.config import load_settings
            steps=processor.get("steps",[])
            if not isinstance(steps,list) or not 1<=len(steps)<=edge_pipeline.MAX_STEPS:
                raise RunnerError("Invalid pipeline step count","invalid_processor")
            names={s["function"] for s in steps if isinstance(s,dict) and isinstance(s.get("function"),str)}
            if len(names)>edge_pipeline.MAX_STEPS or any(not edge_pipeline.SLUG.fullmatch(s) for s in names):
                raise RunnerError("Invalid Edge Function identifiers","invalid_processor")
            catalog={}
            if names:
                records=supabase().service().select("edge_function_catalog",{"select":"slug,input_schema,output_schema","enabled":"eq.true","slug":"in.("+",".join(sorted(names))+")"})
                catalog={row["slug"]:row for row in records}
            output=edge_pipeline.run_pipeline(processor,input_data,context,catalog,load_settings(),deadline,log)
        elif processor.get("type") == "code":
            raise RunnerUnavailable("Code processors are disabled in AnyAPI V1")
            result = runner.run(processor.get("language", ""), processor.get("code", ""), input_data, context, timeout_ms)
            logs.extend(result.logs)
            output = result.output
            log("info", f"Code processor finished in {result.duration_ms}ms")
        else:
            state = {"input": input_data, "vars": {}, "steps": {}, "output": {}, "context": context}
            output = declarative.run_steps(
                processor.get("steps") or [], state, connectors=connectors, deadline=deadline, log=log
            )
            log("info", f"Visual processor ran {len(processor.get('steps') or [])} step(s)")
    except RunnerUnavailable as exc:
        log("error", str(exc))
        return finish(
            ExecutionResult(
                503,
                {"error": {"type": "runtime_unavailable", "message": str(exc)}},
                error_type="runtime_unavailable",
                error_message=str(exc),
            )
        )
    except RunnerError as exc:
        logs.extend(exc.logs)
        log("error", exc.message)
        status = 504 if exc.error_type == "timeout" else 500
        return finish(
            ExecutionResult(status, {"error": {"type": exc.error_type, "message": exc.message}}, error_type=exc.error_type, error_message=exc.message)
        )
    except declarative.ProcessorError as exc:
        log("error", exc.message)
        status = {"timeout": 504, "upstream_error": 502, "egress_blocked": 502}.get(exc.error_type, 500)
        body = {"error": {"type": exc.error_type, "message": exc.message, "step": exc.step}}
        return finish(ExecutionResult(status, body, error_type=exc.error_type, error_message=exc.message))

    output_errors = schema.validate(output, config.get("output_schema") or {"type": "object"})
    if output_errors:
        log("error", f"Output validation failed with {len(output_errors)} error(s)")
        return finish(
            ExecutionResult(
                500,
                {
                    "error": {
                        "type": "output_validation",
                        "message": "Processor output does not match the output schema",
                        "fields": output_errors,
                    }
                },
                error_type="output_validation",
                error_message="Processor output does not match the output schema",
            )
        )
    log("info", "Output validated")

    response_config = config.get("response_config") or {}
    status_code = response_config.get("status_code", 200)
    if not isinstance(status_code, int) or not 200 <= status_code <= 299:
        status_code = 200
    return finish(ExecutionResult(status_code, output, headers=safe_response_headers(response_config.get("headers"))))
