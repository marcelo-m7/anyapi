"""PostgreSQL atomic one-time code consumption, no concurrency replay or cross-server grants."""
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

psycopg = pytest.importorskip("psycopg")
from mcp_saas.oauth_store import OAuthStore, OAuthError
from authlib.oauth2.rfc7636 import create_s256_code_challenge
VERIFIER = 'v'*48
CHALLENGE = create_s256_code_challenge(VERIFIER)

DSN = os.environ.get("ODOO_MCP_TEST_DB_DSN")
if not DSN:
    pytest.skip("Requires disposable PostgreSQL service", allow_module_level=True)

MIGRATION = Path(__file__).resolve().parents[2] / "supabase/migrations/20261010214921_odoo_mcp_init.sql"


@pytest.fixture(scope="module")
def db():
    with psycopg.connect(DSN, autocommit=True) as cx:
        cx.execute("create schema if not exists auth")
        cx.execute("create table if not exists auth.users (id uuid primary key)")
        cx.execute("""create or replace function auth.uid() returns uuid language sql stable
                      as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$""")
        for role in ("anon", "authenticated"):
            cx.execute(f"""do $$ begin if not exists(select 1 from pg_roles where rolname='{role}')
                           then create role {role} nologin; end if; end $$""")
        if cx.execute("select to_regclass('public.odoo_mcp_servers')").fetchone()[0] is None:
            cx.execute(MIGRATION.read_text())
        owner = str(uuid4())
        foreign = str(uuid4())
        server = str(uuid4())
        other_server = str(uuid4())
        conn = str(uuid4())
        cx.execute("insert into auth.users(id) values (%s),(%s)", (owner,foreign))
        cx.execute("""insert into public.odoo_mcp_connections
                      (id,owner_id,label,base_url,database)
                      values (%s,%s,'Example','https://odoo.example.org','db')""", (conn, owner))
        cx.execute("""insert into public.odoo_mcp_servers (id,owner_id,connection_id,public_id,label)
                      values (%s,%s,%s,%s,'A'),(%s,%s,%s,%s,'B')""",
                   (server, owner, conn, "a"*40, other_server, owner, conn, "b"*40))
        yield OAuthStore(DSN), owner, foreign, server, other_server


def test_duplicate_code_consumption_1_of_2_only(db):
    store, owner, foreign, server, other = db
    secret = store.issue_code(owner,server,"https://client.example.org/client.json",
        "https://client.example.org/callback","https://mcp.example.org/mcp/"+"a"*40,
        ["odoo:read"],CHALLENGE)
    def consume():
        try:
            return store.consume_code(secret, "https://client.example.org/client.json",
                   "https://client.example.org/callback","https://mcp.example.org/mcp/"+"a"*40,VERIFIER)
        except OAuthError:
            return None
    with ThreadPoolExecutor(max_workers=2) as ex:
        results = list(ex.map(lambda _i: consume(), range(2)))
    assert len([x for x in results if x]) == 1


def test_cross_server_grant_cannot_resolve(db):
    store, owner, foreign, server, other = db
    token = store.issue_code(owner,server,"https://client.example.org/client.json",
        "https://client.example.org/callback","https://mcp.example.org/mcp/"+"a"*40,
        ["odoo:read"],CHALLENGE)
    with pytest.raises(OAuthError):
        store.consume_code(token, "https://client.example.org/client.json",
           "https://client.example.org/callback","https://mcp.example.org/mcp/"+"b"*40,VERIFIER)


def test_expired_code_rejected(db):
    store, owner, foreign, server, other = db
    token = store.issue_code(owner, server, "https://client.example.org/client.json",
           "https://client.example.org/callback", "https://mcp.example.org/mcp/"+"a"*40,
           ["odoo:read"],CHALLENGE, ttl_seconds=-1)
    with pytest.raises(OAuthError):
        store.consume_code(token,"https://client.example.org/client.json",
            "https://client.example.org/callback","https://mcp.example.org/mcp/"+"a"*40,VERIFIER)
