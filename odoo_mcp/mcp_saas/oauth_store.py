"""One-time OAuth authorization codes and transactional token persistence.

All operations are parameterized, server/owner scoped and use DB transactions.
No generic SQL endpoint is exported to API consumers.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import psycopg
from psycopg.rows import dict_row


class OAuthError(Exception):
    """Generic OAuth grant rejection; never expose presence of other tenants."""


def _uuid(value: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError) as exc:
        raise OAuthError("invalid_grant") from exc


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class OAuthStore:
    def __init__(self, db_dsn: str):
        if not db_dsn.startswith(("postgresql://", "postgres://")):
            raise ValueError("PostgreSQL DSN required")
        self._dsn = db_dsn

    def issue_code(self, owner_id: str, server_id: str, client_id: str,
                   redirect_uri: str, resource: str, scopes: list[str],
                   pkce_challenge: str, ttl_seconds: int = 300) -> str:
        owner_id = _uuid(owner_id)
        server_id = _uuid(server_id)
        if not (client_id and redirect_uri and resource and isinstance(scopes, list)
                and pkce_challenge and len(pkce_challenge) == 43):
            raise OAuthError("invalid_request")
        raw = secrets.token_urlsafe(48)
        with psycopg.connect(self._dsn, connect_timeout=5) as connection:
            with connection.cursor() as cur:
                cur.execute(
                    """insert into odoo_mcp_private.odoo_mcp_oauth_codes
                       (owner_id,server_id,client_id,redirect_uri,resource,scopes,
                        pkce_challenge,code_hash,expires_at)
                       values (%s,%s,%s,%s,%s,%s,%s,%s,now() + (%s * interval '1 second'))""",
                    (owner_id, server_id, client_id, redirect_uri, resource, scopes,
                     pkce_challenge, _digest(raw), ttl_seconds),
                )
        return raw

    def consume_code(self, raw: str, client_id: str, redirect_uri: str, resource: str) -> dict:
        if not (raw and client_id and redirect_uri and resource):
            raise OAuthError("invalid_grant")
        with psycopg.connect(self._dsn, connect_timeout=5) as connection:
            with connection.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """update odoo_mcp_private.odoo_mcp_oauth_codes
                       set consumed_at=now()
                       where code_hash=%s and client_id=%s and redirect_uri=%s
                         and resource=%s and consumed_at is null and expires_at > now()
                       returning owner_id,server_id,client_id,resource,scopes,pkce_challenge""",
                    (_digest(raw), client_id, redirect_uri, resource),
                )
                row = cur.fetchone()
                if not row:
                    raise OAuthError("invalid_grant")
                return dict(row)
