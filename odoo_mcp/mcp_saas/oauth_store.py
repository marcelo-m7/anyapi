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

    def issue_tokens(self, owner_id: str, server_id: str, client_id: str,
                     resource: str, scopes: list[str]) -> dict:
        """Create hashed opaque credentials; caller must have validated the grant."""
        owner_id, server_id = _uuid(owner_id), _uuid(server_id)
        if not client_id or not resource or not scopes or not set(scopes) <= {"odoo:read", "odoo:write"}:
            raise OAuthError("invalid_grant")
        access, refresh = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
        with psycopg.connect(self._dsn, connect_timeout=5) as connection:
            with connection.cursor() as cur:
                cur.execute(
                    """insert into odoo_mcp_private.odoo_mcp_oauth_tokens
                       (owner_id,server_id,client_id,access_hash,refresh_hash,scopes,resource,expires_at)
                       select %s,%s,%s,%s,%s,%s,%s,now() + interval '15 minutes'
                       where exists(select 1 from public.odoo_mcp_servers
                                    where id=%s and owner_id=%s and enabled=true)""",
                    (owner_id, server_id, client_id, _digest(access), _digest(refresh),
                     scopes, resource, server_id, owner_id),
                )
                if cur.rowcount != 1:
                    raise OAuthError("invalid_grant")
        return {"access_token": access, "refresh_token": refresh, "token_type": "Bearer",
                "expires_in": 900, "scope": " ".join(scopes)}

    def authenticate_access_token(self, token: str, resource: str) -> dict:
        if not token or not resource:
            raise OAuthError("invalid_token")
        with psycopg.connect(self._dsn, connect_timeout=5) as connection:
            with connection.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """select t.owner_id,t.server_id,t.client_id,t.resource,t.scopes
                       from odoo_mcp_private.odoo_mcp_oauth_tokens t
                       join public.odoo_mcp_servers s
                         on s.id=t.server_id and s.owner_id=t.owner_id
                       where t.access_hash=%s and t.resource=%s and t.revoked_at is null
                         and t.expires_at>now() and s.enabled=true""",
                    (_digest(token),resource),
                )
                record = cur.fetchone()
                if record is None:
                    raise OAuthError("invalid_token")
                return {**dict(record), "owner_id": str(record["owner_id"]),
                        "server_id": str(record["server_id"])}

    def revoke_token(self, raw_token: str) -> bool:
        if not raw_token:
            return False
        with psycopg.connect(self._dsn, connect_timeout=5) as connection:
            with connection.cursor() as cur:
                cur.execute(
                    """update odoo_mcp_private.odoo_mcp_oauth_tokens
                       set revoked_at=now()
                       where (access_hash=%s or refresh_hash=%s) and revoked_at is null""",
                    (_digest(raw_token), _digest(raw_token)),
                )
                return cur.rowcount > 0

    def rotate_refresh(self, raw_token: str, client_id: str, resource: str) -> dict:
        """Atomic refresh, old credentials are invalidated by the first winner."""
        if not raw_token or not client_id or not resource:
            raise OAuthError("invalid_grant")
        access, refresh = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
        with psycopg.connect(self._dsn, connect_timeout=5) as connection:
            with connection.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """update odoo_mcp_private.odoo_mcp_oauth_tokens
                       set revoked_at=now(), rotated_at=now()
                       where refresh_hash=%s and client_id=%s and resource=%s
                         and revoked_at is null
                         and exists(select 1 from public.odoo_mcp_servers
                           where id=server_id and owner_id=odoo_mcp_oauth_tokens.owner_id
                             and enabled=true)
                       returning owner_id,server_id,scopes""",
                    (_digest(raw_token), client_id, resource),
                )
                prior = cur.fetchone()
                if prior is None:
                    raise OAuthError("invalid_grant")
                cur.execute(
                    """insert into odoo_mcp_private.odoo_mcp_oauth_tokens
                       (owner_id,server_id,client_id,access_hash,refresh_hash,scopes,resource,expires_at)
                       values (%s,%s,%s,%s,%s,%s,%s,now() + interval '15 minutes')""",
                    (prior["owner_id"],prior["server_id"],client_id,
                     _digest(access),_digest(refresh),prior["scopes"],resource),
                )
                return {"access_token": access, "refresh_token": refresh, "token_type": "Bearer",
                        "expires_in": 900, "scope": " ".join(prior["scopes"])}
