"""OAuth code/PKCE and opaque token protocol contract."""
import base64
import hashlib
from uuid import uuid4

import pytest
from authlib.oauth2.rfc7636 import create_s256_code_challenge

from mcp_saas.oauth import AuthorizationService, ClientMetadataResolver
from mcp_saas.oauth_store import OAuthError


OWNER, SERVER = str(uuid4()), str(uuid4())
PUBLIC = "a"*40
RESOURCE = "https://mcp.example.org/mcp/" + PUBLIC
CLIENT = "https://client.example.org/client.json"
REDIRECT = "https://client.example.org/callback"
VERIFIER = "v"*48
CHALLENGE = create_s256_code_challenge(VERIFIER)


class MetadataTransport:
    def get_metadata_json(self, url, timeout_s):
        return {"client_id": CLIENT, "client_name": "Test Client", "redirect_uris": [REDIRECT]}


class FakeStore:
    def __init__(self):
        self.created = []
        self.code = "unique-auth-code"
        self.grant = {
            "owner_id": OWNER, "server_id": SERVER, "client_id": CLIENT,
            "resource": RESOURCE, "scopes": ["odoo:read"], "pkce_challenge": CHALLENGE,
        }
        self.access = "unique-access-token"

    def get_authorized_server(self, public_id, owner_id):
        return {"id": SERVER, "owner_id": OWNER, "enabled": True} if public_id == PUBLIC and owner_id == OWNER else None

    def issue_code(self, owner_id, server_id, client_id, redirect_uri, resource, scopes, pkce_challenge):
        self.created.append((owner_id, server_id, scopes, pkce_challenge))
        return self.code

    def consume_code(self, code, client_id, redirect_uri, resource, verifier):
        if code != self.code or client_id != CLIENT or redirect_uri != REDIRECT or resource != RESOURCE:
            raise OAuthError("invalid_grant")
        if create_s256_code_challenge(verifier) != CHALLENGE:
            raise OAuthError("invalid_grant")
        self.code = None
        return self.grant

    def issue_tokens(self, grant):
        assert grant["server_id"] == SERVER
        return {"access_token": self.access, "refresh_token": "refresh-secret",
                "token_type": "Bearer", "expires_in": 900, "scope": "odoo:read"}

    def authenticate_access_token(self, token, resource):
        if token != self.access or resource != RESOURCE:
            raise OAuthError("invalid_token")
        return self.grant


def service():
    store = FakeStore()
    return AuthorizationService(store, ClientMetadataResolver(MetadataTransport()), "https://mcp.example.org"), store


def authorization_params():
    return {"client_id": CLIENT, "redirect_uri": REDIRECT, "resource": RESOURCE,
            "response_type": "code", "scope": "odoo:read", "state": "csrf-state",
            "code_challenge_method": "S256", "code_challenge": CHALLENGE}


def test_code_pkce_s256_happy_path():
    auth, store = service()
    approval = auth.approve(OWNER, authorization_params())
    assert approval["code"] == "unique-auth-code"
    assert store.created[0][2] == ["odoo:read"]
    token = auth.exchange_code({"grant_type":"authorization_code", "code": approval["code"],
        "client_id": CLIENT, "redirect_uri": REDIRECT, "resource": RESOURCE,
        "code_verifier": VERIFIER})
    assert token["access_token"] == "unique-access-token"
    assert auth.authenticate_access_token(token["access_token"], RESOURCE)["owner_id"] == OWNER


def test_without_consent_rejected():
    auth, store = service()
    with pytest.raises(OAuthError):
        auth.inspect(OWNER, dict(authorization_params(), response_type="token"))
    assert not store.created


def test_wrong_redirect_or_resource_rejected():
    auth, store = service()
    with pytest.raises(OAuthError):
        auth.approve(OWNER, dict(authorization_params(), redirect_uri="https://attacker.example.org/callback"))
    with pytest.raises(OAuthError):
        auth.approve(OWNER, dict(authorization_params(), resource="https://mcp.example.org/mcp/" + "b"*40))
    assert not store.created


def test_pkce_plain_rejected():
    auth, store = service()
    with pytest.raises(OAuthError):
        auth.approve(OWNER, dict(authorization_params(), code_challenge_method="plain"))


def test_replayed_code_rejected():
    auth, store = service()
    code = auth.approve(OWNER, authorization_params())["code"]
    params = {"grant_type":"authorization_code", "code":code,
        "client_id": CLIENT, "redirect_uri": REDIRECT, "resource":RESOURCE,
        "code_verifier":VERIFIER}
    auth.exchange_code(params)
    with pytest.raises(OAuthError):
        auth.exchange_code(params)


def test_write_scope_not_allowed_by_default():
    auth, store = service()
    with pytest.raises(OAuthError):
        auth.approve(OWNER, dict(authorization_params(), scope="odoo:read odoo:write"))


def test_supabase_cookie_cannot_be_reused_as_oauth_bearer():
    auth, store = service()
    with pytest.raises(OAuthError):
        auth.authenticate_access_token("supabase-access-token", RESOURCE)
