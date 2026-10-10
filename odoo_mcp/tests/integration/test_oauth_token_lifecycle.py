"""OAuth token lifecycle: audience binding, expiry, revocation and refresh replay."""
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

psycopg = pytest.importorskip("psycopg")
from mcp_saas.oauth_store import OAuthStore, OAuthError

DSN = os.environ.get("ODOO_MCP_TEST_DB_DSN")
if not DSN:
    pytest.skip("Disposable PostgreSQL is required", allow_module_level=True)

MIGRATION = Path(__file__).resolve().parents[2] / "supabase/migrations/20261010214921_odoo_mcp_init.sql"


@pytest.fixture(scope="module")
def tenant():
    with psycopg.connect(DSN, autocommit=True) as db:
        db.execute("create schema if not exists auth")
        db.execute("create table if not exists auth.users (id uuid primary key)")
        db.execute("""create or replace function auth.uid() returns uuid language sql stable
            as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$""")
        for role in ("anon", "authenticated"):
            db.execute(f"""do $$ begin if not exists(select 1 from pg_roles where rolname='{role}')
                then create role {role} nologin; end if; end $$""")
        if db.execute("select to_regclass('public.odoo_mcp_servers')").fetchone()[0] is None:
            db.execute(MIGRATION.read_text())
        owner, conn, server = str(uuid4()), str(uuid4()), str(uuid4())
        db.execute("insert into auth.users(id) values (%s)", (owner,))
        db.execute("""insert into public.odoo_mcp_connections(id,owner_id,label,base_url,database)
            values (%s,%s,'Test','https://odoo.example.org','db')""", (conn,owner))
        db.execute("""insert into public.odoo_mcp_servers
            (id,owner_id,connection_id,public_id,label,enabled)
            values (%s,%s,%s,%s,'Test',true)""", (server,owner,conn,server.replace("-","")))
        return OAuthStore(DSN), owner, server, "https://mcp.example.org/mcp/" + server.replace("-","")


def test_access_token_audience_and_scope_are_enforced(tenant):
    store, owner, server, resource = tenant
    bundle = store.issue_tokens(owner, server, "client-a", resource, ["odoo:read"])
    assert bundle["token_type"] == "Bearer"
    assert bundle["expires_in"] <= 900
    grant = store.authenticate_access_token(bundle["access_token"], resource)
    assert grant["owner_id"] == owner
    assert grant["server_id"] == server
    assert grant["scopes"] == ["odoo:read"]
    with pytest.raises(OAuthError):
        store.authenticate_access_token(bundle["access_token"], resource + "-different")


def test_revocation_applies_on_next_request(tenant):
    store, owner, server, resource = tenant
    bundle = store.issue_tokens(owner, server, "client-a", resource, ["odoo:read"])
    assert store.revoke_token(bundle["access_token"]) is True
    with pytest.raises(OAuthError):
        store.authenticate_access_token(bundle["access_token"], resource)


def test_refresh_rotation_single_winner_under_concurrency(tenant):
    store, owner, server, resource = tenant
    bundle = store.issue_tokens(owner, server, "client-a", resource, ["odoo:read"])
    def refresh(_):
        try:
            return store.rotate_refresh(bundle["refresh_token"], "client-a", resource)
        except OAuthError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(refresh, range(2)))
    successful = [x for x in results if x is not None]
    assert len(successful) == 1
    with pytest.raises(OAuthError):
        store.rotate_refresh(bundle["refresh_token"], "client-a", resource)


def test_token_for_disabled_server_is_denied(tenant):
    store, owner, server, resource = tenant
    bundle = store.issue_tokens(owner, server, "client-a", resource, ["odoo:read"])
    with psycopg.connect(DSN) as db:
        db.execute("update public.odoo_mcp_servers set enabled=false where id=%s", (server,))
    with pytest.raises(OAuthError):
        store.authenticate_access_token(bundle["access_token"], resource)
    with psycopg.connect(DSN) as db:
        db.execute("update public.odoo_mcp_servers set enabled=true where id=%s", (server,))
