"""Deny-by-default Odoo policy enforcement and output minimization."""
from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import AppError

_MODEL = re.compile(r"^[a-z_][a-z0-9_.]*$")
_FIELD = re.compile(r"^[a-z_][a-z0-9_]*$")
_SENSITIVE = re.compile(r"password|secret|token|api.?key|credential|attachment|binary|image|avatar|private.?key", re.I)
_TECHNICAL = frozenset({
    "res.users", "res.config.settings", "ir.config_parameter",
    "ir.attachment", "ir.model", "ir.model.fields", "ir.model.access",
    "ir.rule", "mail.message", "mail.mail", "base.automation",
})
_ALLOWED_DOMAIN_OPERATORS = frozenset({"=", "!=", "ilike", ">", "<", ">=", "<="})
_ALLOWED_ACTIONS = frozenset({"read", "create", "update"})


@dataclass(frozen=True)
class AuthorizedOperation:
    model: str
    action: str
    fields: list[str]
    domain: list[list]


class PolicyEngine:
    @staticmethod
    def valid_model(model: str) -> bool:
        return (isinstance(model, str) and bool(_MODEL.fullmatch(model))
                and model not in _TECHNICAL
                and not model.startswith(("ir.", "base.", "auth.", "mail.")))

    @staticmethod
    def valid_field(field: str) -> bool:
        return (isinstance(field, str) and bool(_FIELD.fullmatch(field))
                and not _SENSITIVE.search(field)
                and (field == "id" or not field.endswith("_id")))

    @staticmethod
    def authorize(server: dict, policies: list[dict], granted_scopes: set[str],
                  action: str, model: str, fields: list[str]) -> AuthorizedOperation:
        if (not server.get("enabled") or action not in _ALLOWED_ACTIONS
                or not PolicyEngine.valid_model(model)):
            raise AppError("not_authorized", 403, "Model/action not available")
        scope = "odoo:read" if action == "read" else "odoo:write"
        if scope not in granted_scopes:
            raise AppError("not_authorized", 403, "OAuth grant lacks required scope")
        policy = next((item for item in policies
                       if item.get("server_id") == server.get("id")
                       and item.get("model_name") == model
                       and item.get("action") == action
                       and item.get("enabled") is True
                       and item.get("owner_id", server.get("owner_id")) == server.get("owner_id")), None)
        if policy is None:
            raise AppError("not_authorized", 403, "Model/action is not enabled")
        allowed = policy.get("allowed_fields")
        if (not isinstance(allowed, list) or not allowed or
            any(not PolicyEngine.valid_field(f) for f in allowed)):
            raise AppError("not_authorized", 403, "Model field policy is invalid")
        if not isinstance(fields, list) or any(not isinstance(f, str) for f in fields):
            raise AppError("invalid_input", 400, "Requested fields must be a list")
        projection = list(allowed) if not fields else fields
        if not projection or any(not PolicyEngine.valid_field(f) or f not in allowed for f in projection):
            raise AppError("not_authorized", 403, "Requested fields are not permitted")
        domain = PolicyEngine.validate_filter(policy.get("allowed_domain", []), allowed)
        return AuthorizedOperation(model, action, projection, domain)

    @staticmethod
    def validate_filter(domain: list, allowed_fields: list[str]) -> list[list]:
        if not isinstance(domain, list) or len(domain) > 20:
            raise AppError("invalid_input", 400, "Domain must be a short AND-only list")
        result = []
        for term in domain:
            if not isinstance(term, (list, tuple)) or len(term) != 3:
                raise AppError("invalid_input", 400, "Unsupported domain expression")
            field, operator, value = term
            if (field not in allowed_fields or not PolicyEngine.valid_field(field)
                or operator not in _ALLOWED_DOMAIN_OPERATORS
                or isinstance(value, (list, tuple, dict))
                or not (value is None or isinstance(value, (str, int, float, bool)))
                or (isinstance(value, str) and len(value) > 256)):
                raise AppError("invalid_input", 400, "Unsupported domain clause")
            result.append([field, operator, value])
        return result

    @staticmethod
    def sanitize_records(records: object, fields: list[str]) -> list[dict]:
        if not isinstance(records, list) or len(records) > 100:
            raise AppError("upstream_error", 502, "Odoo returned too many records")
        result = []
        for record in records:
            if not isinstance(record, dict):
                raise AppError("upstream_error", 502, "Unexpected Odoo record")
            safe = {}
            for field in fields:
                if not PolicyEngine.valid_field(field) or field not in record:
                    continue
                value = record[field]
                if value is None or type(value) in (str, int, float, bool):
                    safe[field] = value[:4096] if isinstance(value, str) else value
            result.append(safe)
        return result
