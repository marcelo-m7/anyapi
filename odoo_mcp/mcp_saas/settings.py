"""Settings for the separately deployed Odoo MCP service; no AnyAPI keys shared."""
from __future__ import annotations

from dataclasses import dataclass
from os import environ
from typing import Mapping
from urllib.parse import urlparse


@dataclass(frozen=True, repr=False)
class Settings:
    supabase_url: str
    supabase_publishable_key: str
    supabase_secret_key: str
    db_dsn: str
    encryption_key: str
    session_key: str
    public_url: str

    @classmethod
    def from_env(cls, values: Mapping[str, str] | None = None) -> "Settings":
        env = environ if values is None else values
        return cls(
            supabase_url=env.get("SUPABASE_URL", "").strip(),
            supabase_publishable_key=env.get("SUPABASE_PUBLISHABLE_KEY", "").strip(),
            supabase_secret_key=env.get("SUPABASE_SECRET_KEY", "").strip(),
            db_dsn=env.get("ODOO_MCP_DB_DSN", "").strip(),
            encryption_key=env.get("ODOO_MCP_ENCRYPTION_KEY", "").strip(),
            session_key=env.get("ODOO_MCP_SESSION_KEY", "").strip(),
            public_url=env.get("ODOO_MCP_PUBLIC_URL", "").strip(),
        )

    @staticmethod
    def _https(value: str) -> bool:
        try:
            u = urlparse(value)
            return (
                u.scheme == "https" and bool(u.hostname)
                and u.username is None and u.password is None
                and not u.fragment and not u.query
            )
        except ValueError:
            return False

    def readiness(self) -> dict[str, bool]:
        valid_keys = bool(
            self.encryption_key and self.session_key
            and self.encryption_key != self.session_key
            and len(self.encryption_key) >= 24
            and len(self.session_key) >= 24
        )
        return {
            "supabase_url": self._https(self.supabase_url),
            "supabase_publishable_key": bool(self.supabase_publishable_key),
            "supabase_secret_key": bool(self.supabase_secret_key),
            "database": self.db_dsn.startswith(("postgresql://", "postgres://")),
            "encryption": valid_keys,
            "session": valid_keys,
            "public_url": self._https(self.public_url),
        }

    def __repr__(self) -> str:
        return "Settings(<redacted>)"
