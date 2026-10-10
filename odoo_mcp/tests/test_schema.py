"""Static checks for the forward-only, tenant-isolated Supabase migration."""
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[1] / "supabase/migrations/20261010214921_odoo_mcp_init.sql"


def test_migration_has_all_expected_tables():
    sql = MIGRATION.read_text().lower()
    for table in ("connections", "servers", "policies", "audit_events"):
        assert f"create table public.odoo_mcp_{table}" in sql
    for table in ("connection_secrets", "oauth_clients", "oauth_codes", "oauth_tokens", "rate_limits"):
        assert f"create table odoo_mcp_private.odoo_mcp_{table}" in sql


def test_public_tenant_tables_have_rls_and_owner_constraints():
    sql = MIGRATION.read_text().lower()
    for table in ("connections", "servers", "policies", "audit_events"):
        assert f"alter table public.odoo_mcp_{table} enable row level security" in sql
    assert "with check (owner_id = (select auth.uid()))" in sql
    assert "foreign key (connection_id, owner_id)" in sql
    assert "foreign key (server_id, owner_id)" in sql


def test_private_storage_unavailable_to_browser_roles():
    sql = MIGRATION.read_text().lower()
    assert "revoke all on schema odoo_mcp_private from public, anon, authenticated" in sql
    assert "revoke all on all tables in schema odoo_mcp_private from public, anon, authenticated" in sql
    assert "service_role" not in sql
