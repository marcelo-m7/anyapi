"""Resolve an OAuth grant into an explicitly owner-scoped MCP tool context.

No caller-selected connection/model/owner is trusted: all selectors derive
from the already validated access token and opaque server path.
"""
from __future__ import annotations

from uuid import UUID
import psycopg
from psycopg.rows import dict_row

from .credentials import CredentialsService
from .errors import AppError
from .odoo_json2 import OdooJSON2
from .tools import ToolContext


def _uuid(value) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise AppError("not_authorized",401,"Unauthorized resource") from exc


class ContextResolver:
    def __init__(self, db_dsn: str, encryption_key: str):
        if not db_dsn.startswith(("postgres://","postgresql://")):
            raise ValueError("PostgreSQL connection is not configured")
        self.db_dsn=db_dsn
        self.credentials=CredentialsService(encryption_key)

    def resolve(self, grant: dict, public_id: str) -> ToolContext:
        try:
            owner=_uuid(grant["owner_id"])
            server_id=_uuid(grant["server_id"])
            scopes=set(grant["scopes"])
            if not scopes or not scopes <= {"odoo:read","odoo:write"}:
                raise ValueError("Invalid grant scopes")
        except (ValueError, TypeError, KeyError) as exc:
            raise AppError("not_authorized",401,"Unauthorized resource") from exc
        if not public_id or len(public_id)>64:
            raise AppError("not_authorized",401,"Unauthorized resource")
        with psycopg.connect(self.db_dsn, connect_timeout=5) as db:
            with db.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """select s.id,s.owner_id,s.connection_id,s.enabled,
                              c.base_url,c.database,c.status,c.id as connection_record_id,
                              k.secret_ciphertext,k.key_version
                       from public.odoo_mcp_servers s
                       join public.odoo_mcp_connections c
                         on c.id=s.connection_id and c.owner_id=s.owner_id
                       join odoo_mcp_private.odoo_mcp_connection_secrets k
                         on k.connection_id=c.id and k.owner_id=c.owner_id
                       where s.id=%s and s.owner_id=%s and s.public_id=%s
                         and s.enabled=true and c.status='healthy'""",
                    (server_id,owner,public_id),
                )
                record=cur.fetchone()
                if record is None:
                    raise AppError("not_authorized",401,"Unauthorized resource")
                cur.execute(
                    """select model_name,action,allowed_fields,allowed_domain,enabled
                       from public.odoo_mcp_policies
                       where owner_id=%s and server_id=%s and enabled=true""",
                    (owner,server_id),
                )
                policies=[{**dict(item),"owner_id":owner,"server_id":server_id}
                          for item in cur.fetchall()]
        if record["key_version"] != 1:
            raise AppError("not_authorized",401,"Unsupported credentials version")
        try:
            api_key=self.credentials.decrypt_key(record["secret_ciphertext"])
        except ValueError as exc:
            raise AppError("not_authorized",401,"Credentials are unavailable") from exc
        return ToolContext(
            owner_id=owner,server_id=server_id,
            server={"id":server_id,"owner_id":owner,"enabled":True},
            scopes=scopes,policies=policies,
            connection={"id":str(record["connection_record_id"]),
                        "base_url":record["base_url"],"database":record["database"]},
            api_key=api_key,odoo=OdooJSON2(),
        )
