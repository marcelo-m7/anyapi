"""Real Postgres: refresh rotation, access audience, revoked and expired tokens."""
import os
from pathlib import Path
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

import pytest
psycopg = pytest.importorskip("psycopg")

from mcp_saas.oauth_store import OAuthStore, OAuthError

DSN = os.environ.get("ODOO_MCP_TEST_DB_DSN")
if not DSN:
    pytest.skip("Requires disposable PostgreSQL", allow_module_level=True)

MIGRATION = Path(__file__).resolve().parents[2] / "supabase/migrations/20261010214921_odoo_mcp_init.sql"
RESOURCE = "https://mcp.example.org/mcp/" + "f"*40


@pytest.fixture(scope="module")
def seeded():
    with psycopg.connect(DSN, autocommit=True) as cx:
        cx.execute("create schema if not exists auth")
        cx.execute("create table if not exists auth.users (id uuid primary key)")
        for role in ("anon", "authenticated"):
            cx.execute(f"""do $$ begin if not exists(select 1 from pg_roles where rolname='{role}')
                           then create role {role} nologin; end if; end $$""")
        cx.execute("""create or replace function auth.uid() returns uuid language sql stable as
                      $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$""")
        if cx.execute("select to_regclass('public.odoo_mcp_servers')").fetchone()[0] is None:
            cx.execute(MIGRATION.read_text())
        owner,server,conn = str(uuid4()),str(uuid4()),str(uuid4())
        cx.execute("insert into auth.users(id) values (%s)", (owner,))
        cx.execute("""insert into public.odoo_mcp_connections
          (id,owner_id,label,base_url,database) values (%s,%s,'A','https://odoo.example.org','db')""",
          (conn, owner))
        cx.execute("""insert into public.odoo_mcp_servers
          (id,owner_id,connection_id,public_id,label,enabled)
          values (%s,%s,%s,%s,'A',true)""",(server,owner,conn,"f"*40))
    return OAuthStore(DSN), {"owner_id":owner,"server_id":server,
        "client_id":"https://client.example.org/client.json",
        "resource":RESOURCE, "scopes":["odoo:read"]}


def test_access_audience_bound_and_revoked_immediately(seeded):
    store,grant=seeded
    tokens=store.issue_tokens(grant)
    assert store.authenticate_access_token(tokens["access_token"], RESOURCE)["server_id"]==grant["server_id"]
    with pytest.raises(OAuthError):
        store.authenticate_access_token(tokens["access_token"],"https://mcp.example.org/mcp/"+"e"*40)
    store.revoke_token(tokens["access_token"],grant["client_id"])
    with pytest.raises(OAuthError):
        store.authenticate_access_token(tokens["access_token"], RESOURCE)


def test_concurrent_refresh_only_one_succeeds(seeded):
    store,grant=seeded
    tokens=store.issue_tokens(grant)
    def rotate():
        try:
            return store.rotate_refresh(tokens["refresh_token"],grant["client_id"],RESOURCE)
        except OAuthError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:rotate(),range(2)))
    assert sum(x is not None for x in results)==1


def test_refresh_rotation_invalidates_old_token_family_on_replay(seeded):
    store,grant=seeded
    issued=store.issue_tokens(grant)
    fresh=store.rotate_refresh(issued["refresh_token"],grant["client_id"],RESOURCE)
    with pytest.raises(OAuthError):
        store.rotate_refresh(issued["refresh_token"],grant["client_id"],RESOURCE)
    with pytest.raises(OAuthError):
        store.authenticate_access_token(fresh["access_token"],RESOURCE)


def test_refresh_expiry_refused(seeded):
    store,grant=seeded
    issued=store.issue_tokens(grant)
    with psycopg.connect(DSN) as conn:
        conn.execute("""update odoo_mcp_private.odoo_mcp_oauth_tokens
                        set refresh_expires_at=now()-interval '1 second'
                        where refresh_hash=%s""", (store.hash_token(issued["refresh_token"]),))
    with pytest.raises(OAuthError):
        store.rotate_refresh(issued["refresh_token"],grant["client_id"],RESOURCE)
