"""Task 1: independent WSGI application and fail-closed readiness checks."""
from mcp_saas.app_factory import create_app
from mcp_saas.settings import Settings


def empty_settings():
    return Settings.from_env({})


def test_health_with_missing_credentials_has_no_secrets():
    client = create_app(settings=empty_settings()).test_client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "service": "odoo-mcp-saas"}
    response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.get_json()
    assert body == {"ready": False, "checks": {
        "supabase_url": False, "supabase_publishable_key": False,
        "supabase_secret_key": False, "database": False,
        "encryption": False, "session": False, "public_url": False,
    }}
    assert "private" not in str(body).lower()


def test_anyapi_entrypoint_not_mounted():
    client = create_app(settings=empty_settings()).test_client()
    assert client.get("/_api/projects").status_code == 404
    assert client.get("/studio/endpoints/123").status_code == 404


def test_partial_config_never_reports_ready():
    settings = Settings.from_env({"SUPABASE_URL": "https://example.supabase.co"})
    response = create_app(settings=settings).test_client().get("/health/ready")
    assert response.status_code == 503
    assert response.get_json()["checks"]["supabase_url"] is True
    assert response.get_json()["ready"] is False


def test_complete_config_reports_readiness_without_leaking_values():
    settings = Settings.from_env({
        "SUPABASE_URL": "https://sample.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_example",
        "SUPABASE_SECRET_KEY": "sb_secret_example",
        "ODOO_MCP_DB_DSN": "postgresql://private:secret@db.example.net/app",
        "ODOO_MCP_ENCRYPTION_KEY": "encryption_key_material_separate",
        "ODOO_MCP_SESSION_KEY": "session_key_material_separate",
        "ODOO_MCP_PUBLIC_URL": "https://odoo-mcp.example.com",
    })
    response = create_app(settings=settings).test_client().get("/health/ready")
    assert response.status_code == 200
    assert response.get_json()["ready"] is True
    assert "postgresql://" not in response.get_data(as_text=True)
    assert "sb_secret_example" not in response.get_data(as_text=True)


def test_session_key_reuse_fails_readiness():
    settings = Settings.from_env({
        "SUPABASE_URL": "https://sample.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY": "publishable",
        "SUPABASE_SECRET_KEY": "secret",
        "ODOO_MCP_DB_DSN": "postgresql://db.example.net/app",
        "ODOO_MCP_ENCRYPTION_KEY": "same_secret",
        "ODOO_MCP_SESSION_KEY": "same_secret",
        "ODOO_MCP_PUBLIC_URL": "https://odoo-mcp.example.com",
    })
    assert create_app(settings=settings).test_client().get("/health/ready").status_code == 503
