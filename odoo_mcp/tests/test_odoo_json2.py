"""Task 4: Odoo 19 JSON-2 named arguments and API errors."""
import pytest
from mcp_saas.odoo_json2 import OdooJSON2
from mcp_saas.errors import AppError


class SpyTransport:
    def __init__(self, response=None, error=None):
        self.response = response if response is not None else []
        self.error = error
        self.calls = []

    def post_json(self, url, headers, payload, timeout_s):
        self.calls.append((url, headers, payload, timeout_s))
        if self.error:
            raise self.error
        return self.response


def test_json2_search_read_uses_named_args_and_bearer():
    spy = SpyTransport([{"id": 7}])
    api = OdooJSON2(spy)
    result = api.call({"base_url": "https://odoo.example.org", "database": "odoo"},
                      "secret-for-test", "res.partner", "search_read",
                      {"domain": [], "fields": ["id"], "limit": 1})
    assert result == [{"id": 7}]
    url, headers, payload, timeout_s = spy.calls[0]
    assert url == "https://odoo.example.org/json/2/res.partner/search_read"
    assert headers["Authorization"] == "bearer secret-for-test"
    assert headers["X-Odoo-Database"] == "odoo"
    assert payload == {"domain": [], "fields": ["id"], "limit": 1}
    assert 0 < timeout_s <= 15


def test_arbitrary_odoo_method_is_denied_before_network():
    spy = SpyTransport()
    with pytest.raises(AppError) as exc:
        OdooJSON2(spy).call({"base_url": "https://odoo.example.org"}, "key",
                            "res.partner", "unlink", {"ids": [7]})
    assert exc.value.code == "not_authorized"
    assert spy.calls == []


def test_unsupported_plan_error_is_actionable():
    spy = SpyTransport(error=AppError("unsupported_odoo_api", 403,
                                     "Odoo external API is unavailable for this plan"))
    result = OdooJSON2(spy).probe_connection(
        {"base_url": "https://odoo.example.org"}, "key")
    assert result["ok"] is False
    assert result["error"] == "unsupported_odoo_api"
    assert "plan" in result["message"].lower()


def test_probe_on_success_uses_bounded_read():
    spy = SpyTransport([{"id": 1}])
    assert OdooJSON2(spy).probe_connection(
        {"base_url": "https://odoo.example.org"}, "key")["ok"] is True
    assert spy.calls[0][2]["limit"] == 1
