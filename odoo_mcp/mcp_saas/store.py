"""RLS-preserving Supabase PostgREST reads scoped to owner and resource IDs."""
from __future__ import annotations

from uuid import UUID
import requests

from .settings import Settings


def _uuid(value: str) -> str:
    return str(UUID(str(value)))


class TenantStore:
    def __init__(self, user_jwt: str, settings: Settings | None = None, http: requests.Session | None = None):
        if not user_jwt:
            raise ValueError("End-user JWT required")
        self.jwt = user_jwt
        self.settings = settings if settings is not None else Settings.from_env()
        self.http = http or requests.Session()

    def _read_one(self, table: str, owner_id: str, key: str, identity: str) -> dict | None:
        if not self.settings.supabase_url.startswith("https://"):
            raise ValueError("A HTTPS Supabase URL is required")
        query = {"select": "*", "owner_id": "eq." + _uuid(owner_id),
                 key: "eq." + _uuid(identity), "limit": "1"}
        response = self.http.get(
            self.settings.supabase_url.rstrip("/") + "/rest/v1/" + table,
            params=query,
            headers={"apikey": self.settings.supabase_publishable_key,
                     "Authorization": "Bearer " + self.jwt},
            timeout=10,
            allow_redirects=False,
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            raise ValueError("Invalid Supabase response")
        return rows[0] if rows else None

    def get_owned_connection(self, owner_id: str, connection_id: str) -> dict | None:
        return self._read_one("odoo_mcp_connections", owner_id, "id", connection_id)

    def get_owned_server(self, owner_id: str, server_id: str) -> dict | None:
        return self._read_one("odoo_mcp_servers", owner_id, "id", server_id)
