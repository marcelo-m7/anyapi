"""Supabase Auth browser sessions, isolated from OAuth MCP bearer credentials."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from functools import wraps

import requests
from cryptography.fernet import Fernet, InvalidToken
from flask import Blueprint, abort, current_app, jsonify, redirect, render_template_string, request, session


bp = Blueprint("odoo_mcp_browser_auth", __name__)
COOKIE_KEY = "odoo_mcp_encrypted_session"


@dataclass(frozen=True)
class BrowserIdentity:
    id: str
    email: str
    access_token: str


class SupabaseAuthProvider:
    def __init__(self, url: str, publishable_key: str, http: requests.Session | None = None):
        if not url.startswith("https://"):
            raise ValueError("Supabase Auth requires HTTPS")
        self.url = url.rstrip("/")
        self.publishable_key = publishable_key
        self.http = http or requests.Session()

    def _request(self, method: str, path: str, *, token: str = "", payload: dict | None = None,
                 params: dict | None = None) -> dict:
        headers = {"apikey": self.publishable_key, "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + token
        response = self.http.request(
            method, self.url + "/auth/v1/" + path, headers=headers,
            json=payload, params=params, timeout=10, allow_redirects=False,
        )
        response.raise_for_status()
        data = response.json() if response.content else {}
        if not isinstance(data, dict):
            raise ValueError("Unexpected identity provider response")
        return data

    def sign_in(self, email: str, password: str) -> dict:
        return self._request("POST", "token", params={"grant_type": "password"},
                             payload={"email": email, "password": password})

    def refresh(self, refresh_token: str) -> dict:
        return self._request("POST", "token", params={"grant_type": "refresh_token"},
                             payload={"refresh_token": refresh_token})

    def get_user(self, access_token: str) -> dict:
        return self._request("GET", "user", token=access_token)

    def sign_out(self, access_token: str) -> None:
        self._request("POST", "logout", token=access_token)


def _settings():
    return current_app.extensions["odoo_mcp.settings"]


def _provider():
    return current_app.extensions["odoo_mcp.auth_provider"]


def _session_cipher() -> Fernet:
    key = _settings().session_key
    if not key or len(key) < 24:
        raise ValueError("Session signing/encryption key is not configured")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))


def _csrf_token() -> str:
    value = session.get("odoo_mcp_csrf")
    if not value:
        value = secrets.token_urlsafe(32)
        session["odoo_mcp_csrf"] = value
    return value


def _verify_csrf() -> None:
    expected = session.get("odoo_mcp_csrf", "")
    supplied = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
    if not expected or not hmac.compare_digest(expected, supplied):
        abort(400, "Missing or invalid CSRF token")


def _encrypted_payload(payload: dict) -> str:
    return _session_cipher().encrypt(json.dumps(payload).encode()).decode()


def _decoded_payload(value: str) -> dict | None:
    try:
        obj = json.loads(_session_cipher().decrypt(value.encode()))
        return obj if isinstance(obj, dict) else None
    except (ValueError, TypeError, InvalidToken, UnicodeError):
        return None


def _store_auth(data: dict) -> None:
    user = data.get("user") or {}
    if not data.get("access_token") or not data.get("refresh_token") or not user.get("id"):
        raise ValueError("Identity provider omitted required token data")
    payload = {
        "id": str(user["id"]),
        "email": str(user.get("email") or ""),
        "access_token": str(data["access_token"]),
        "refresh_token": str(data["refresh_token"]),
        "expires_at": int(time.time()) + int(data.get("expires_in", 3600)),
    }
    session.clear()
    session[COOKIE_KEY] = _encrypted_payload(payload)
    _csrf_token()


def current_identity() -> BrowserIdentity | None:
    encrypted = session.get(COOKIE_KEY)
    if not encrypted:
        return None
    data = _decoded_payload(encrypted)
    if not data:
        session.pop(COOKIE_KEY, None)
        return None
    try:
        if data.get("expires_at", 0) < time.time() + 30:
            refreshed = _provider().refresh(data["refresh_token"])
            _store_auth(refreshed)
            data = _decoded_payload(session[COOKIE_KEY])
            if not data:
                raise ValueError("Invalid refreshed session")
        remote_user = _provider().get_user(data["access_token"])
        if str(remote_user.get("id")) != str(data.get("id")):
            raise ValueError("Session subject mismatch")
        return BrowserIdentity(
            id=str(remote_user["id"]),
            email=str(remote_user.get("email") or data.get("email") or ""),
            access_token=str(data["access_token"]),
        )
    except (requests.RequestException, KeyError, ValueError, TypeError):
        session.pop(COOKIE_KEY, None)
        return None


def require_current_user(_request=None) -> BrowserIdentity:
    identity = current_identity()
    if not identity:
        abort(401, "Sign in required")
    return identity


def browser_login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_identity():
            return redirect("/login")
        return view(*args, **kwargs)
    return wrapper


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if current_identity():
            return redirect("/dashboard")
        try:
            csrf = _csrf_token()
        except RuntimeError:
            return "Service is not configured", 503
        return render_template_string("""
<!doctype html><html lang="en"><meta charset="utf-8"><title>Odoo MCP - Sign in</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<form method="post"><h1>Odoo MCP</h1>
<label>Email <input type="email" name="email" required></label>
<label>Password <input type="password" name="password" required></label>
<input type="hidden" name="csrf_token" value="{{ csrf_token }}">
<button type="submit">Sign in</button></form></html>""", csrf_token=csrf)
    _verify_csrf()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    if not email or "@" not in email or not password:
        return "Invalid credentials", 400
    try:
        data = _provider().sign_in(email, password)
        _store_auth(data)
        return redirect("/dashboard")
    except (requests.RequestException, ValueError, TypeError):
        return "Invalid credentials", 401


@bp.get("/dashboard")
@browser_login_required
def dashboard():
    identity = require_current_user()
    return render_template_string(
        '<!doctype html><html><meta charset="utf-8"><h1>Odoo MCP SaaS</h1>'
        '<p>Signed in as {{ email }}</p>'
        '<form action="/logout" method="post">'
        '<input type="hidden" name="csrf_token" value="{{ csrf_token }}">'
        '<button type="submit">Sign out</button></form></html>',
        email=identity.email, csrf_token=_csrf_token(),
    )


@bp.get("/auth/whoami")
def whoami():
    user = current_identity()
    if not user:
        return jsonify(error="unauthorized"), 401
    return jsonify(id=user.id, email=user.email)


@bp.post("/logout")
def logout():
    _verify_csrf()
    data = _decoded_payload(session.get(COOKIE_KEY, "")) if session.get(COOKIE_KEY) else None
    if data and data.get("access_token") and hasattr(_provider(), "sign_out"):
        try:
            _provider().sign_out(data["access_token"])
        except (requests.RequestException, ValueError):
            pass
    session.clear()
    return redirect("/login")
