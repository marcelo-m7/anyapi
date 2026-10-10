"""Task 9 — authenticated grant resolves only its own Odoo tenant data."""
import os
from pathlib import Path
from uuid import uuid4
import pytest

psycopg=pytest.importorskip("psycopg")
from mcp_saas.context_resolver import ContextResolver
from mcp_saas.credentials import CredentialsService
from mcp_saas.errors import AppError

DSN=os.environ.get("ODOO_MCP_TEST_DB_DSN")
if not DSN:
    pytest.skip("Requires disposable PostgreSQL", allow_module_level=True)
MIGRATION=Path(__file__).resolve().parents[2]/"supabase/migrations/20261010214921_odoo_mcp_init.sql"
KEY="context-fixture-encryption-master-key-123456789"

@pytest.fixture(scope="module")
def records():
    a,b=str(uuid4()),str(uuid4())
    c1,c2=str(uuid4()),str(uuid4())
    s1,s2=str(uuid4()),str(uuid4())
    with psycopg.connect(DSN,autocommit=True) as db:
        db.execute("create schema if not exists auth")
        db.execute("create table if not exists auth.users(id uuid primary key)")
        db.execute("""create or replace function auth.uid() returns uuid language sql stable
            as $$select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid$$""")
        for role in ("anon","authenticated"):
            db.execute(f"""do $$ begin if not exists(select 1 from pg_roles where rolname='{role}')
            then create role {role} nologin; end if; end $$""")
        if db.execute("select to_regclass('public.odoo_mcp_servers')").fetchone()[0] is None:
            db.execute(MIGRATION.read_text())
        db.execute("insert into auth.users(id) values (%s),(%s)",(a,b))
        for owner,conn,server,marker in ((a,c1,s1,"c"),(b,c2,s2,"d")):
            db.execute("""insert into public.odoo_mcp_connections
                (id,owner_id,label,base_url,database,status)
                values (%s,%s,'Test','https://odoo.example.org','db','healthy')""",(conn,owner))
            db.execute("""insert into public.odoo_mcp_servers
                (id,owner_id,connection_id,public_id,label,enabled)
                values (%s,%s,%s,%s,'Test',true)""",(server,owner,conn,marker*40))
            db.execute("""insert into public.odoo_mcp_policies
                (owner_id,server_id,model_name,action,allowed_fields,enabled)
                values (%s,%s,'res.partner','read','["id","name"]'::jsonb,true)""",(owner,server))
            db.execute("""insert into odoo_mcp_private.odoo_mcp_connection_secrets
                (owner_id,connection_id,secret_ciphertext,key_version)
                values (%s,%s,%s,1)""",(owner,conn,CredentialsService(KEY).encrypt_key(marker+"-secret")))
    return a,b,s1,s2


def test_owner_a_reads_only_its_connection_and_secret(records):
    a,b,s1,s2=records
    result=ContextResolver(DSN,KEY).resolve({
        "owner_id":a,"server_id":s1,"scopes":["odoo:read"]},"c"*40)
    assert result.owner_id==a
    assert result.server_id==s1
    assert result.api_key=="c-secret"
    assert [p["model_name"] for p in result.policies]==["res.partner"]


def test_owner_b_cannot_resolve_a_server_even_with_id(records):
    a,b,s1,s2=records
    with pytest.raises(AppError):
        ContextResolver(DSN,KEY).resolve({
            "owner_id":b,"server_id":s1,"scopes":["odoo:read"]},"c"*40)


def test_grant_for_server_a_cannot_reach_server_b_public_id(records):
    a,b,s1,s2=records
    with pytest.raises(AppError):
        ContextResolver(DSN,KEY).resolve({
            "owner_id":a,"server_id":s1,"scopes":["odoo:read"]},"d"*40)


def test_denies_missing_oauth_read_scope(records):
    a,b,s1,s2=records
    with pytest.raises(AppError):
        ContextResolver(DSN,KEY).resolve({
            "owner_id":a,"server_id":s1,"scopes":[]},"c"*40)


def test_policy_disable_is_effective_next_resolution(records):
    a,b,s1,s2=records
    with psycopg.connect(DSN) as db:
        db.execute("update public.odoo_mcp_policies set enabled=false where server_id=%s",(s1,))
    try:
        resolved=ContextResolver(DSN,KEY).resolve({
            "owner_id":a,"server_id":s1,"scopes":["odoo:read"]},"c"*40)
        assert resolved.policies==[]
    finally:
        with psycopg.connect(DSN) as db:
            db.execute("update public.odoo_mcp_policies set enabled=true where server_id=%s",(s1,))


def test_production_factory_binds_real_opaque_oauth_grants(records):
    """A real PostgreSQL-issued bearer must reach tools/list without a test-only auth bypass."""
    from mcp_saas.app_factory import create_app
    from mcp_saas.settings import Settings
    from mcp_saas.oauth_store import OAuthStore

    owner, other_owner, server, other_server = records
    resource = "https://mcp.example.org/mcp/" + "c"*40
    token = OAuthStore(DSN).issue_tokens(
        owner, server, "https://client.example.org/client.json", resource, ["odoo:read"]
    )["access_token"]
    settings = Settings.from_env({
        "SUPABASE_URL": "https://sample.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
        "SUPABASE_SECRET_KEY": "sb_secret_test",
        "ODOO_MCP_DB_DSN": DSN,
        "ODOO_MCP_ENCRYPTION_KEY": KEY,
        "ODOO_MCP_SESSION_KEY": "different-cookie-master-key-0123456789",
        "ODOO_MCP_PUBLIC_URL": "https://mcp.example.org",
    })
    client = create_app(settings=settings).test_client()
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-11-25",
    }
    rpc = {"jsonrpc": "2.0", "method": "tools/list", "id": 23}
    response = client.post("/mcp/" + "c"*40, json=rpc, headers=headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body["id"] == 23
    assert "odoo_list_models" in [t["name"] for t in body["result"]["tools"]]
    assert client.post("/mcp/"+"d"*40,json=rpc,headers=headers).status_code == 401
