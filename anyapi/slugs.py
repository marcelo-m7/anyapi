"""Slug and username rules. Mirrors `anyapi_is_valid_slug` / `anyapi_reserved_names` in Postgres."""

from __future__ import annotations

import re

SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")

RESERVED_NAMES = frozenset(
    {
        "about", "admin", "anyapi", "api", "app", "assets", "auth", "billing", "blog", "dashboard",
        "docs", "favicon.ico", "forgot-password", "health", "help", "login", "logout", "new", "openapi",
        "pricing", "reset-password", "robots.txt", "settings", "signup", "static", "status", "support",
        "system", "v1", "www", "_api", "_next",
    }
)


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    value = re.sub(r"-{2,}", "-", value)
    return value[:40].strip("-")


def normalize_username(value: str) -> str:
    return (value or "").strip().lower()


def slug_error(value: str, label: str = "Slug") -> str | None:
    if not value:
        return f"{label} is required."
    if not SLUG_PATTERN.match(value) or "--" in value:
        return f"{label} may only contain lowercase letters, numbers and single hyphens (max 40)."
    return None


def username_error(value: str) -> str | None:
    error = slug_error(value, "Username")
    if error:
        return error
    if len(value) < 3:
        return "Username must be at least 3 characters."
    if value in RESERVED_NAMES:
        return "That username is reserved."
    return None
