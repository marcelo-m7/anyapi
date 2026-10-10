"""Tenant store never looks up records without owner-scoped JWT filters."""
from uuid import uuid4
import pytest
from mcp_saas.store import TenantStore
from mcp_saas.settings import Settings


class Response:
    def raise_for_status(self):
        pass

    def json(self):
        return [{"id": "owned"}]


class FakeHttp:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response()


def test_get_owned_server_includes_both_ids_and_jwt():
    user, server = str(uuid4()), str(uuid4())
    http = FakeHttp()
    store = TenantStore("TEST-user-jwt", Settings.from_env({
        "SUPABASE_URL": "https://sample.supabase.co",
        "SUPABASE_PUBLISHABLE_KEY": "published"
    }), http)
    assert store.get_owned_server(user, server)["id"] == "owned"
    url, kw = http.calls[0]
    assert url.endswith("/rest/v1/odoo_mcp_servers")
    assert kw["params"]["owner_id"] == "eq." + user
    assert kw["params"]["id"] == "eq." + server
    assert kw["headers"]["Authorization"] == "Bearer TEST-user-jwt"
    assert kw["allow_redirects"] is False


def test_get_owned_server_rejects_untrusted_filter_injection():
    store = TenantStore("TEST", Settings.from_env({"SUPABASE_URL": "https://sample.supabase.co"}), FakeHttp())
    with pytest.raises(ValueError):
        store.get_owned_server("any text,or(1=1)", str(uuid4()))
