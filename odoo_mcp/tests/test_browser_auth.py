"""Task 3: Supabase browser sessions are separate from MCP bearer credentials."""
import re
import pytest
from mcp_saas.app_factory import create_app
from mcp_saas.settings import Settings


USER_ID = "00000000-0000-4000-8000-000000000001"


class FakeProvider:
    def sign_in(self, email, password):
        assert password == "correct_password"
        return {"access_token": "supabase-only-access", "refresh_token": "refresh-1",
                "expires_in": 3600, "user": {"id": USER_ID, "email": email}}

    def get_user(self, access_token):
        if access_token != "supabase-only-access":
            raise ValueError("invalid auth token")
        return {"id": USER_ID, "email": "demo@example.org"}

    def refresh(self, refresh_token):
        if refresh_token != "refresh-1":
            raise ValueError("bad refresh")
        return self.sign_in("demo@example.org", "correct_password")


def app():
    settings = Settings.from_env({
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
        "SUPABASE_SECRET_KEY": "sb_secret_test",
        "ODOO_MCP_DB_DSN": "postgresql://db.example.net/mcp",
        "ODOO_MCP_ENCRYPTION_KEY": "connection-key-material-0123456789",
        "ODOO_MCP_SESSION_KEY": "different-cookie-key-material-0123456789",
        "ODOO_MCP_PUBLIC_URL": "https://mcp.example.com"
    })
    return create_app(settings=settings, dependencies={"supabase_auth": FakeProvider()})


def login(client):
    html = client.get("/login").get_data(as_text=True)
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    return client.post("/login", data={
        "email": "demo@example.org", "password": "correct_password", "csrf_token": csrf})


def test_missing_cookie_redirects_to_login():
    client = app().test_client()
    response = client.get("/dashboard")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_browser_auth_cannot_use_mcp_bearer_as_login():
    client = app().test_client()
    response = client.get("/dashboard", headers={"Authorization": "Bearer fake-mcp-token"})
    assert response.status_code == 302


def test_login_is_csrf_protected_and_session_is_encrypted():
    client = app().test_client()
    assert client.post("/login", data={"email": "demo@example.org", "password": "correct_password"}).status_code == 400
    response = login(client)
    assert response.status_code == 302
    cookie = response.headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie and "Secure" in cookie
    assert "supabase-only-access" not in cookie
    assert "refresh-1" not in cookie
    profile = client.get("/auth/whoami")
    assert profile.status_code == 200
    assert profile.get_json() == {"id": USER_ID, "email": "demo@example.org"}


def test_forged_cookie_is_not_accepted():
    client = app().test_client()
    client.set_cookie("session", "forged-signature")
    assert client.get("/dashboard").status_code == 302


def test_logout_revokes_browser_cookie():
    client = app().test_client()
    login(client)
    csrf = re.search(r'name="csrf_token" value="([^"]+)"',
                     client.get("/dashboard").get_data(as_text=True)).group(1)
    response = client.post("/logout", data={"csrf_token": csrf})
    assert response.status_code == 302
    assert client.get("/dashboard").status_code == 302
