"""Task 6: authenticated, stateless HTTP transport in isolated Flask app."""
from mcp_saas.app_factory import create_app
from mcp_saas.errors import AppError
from mcp_saas.settings import Settings
from tests.test_mcp_http import context, rpc

PUBLIC_ID = "a" * 40


class FakeAuthorization:
    def authenticate_access_token(self, token, resource):
        if token != "test-only-opaque" or not resource.endswith("/mcp/" + PUBLIC_ID):
            raise AppError("not_authorized", 401, "Not authorized")
        return {"sub": "owner-1", "server_id": "server-1"}


def client():
    settings = Settings.from_env({
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY": "anon",
        "SUPABASE_SECRET_KEY": "service",
        "ODOO_MCP_DB_DSN": "postgresql://example.org/db",
        "ODOO_MCP_ENCRYPTION_KEY": "encryption_key_material_separate",
        "ODOO_MCP_SESSION_KEY": "session_key_material_separate",
        "ODOO_MCP_PUBLIC_URL": "https://mcp.example.com",
    })
    app = create_app(settings=settings, dependencies={
        "authorizer": FakeAuthorization(),
        "context_factory": lambda grant, public_id: context(),
    })
    return app.test_client()


def headers(token="test-only-opaque"):
    return {
        "Authorization": "Bearer " + token,
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-11-25",
    }


def post(message, extra=None):
    return client().post("/mcp/" + PUBLIC_ID, json=message,
                         headers={**headers(), **(extra or {})})


def test_get_stream_returns_405():
    assert client().get("/mcp/" + PUBLIC_ID).status_code == 405


def test_invalid_origin_403():
    assert post(rpc("ping"), {"Origin": "https://attacker.example.org"}).status_code == 403


def test_invalid_version_400():
    assert post(rpc("ping"), {"MCP-Protocol-Version": "not-a-version"}).status_code == 400


def test_wrong_accept_rejected():
    assert post(rpc("ping"), {"Accept": "text/html"}).status_code == 406


def test_unknown_bearer_gets_oauth_metadata_challenge():
    result = post(rpc("ping"), {"Authorization": "Bearer wrong"})
    assert result.status_code == 401
    assert ".well-known/oauth-protected-resource/mcp/" in result.headers["WWW-Authenticate"]


def test_valid_initialize_has_no_session_header():
    result = post(rpc("initialize", {"protocolVersion": "2025-11-25"}))
    assert result.status_code == 200
    assert "Mcp-Session-Id" not in result.headers
    assert result.get_json()["result"]["serverInfo"]["name"] == "odoo-mcp-saas"


def test_notification_returns_202_no_content():
    result = post({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert result.status_code == 202
    assert result.data == b""


def test_production_without_authorizer_fails_closed():
    s = Settings.from_env({"ODOO_MCP_PUBLIC_URL": "https://mcp.example.com"})
    app = create_app(settings=s)
    result = app.test_client().post(
        "/mcp/" + PUBLIC_ID, json=rpc("ping"), headers=headers())
    assert result.status_code == 401
