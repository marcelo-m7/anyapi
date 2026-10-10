"""Stable, safely reportable errors for the Odoo MCP transport."""
from __future__ import annotations


class AppError(Exception):
    def __init__(self, code: str, status: int, message: str):
        super().__init__(message)
        self.code = code
        self.status = status
        self.message = message

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message}
