"""OAuth HTTP boundaries: explicit consent, PKCE exchange, redirect and CSRF."""
import re
from urllib.parse import urlencode
from uuid import uuid4

from mcp_saas.app_factory import create_app
from mcp_saas.settings import Settings

OWNER = str(uuid4())
SERVER = str(uuid4())
PUBLIC = "a" * 40
RESOURCE = "https://mcp.example.org/mcp/" + PUBLIC
CLIENT = "https://client.example.org/client.json"
REDIRECT = "https://client.example.org/callback"
VERIFIER = "v" * 48

class AuthProvider:
    def sign_in(self, email, password):
        return {"user": {"id": OWNER, "email": email},
                "access_token": "fake-supabase-token",
                "refresh_token": "fake-supabase-refresh",
                "expires_in": 3600}
    def get_user(self, access_token):
        return {"id": OWNER, "email": "owner@example.org"}

class Store:
    def __init__(self):
        self.approvals = []
        self.code = "opaque-code"
    def get_authorized_server(self, public_id, owner_id):
        return {"id": SERVER, "owner_id": OWNER, "enabled": True} if public_id == PUBLIC and owner_id == OWNER else None
    def issue_code(self, owner_id, server_id, client_id, redirect_uri, resource, scopes, challenge):
        self.approvals.append((owner_id, server_id, scopes, challenge))
        return self.code
    def consume_code(self, code, client_id, redirect_uri, resource, verifier):
        from authlib.oauth2.rfc7636 import create_s256_code_challenge
        if not self.approvals or code != self.code or verifier != VERIFIER:
            from mcp_saas.oauth_store import OAuthError
            raise OAuthError("invalid_grant")
        self.code = None
        return {"owner_id": OWNER, "server_id": SERVER, "client_id": CLIENT,
                "resource": RESOURCE, "scopes": ["odoo:read"]}
    def issue_tokens_from_grant(self, grant):
        return {"access_token": "mcp-access-opaque", "refresh_token": "mcp-refresh-opaque",
                "token_type": "Bearer", "expires_in": 900, "scope": "odoo:read"}
    def revoke_token(self, token, client_id=None):
        return token == "mcp-access-opaque"

class Metadata:
    def get_metadata_json(self, url, timeout_s):
        return {"client_id": CLIENT, "client_name": "Test Client",
                "redirect_uris": [REDIRECT]}


def app():
    settings = Settings.from_env({
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY": "anon",
        "SUPABASE_SECRET_KEY": "secret",
        "ODOO_MCP_DB_DSN": "postgresql://example.org/test",
        "ODOO_MCP_ENCRYPTION_KEY": "encryption_key_material_separate",
        "ODOO_MCP_SESSION_KEY": "session_key_material_separate",
        "ODOO_MCP_PUBLIC_URL": "https://mcp.example.org",
    })
    store = Store()
    return create_app(settings=settings, dependencies={
        "supabase_auth": AuthProvider(),
        "oauth_store": store,
        "oauth_client_transport": Metadata(),
    }), store


def auth_params():
    from authlib.oauth2.rfc7636 import create_s256_code_challenge
    return {
        "client_id": CLIENT, "redirect_uri": REDIRECT, "resource": RESOURCE,
        "response_type": "code", "scope": "odoo:read", "state": "client-state",
        "code_challenge_method": "S256",
        "code_challenge": create_s256_code_challenge(VERIFIER),
    }


def login(client):
    html = client.get("/login").get_data(as_text=True)
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    assert client.post("/login", data={
        "email": "owner@example.org", "password": "pass",
        "csrf_token": csrf,
    }).status_code == 302


def test_oauth_consent_requires_login_and_cannot_auto_approve():
    application, store = app()
    client = application.test_client()
    response = client.get("/oauth/authorize?" + urlencode(auth_params()))
    assert response.status_code in (302, 401)
    assert not store.approvals


def test_oauth_get_shows_approval_and_post_requires_csrf():
    application, store = app()
    client = application.test_client()
    login(client)
    response = client.get("/oauth/authorize?" + urlencode(auth_params()))
    assert response.status_code == 200
    assert "Test Client" in response.get_data(as_text=True)
    assert "odoo:read" in response.get_data(as_text=True)
    assert not store.approvals
    assert client.post("/oauth/authorize", data=dict(auth_params(), decision="approve")).status_code == 400
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True)).group(1)
    approved = client.post("/oauth/authorize", data=dict(auth_params(), decision="approve", csrf_token=csrf))
    assert approved.status_code == 302
    assert approved.headers["Location"].startswith(REDIRECT + "?")
    assert "code=opaque-code" in approved.headers["Location"]
    assert "state=client-state" in approved.headers["Location"]


def test_code_exchange_checks_pkce_and_never_exposes_supabase_token():
    application, store = app()
    client = application.test_client()
    login(client)
    consent = client.get("/oauth/authorize?" + urlencode(auth_params()))
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', consent.get_data(as_text=True)).group(1)
    client.post("/oauth/authorize", data=dict(auth_params(), decision="approve", csrf_token=csrf))
    reply = client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": "opaque-code",
        "client_id": CLIENT, "redirect_uri": REDIRECT,
        "resource": RESOURCE, "code_verifier": VERIFIER,
    })
    assert reply.status_code == 200
    assert reply.get_json()["access_token"] == "mcp-access-opaque"
    assert "fake-supabase-token" not in reply.get_data(as_text=True)
    assert client.post("/oauth/token", data={
        "grant_type": "authorization_code", "code": "opaque-code",
        "client_id": CLIENT, "redirect_uri": REDIRECT,
        "resource": RESOURCE, "code_verifier": VERIFIER,
    }).status_code == 400


def test_oauth_write_request_is_denied_by_default():
    application, store = app()
    client = application.test_client()
    login(client)
    params = dict(auth_params(), scope="odoo:read odoo:write")
    response = client.get("/oauth/authorize?" + urlencode(params))
    assert response.status_code == 400
    assert not store.approvals
