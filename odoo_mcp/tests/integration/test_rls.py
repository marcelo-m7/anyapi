"""Real PostgreSQL RLS isolation; runs in GitHub Actions PostgreSQL service."""
import os
from pathlib import Path
from uuid import uuid4
import pytest

psycopg = pytest.importorskip("psycopg")
DSN = os.environ.get("ODOO_MCP_TEST_DB_DSN")
if not DSN:
    pytest.skip("Requires disposable ODOO_MCP_TEST_DB_DSN", allow_module_level=True)

MIGRATION = Path(__file__).resolve().parents[2] / "supabase/migrations/20261010214921_odoo_mcp_init.sql"


@pytest.fixture(scope="module")
def database():
    owner_a, owner_b = str(uuid4()), str(uuid4())
    with psycopg.connect(DSN, autocommit=True) as admin:
        admin.execute("create schema if not exists auth")
        admin.execute("create table if not exists auth.users (id uuid primary key)")
        admin.execute("""create or replace function auth.uid() returns uuid
            language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$""")
        for role in ("anon", "authenticated"):
            admin.execute(f"""do $$ begin
                if not exists (select 1 from pg_roles where rolname = '{role}')
                then create role {role} nologin; end if; end $$""")
        admin.execute("grant usage on schema auth to authenticated")
        admin.execute("grant execute on function auth.uid() to authenticated")
        admin.execute("insert into auth.users(id) values (%s), (%s)", (owner_a, owner_b))
        # OAuth integration tests may apply this same migration first.\n        if admin.execute("select to_regclass('public.odoo_mcp_connections')").fetchone()[0] is None:\n            admin.execute(MIGRATION.read_text())
        yield owner_a, owner_b


def scoped_sql(sql: str, tenant: str, parameters=()):
    with psycopg.connect(DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute("set local role authenticated")
            cursor.execute("select set_config('request.jwt.claim.sub', %s, true)", (tenant,))
            cursor.execute(sql, parameters)
            if cursor.description:
                return cursor.fetchall()
            return cursor.rowcount


def test_user_cannot_select_or_update_other_tenant(database):
    owner_a, owner_b = database
    record = str(uuid4())
    assert scoped_sql("""insert into public.odoo_mcp_connections
        (id, owner_id, label, base_url, database)
        values (%s, %s, 'A', 'https://odoo.example.com', 'odoo')""",
        owner_a, (record, owner_a)) == 1
    assert scoped_sql("select id from public.odoo_mcp_connections where id = %s",
                      owner_b, (record,)) == []
    assert scoped_sql("update public.odoo_mcp_connections set label = 'hacked' where id = %s",
                      owner_b, (record,)) == 0


def test_public_tenant_tables_cannot_reassign_owner(database):
    owner_a, owner_b = database
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        scoped_sql("""insert into public.odoo_mcp_connections
             (owner_id, label, base_url, database)
             values (%s, 'stolen', 'https://odoo.example.com', 'db')""",
             owner_a, (owner_b,))


def test_unrelated_server_connection_foreign_key_denied(database):
    owner_a, owner_b = database
    connection_id = str(uuid4())
    scoped_sql("""insert into public.odoo_mcp_connections(id, owner_id, label, base_url, database)
       values (%s, %s, 'B', 'https://odoo.example.com', 'odoo')""",
       owner_b, (connection_id, owner_b))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        scoped_sql("""insert into public.odoo_mcp_servers
        (owner_id, connection_id, public_id, label)
        values (%s, %s, %s, 'malicious')""",
        owner_a, (owner_a, connection_id, "x"*40))


def test_authenticated_cannot_access_private_oauth_tokens(database):
    owner_a, _ = database
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        scoped_sql("select * from odoo_mcp_private.odoo_mcp_oauth_tokens", owner_a)
