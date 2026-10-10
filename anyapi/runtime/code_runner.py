"""Client for the isolated code runner.

User-submitted Python/JavaScript is NEVER executed inside the Flask process. Instead it is
sent to a dedicated runner service (see `docs/RUNNER.md`) that runs each job in a
sandbox with CPU, memory, wall-clock, network and secret restrictions.

If `ANYAPI_RUNNER_URL` / `ANYAPI_RUNNER_TOKEN` are not configured, code processors can be
saved but not executed or published.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

import requests

LANGUAGES = ("python", "javascript")
MAX_CODE_BYTES = 64 * 1024


class RunnerUnavailable(Exception):
    pass


class RunnerError(Exception):
    def __init__(self, message: str, error_type: str = "code_error", logs: list[dict] | None = None):
        super().__init__(message)
        self.message = message
        self.error_type = error_type
        self.logs = logs or []


@dataclass
class RunnerResult:
    output: Any
    logs: list[dict[str, Any]]
    duration_ms: int


class CodeRunner:
    def __init__(self, url: str, token: str):
        self.url = url
        self.token = token

    @property
    def available(self) -> bool:
        return bool(self.url and self.token)

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "languages": list(LANGUAGES) if self.available else [],
            "reason": None if self.available else "No isolated code runner is configured (ANYAPI_RUNNER_URL).",
        }

    def run(self, language: str, code: str, input_data: Any, context: dict[str, Any], timeout_ms: int) -> RunnerResult:
        if not self.available:
            raise RunnerUnavailable("Code execution is disabled: no isolated runner is configured.")
        if language not in LANGUAGES:
            raise RunnerError(f"Unsupported language '{language}'", "invalid_processor")
        if len(code.encode()) > MAX_CODE_BYTES:
            raise RunnerError("Code exceeds 64 KB limit", "invalid_processor")
        payload = json.dumps(
            {
                "language": language,
                "code": code,
                "entrypoint": "process",
                "input": input_data,
                "context": context,
                "limits": {"timeout_ms": timeout_ms, "memory_mb": 128, "network": False},
            }
        ).encode()
        timestamp = str(int(time.time()))
        signature = hmac.new(self.token.encode(), timestamp.encode() + b"." + payload, hashlib.sha256).hexdigest()
        started = time.monotonic()
        try:
            resp = requests.post(
                f"{self.url}/v1/run",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-AnyAPI-Timestamp": timestamp,
                    "X-AnyAPI-Signature": signature,
                },
                timeout=(3, timeout_ms / 1000 + 3),
            )
        except requests.RequestException as exc:
            raise RunnerUnavailable(f"Runner unreachable: {type(exc).__name__}") from exc
        duration = int((time.monotonic() - started) * 1000)
        try:
            body = resp.json()
        except ValueError as exc:
            raise RunnerError(f"Runner returned an invalid response (HTTP {resp.status_code})", "runner_error") from exc
        logs = body.get("logs") or []
        if not resp.ok or not body.get("ok"):
            error = body.get("error") or {}
            raise RunnerError(error.get("message") or "Code execution failed", error.get("type") or "code_error", logs)
        return RunnerResult(output=body.get("output"), logs=logs, duration_ms=duration)
