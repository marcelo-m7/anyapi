"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


def _load_env_files() -> None:
    """Load local env files for development without overriding real env vars.

    Vercel injects env vars natively, so this only matters for local/gunicorn runs.
    """
    root = Path(__file__).resolve().parent.parent
    for name in (".env.development.local", ".env.local", ".env"):
        path = root / name
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip().removeprefix("export ").strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key, value)


def _first(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_anon_key: str
    supabase_service_key: str
    secret_key: str
    encryption_key_material: str
    public_base_url: str
    dev_redirect_url: str
    is_production: bool
    runner_url: str
    runner_token: str
    max_payload_bytes: int
    execution_retention_days: int

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key and self.supabase_service_key)

    @property
    def runner_configured(self) -> bool:
        return bool(self.runner_url and self.runner_token)


def load_settings() -> Settings:
    _load_env_files()
    jwt_secret = _first("SUPABASE_JWT_SECRET")
    secret_key = _first("ANYAPI_SECRET_KEY", "FLASK_SECRET_KEY")
    if not secret_key and jwt_secret:
        secret_key = hashlib.sha256(f"anyapi-session:{jwt_secret}".encode()).hexdigest()
    encryption_material = _first("ANYAPI_ENCRYPTION_KEY") or (
        f"anyapi-connectors:{jwt_secret}" if jwt_secret else ""
    )
    return Settings(
        supabase_url=_first("SUPABASE_URL", "NEXT_PUBLIC_SUPABASE_URL").rstrip("/"),
        supabase_anon_key=_first(
            "SUPABASE_ANON_KEY",
            "NEXT_PUBLIC_SUPABASE_ANON_KEY",
            "SUPABASE_PUBLISHABLE_KEY",
            "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY",
        ),
        supabase_service_key=_first("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_SECRET_KEY"),
        secret_key=secret_key or os.urandom(32).hex(),
        encryption_key_material=encryption_material,
        public_base_url=_first("ANYAPI_PUBLIC_URL").rstrip("/"),
        dev_redirect_url=_first("NEXT_PUBLIC_DEV_SUPABASE_REDIRECT_URL"),
        is_production=os.environ.get("VERCEL_ENV") == "production",
        runner_url=_first("ANYAPI_RUNNER_URL").rstrip("/"),
        runner_token=_first("ANYAPI_RUNNER_TOKEN"),
        max_payload_bytes=int(_first("ANYAPI_MAX_PAYLOAD_BYTES") or 1_048_576),
        execution_retention_days=int(_first("ANYAPI_EXECUTION_RETENTION_DAYS") or 30),
    )
