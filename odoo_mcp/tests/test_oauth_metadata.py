"""OAuth discovery contracts, separate from Supabase Auth."""
from mcp_saas.app_factory import create_app
from mcp_saas.settings import Settings


def client():
    config = Settings.from_env({"ODOO_MCP_PUBLIC_URL": "https://mcp.example.org"})
    return create_app(settings=config).test_client()


def test_protected_resource_uses_exact_canonical_mcp_url():
    c = client()
    server = "a" * 40
    response = c.get("/.well-known/oauth-protected-resource/mcp/" + server)
    assert response.status_code == 200
    data = response.get_json()
    assert data["resource"] == "https://mcp.example.org/mcp/" + server
    assert data["authorization_servers"] == ["https://mcp.example.org"]
    assert "odoo:read" in data["scopes_supported"]


def test_authorization_server_metadata_matches_issuer():
    response = client().get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    data = response.get_json()
    assert data["issuer"] == "https://mcp.example.org"
    assert data["authorization_endpoint"] == "https://mcp.example.org/oauth/authorize"
    assert data["token_endpoint"] == "https://mcp.example.org/oauth/token"
    assert data["code_challenge_methods_supported"] == ["S256"]
    assert data["client_id_metadata_document_supported"] is True


def test_public_resource_metadata_does_not_expose_database_config():
    result = client().get("/.well-known/oauth-protected-resource/mcp/" + "b" * 40)
    assert "SUPABASE" not in result.get_data(as_text=True)
    assert "database" not in result.get_data(as_text=True).lower()
