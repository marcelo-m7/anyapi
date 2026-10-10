"""Restricted Odoo 19 JSON-2 external API adapter."""
from __future__ import annotations

import re
from urllib.parse import quote

from .errors import AppError
from .network import PinnedHttpsTransport, assert_safe_odoo_url

_MODEL = re.compile(r"^[a-z_][a-z0-9_.]*$")
_ALLOWED_METHODS = frozenset({"search_read", "read", "fields_get", "create", "write"})


class OdooJSON2:
    def __init__(self, transport: PinnedHttpsTransport | None = None):
        self.transport = transport or PinnedHttpsTransport()

    def call(self, connection: dict, api_key: str, model: str,
             method: str, args: dict) -> object:
        if not _MODEL.fullmatch(model) or method not in _ALLOWED_METHODS:
            raise AppError("not_authorized", 403, "Odoo operation is not allowed")
        if not api_key:
            raise AppError("authentication_failed", 401, "Odoo API key is required")
        if not isinstance(args, dict):
            raise AppError("invalid_input", 400, "Odoo arguments must be an object")
        origin = assert_safe_odoo_url(connection.get("base_url", ""))
        endpoint = origin + "/json/2/" + quote(model, safe=".") + "/" + method
        headers = {"Authorization": "bearer " + api_key}
        if connection.get("database"):
            headers["X-Odoo-Database"] = str(connection["database"])
        return self.transport.post_json(endpoint, headers, args, timeout_s=15)

    def probe_connection(self, connection: dict, api_key: str) -> dict:
        try:
            result = self.call(
                connection, api_key, "res.partner", "search_read",
                {"domain": [], "fields": ["id"], "limit": 1},
            )
            if not isinstance(result, list):
                raise AppError("upstream_error", 502, "Odoo API returned an unexpected format")
            return {"ok": True, "api": "json-2", "model": "res.partner"}
        except AppError as exc:
            return {"ok": False, "error": exc.code, "message": exc.message}
