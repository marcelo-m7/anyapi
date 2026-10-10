"""Task 6: JSON-RPC lifecycle, tool discovery and error contracts."""
from mcp_saas.mcp_http import dispatch_rpc
from mcp_saas.tools import ToolContext


class FakeOdoo:
    def call(self, conn, key, model, method, args):
        if method == "fields_get":
            return {"id": {"type": "integer", "string": "ID"},
                    "name": {"type": "char", "string": "Name"}}
        return [{"id": 1, "name": "Example"}]


def context():
    return ToolContext(
        owner_id="owner-1", server_id="server-1",
        server={"id": "server-1", "owner_id": "owner-1", "enabled": True},
        scopes={"odoo:read"},
        policies=[{"server_id": "server-1", "model_name": "res.partner", "action": "read",
                   "enabled": True, "allowed_fields": ["id", "name"], "allowed_domain": []}],
        connection={"base_url": "https://odoo.example.org"},
        api_key="test-only", odoo=FakeOdoo(),
    )


def rpc(method, params=None, id=12):
    return {"jsonrpc": "2.0", "method": method, "params": params or {}, "id": id}


def test_initialize_negotiates_2025_11_25():
    result, status = dispatch_rpc(context(), rpc("initialize",
        {"protocolVersion": "2025-11-25", "capabilities": {},
         "clientInfo": {"name": "test", "version": "1.0"}}))
    assert status == 200
    assert result["id"] == 12
    assert result["result"]["protocolVersion"] == "2025-11-25"
    assert result["result"]["capabilities"]["tools"] == {}


def test_tools_list_only_authorized():
    result, status = dispatch_rpc(context(), rpc("tools/list"))
    assert status == 200
    assert [x["name"] for x in result["result"]["tools"]] == [
        "odoo_list_models", "odoo_get_model_schema",
        "odoo_search_records", "odoo_get_record"]


def test_notifications_return_202_empty():
    result, status = dispatch_rpc(context(), {"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert result is None
    assert status == 202


def test_unknown_method_yields_jsonrpc_error():
    result, status = dispatch_rpc(context(), rpc("resources/read"))
    assert status == 200
    assert result["error"]["code"] == -32601


def test_tools_call_returns_structured_content():
    result, status = dispatch_rpc(context(), rpc("tools/call", {
        "name": "odoo_list_models", "arguments": {}}))
    assert status == 200
    assert result["result"]["structuredContent"]["models"] == ["res.partner"]
    assert result["result"]["isError"] is False
