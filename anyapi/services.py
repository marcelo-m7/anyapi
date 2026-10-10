"""Shared server-side services: connectors loading, execution logging, rate limiting."""

from __future__ import annotations

import time
import uuid
from typing import Any

from flask import current_app

from .runtime.code_runner import CodeRunner
from .security import SecretBox, redact
from .supabase import Supabase, SupabaseError

CONNECTOR_PUBLIC_COLUMNS = "id,project_id,owner_id,name,type,config,secret_hint,created_at,updated_at"
API_KEY_PUBLIC_COLUMNS = "id,owner_id,project_id,endpoint_id,name,prefix,last_used_at,revoked_at,created_at"


def supabase() -> Supabase:
    return current_app.extensions["anyapi.supabase"]


def runner() -> CodeRunner:
    return current_app.extensions["anyapi.runner"]


def secret_box() -> SecretBox:
    return current_app.extensions["anyapi.secrets"]


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:20]}"


def referenced_connector_ids(processor: dict[str, Any] | None) -> set[str]:
    if not processor or processor.get("type") != "visual":
        return set()
    return {
        str(step["connector_id"])
        for step in processor.get("steps") or []
        if isinstance(step, dict) and step.get("type") == "http" and step.get("connector_id")
    }


def load_connectors(project_id: str, ids: set[str]) -> dict[str, dict[str, Any]]:
    """Load connectors (with decrypted secrets) via the service role. Caller must have authorized access."""
    if not ids:
        return {}
    rows = supabase().service().select(
        "connectors",
        {
            "select": "id,name,type,config,secret_ciphertext",
            "project_id": f"eq.{project_id}",
            "id": f"in.({','.join(sorted(ids))})",
        },
    )
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        secret = ""
        if row.get("secret_ciphertext"):
            secret = secret_box().decrypt(row["secret_ciphertext"])
        result[str(row["id"])] = {"name": row["name"], "type": row["type"], "config": row["config"], "secret": secret}
    return result


def sync_endpoint_connectors(client, endpoint_id: str, owner_id: str, connector_ids: set[str]) -> None:
    client.delete("endpoint_connectors", {"endpoint_id": f"eq.{endpoint_id}"})
    if connector_ids:
        client.insert(
            "endpoint_connectors",
            [{"endpoint_id": endpoint_id, "connector_id": cid, "owner_id": owner_id} for cid in connector_ids],
            select="endpoint_id",
        )


def log_execution(
    *,
    endpoint_id: str,
    owner_id: str,
    version_id: str | None,
    version: int | None,
    source: str,
    request_id: str,
    method: str,
    result,
    request_body: Any,
    secrets_to_hide: list[str] | None = None,
) -> str | None:
    """Persist execution metadata with redacted payloads. Never raises."""
    try:
        response_body = result.body
        if secrets_to_hide:
            import json

            text = json.dumps(response_body, default=str)
            for secret in secrets_to_hide:
                if secret and len(secret) >= 4:
                    text = text.replace(secret, "[redacted]")
            response_body = json.loads(text)
        row = supabase().service().insert(
            "executions",
            {
                "endpoint_id": endpoint_id,
                "owner_id": owner_id,
                "version_id": version_id,
                "version": version,
                "source": source,
                "request_id": request_id,
                "method": method,
                "status_code": result.status_code,
                "duration_ms": result.duration_ms,
                "success": result.success,
                "error_type": result.error_type,
                "error_message": (result.error_message or "")[:1000] or None,
                "request_body": redact(request_body),
                "response_body": redact(response_body),
                "logs": result.logs[:200],
            },
            select="id",
        )
        return row.get("id") if isinstance(row, dict) else None
    except Exception as exc:  # logging must never break a request
        current_app.logger.warning("failed to log execution %s: %s", request_id, exc)
        return None


def consume_rate_limit(key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int, int]:
    """Fixed-window limiter stored in Postgres so it works across serverless instances.

    Returns (allowed, remaining, reset_epoch). Fails open if the database is unreachable.
    """
    try:
        rows = supabase().service().rpc(
            "consume_rate_limit", {"p_key": key[:200], "p_limit": limit, "p_window_seconds": window_seconds}
        )
        row = rows[0] if isinstance(rows, list) and rows else rows or {}
        from datetime import datetime

        reset_at = row.get("reset_at")
        reset = int(datetime.fromisoformat(reset_at.replace("Z", "+00:00")).timestamp()) if reset_at else int(time.time()) + window_seconds
        return bool(row.get("allowed", True)), int(row.get("remaining", limit)), reset
    except SupabaseError as exc:
        current_app.logger.warning("rate limiter unavailable: %s", exc.message)
        return True, limit, int(time.time()) + window_seconds
