"""Task 5: enforce model/field/domain restrictions on every operation."""
import pytest
from mcp_saas.policies import PolicyEngine
from mcp_saas.errors import AppError

SERVER = {"id": "server-1", "owner_id": "owner-1", "enabled": True}
POLICIES = [{"server_id": "server-1", "model_name": "res.partner", "action": "read",
             "enabled": True, "allowed_fields": ["id", "name"], "allowed_domain": []}]


def test_allowed_read_exposes_only_named_fields():
    permit = PolicyEngine.authorize(SERVER, POLICIES, {"odoo:read"},
                                    "read", "res.partner", ["name"])
    assert permit.fields == ["name"]


def test_even_allowlisted_system_model_cannot_be_accessed():
    forbidden = [dict(POLICIES[0], model_name="res.users")]
    with pytest.raises(AppError):
        PolicyEngine.authorize(SERVER, forbidden, {"odoo:read"}, "read", "res.users", ["id"])


def test_domain_or_operator_is_rejected():
    with pytest.raises(AppError):
        PolicyEngine.validate_filter(["|", ["name", "=", "a"], ["name", "=", "b"]],
                                     ["id", "name"])


def test_relational_and_sensitive_fields_are_rejected():
    with pytest.raises(AppError):
        PolicyEngine.authorize(
            SERVER, [dict(POLICIES[0], allowed_fields=["id", "company_id"])],
            {"odoo:read"}, "read", "res.partner", ["company_id"])


def test_sanitize_records_drops_unapproved_values_and_nonprimitives():
    rows = PolicyEngine.sanitize_records([
        {"id": 1, "name": "One", "secret": "x", "company_id": [3, "other"]}
    ], ["id", "name", "company_id"])
    assert rows == [{"id": 1, "name": "One"}]
