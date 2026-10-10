"""Task 5: read-only model/record tools with bounded projection."""
import pytest
from mcp_saas.tools import ToolContext, ToolRegistry
from mcp_saas.errors import AppError


class FakeOdoo:
    def __init__(self):
        self.calls = []

    def call(self, connection, api_key, model, method, args):
        self.calls.append((model, method, args))
        if method == "fields_get":
            return {"id": {"type": "integer", "string": "ID"},
                    "name": {"type": "char", "string": "Name"},
                    "secret": {"type": "binary", "string": "Secret"},
                    "company_id": {"type": "many2one", "relation": "res.company"}}
        if method == "search_read":
            return [{"id": 1, "name": "Example", "secret": "DO_NOT_LEAK"}]
        if method == "read":
            return [{"id": 1, "name": "Example", "secret": "DO_NOT_LEAK"}]
        raise AssertionError("unexpected method: " + method)


def ctx(scopes=None, policies=None):
    odoo = FakeOdoo()
    return ToolContext(
        owner_id="user-1", server_id="server-1",
        server={"id": "server-1", "owner_id": "user-1", "enabled": True},
        scopes=set(["odoo:read"]) if scopes is None else scopes,
        policies=policies if policies is not None else [{
            "server_id": "server-1", "model_name": "res.partner", "action": "read",
            "enabled": True, "allowed_fields": ["id", "name"], "allowed_domain": []}],
        connection={"base_url": "https://odoo.example.org", "database": "odoo"},
        api_key="not-an-actual-key", odoo=odoo,
    )


def test_default_server_has_no_write_tools():
    context = ctx()
    names = [t["name"] for t in ToolRegistry.list_tools(context)]
    assert names == ["odoo_list_models", "odoo_get_model_schema",
                     "odoo_search_records", "odoo_get_record"]


def test_models_discovery_returns_only_allowlisted_models():
    context = ctx()
    assert ToolRegistry.invoke(context, "odoo_list_models", {}) == {"models": ["res.partner"]}
    assert context.odoo.calls == []


def test_search_defaults_to_20_and_strips_extra_upstream_fields():
    context = ctx()
    result = ToolRegistry.invoke(
        context, "odoo_search_records", {"model": "res.partner", "fields": ["id", "name"]})
    assert result == {"records": [{"id": 1, "name": "Example"}]}
    call = [x for x in context.odoo.calls if x[1] == "search_read"][0]
    assert call[2]["limit"] == 20
    assert call[2]["fields"] == ["id", "name"]


def test_query_max_100_and_default_20():
    context = ctx()
    with pytest.raises(AppError):
        ToolRegistry.invoke(context, "odoo_search_records",
                            {"model": "res.partner", "limit": 101})
    assert context.odoo.calls == []


def test_untrusted_domain_or_context_rejected_before_upstream():
    context = ctx()
    with pytest.raises(AppError):
        ToolRegistry.invoke(context, "odoo_search_records",
                            {"model": "res.partner", "context": {"sudo": True}})
    with pytest.raises(AppError):
        ToolRegistry.invoke(context, "odoo_search_records",
                            {"model": "res.partner", "domain": [["secret", "=", "x"]]})
    assert context.odoo.calls == []


def test_disabled_server_and_missing_read_scope_hide_tools():
    context = ctx(scopes=set())
    assert ToolRegistry.list_tools(context) == []
    with pytest.raises(AppError):
        ToolRegistry.invoke(context, "odoo_list_models", {})


def test_schema_redacts_sensitive_and_relation_metadata():
    context = ctx()
    result = ToolRegistry.invoke(context, "odoo_get_model_schema", {"model": "res.partner"})
    assert set(result["fields"]) == {"id", "name"}
