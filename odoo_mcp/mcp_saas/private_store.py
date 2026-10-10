"""Private, owner-scoped SQL access; never exposed as a browser SQL executor."""
from __future__ import annotations

from uuid import UUID


class PrivateStore:
    def __init__(self, db_dsn: str):
        if not db_dsn.startswith(("postgresql://", "postgres://")):
            raise ValueError("A PostgreSQL connection URL is required")
        self.db_dsn = db_dsn

    def get_connection_secret(self, owner_id: str, connection_id: str) -> tuple[str, int] | None:
        import psycopg
        with psycopg.connect(self.db_dsn, connect_timeout=5) as db:
            with db.cursor() as cur:
                cur.execute(
                    """select secret_ciphertext, key_version
                       from odoo_mcp_private.odoo_mcp_connection_secrets
                       where owner_id = %s and connection_id = %s""",
                    (str(UUID(owner_id)), str(UUID(connection_id))),
                )
                return cur.fetchone()

    def put_connection_secret(self, owner_id: str, connection_id: str, ciphertext: str, key_version: int) -> None:
        if not ciphertext or not 1 <= key_version <= 32767:
            raise ValueError("Invalid ciphertext/key version")
        import psycopg
        with psycopg.connect(self.db_dsn, connect_timeout=5) as db:
            with db.cursor() as cur:
                cur.execute(
                    """insert into odoo_mcp_private.odoo_mcp_connection_secrets
                         (owner_id, connection_id, secret_ciphertext, key_version)
                       values (%s, %s, %s, %s)
                       on conflict (connection_id) do update
                         set secret_ciphertext = excluded.secret_ciphertext,
                             key_version = excluded.key_version,
                             updated_at = now()
                       where odoo_mcp_connection_secrets.owner_id = excluded.owner_id""",
                    (str(UUID(owner_id)), str(UUID(connection_id)), ciphertext, key_version),
                )
                if cur.rowcount != 1:
                    raise LookupError("Connection not owned by this tenant")
