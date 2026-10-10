"""Minimal Supabase REST client (GoTrue + PostgREST) built on `requests`.

Two access modes:
- `user(token)`: requests carry the end user's JWT, so Postgres RLS applies.
- `service()`: requests use the service role key and bypass RLS. Only used by the
  gateway and by server code that has already verified ownership.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from .config import Settings

_TIMEOUT = 10
_session = requests.Session()


class SupabaseError(Exception):
    def __init__(self, status: int, message: str, code: str | None = None, details: Any = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code
        self.details = details


def _raise_for(resp: requests.Response) -> None:
    if resp.ok:
        return
    try:
        body = resp.json()
    except ValueError:
        body = {"message": resp.text[:300]}
    message = (
        body.get("message")
        or body.get("msg")
        or body.get("error_description")
        or body.get("error")
        or "Supabase request failed"
    )
    code = body.get("code") or body.get("error_code")
    raise SupabaseError(resp.status_code, str(message), str(code) if code else None, body)


@dataclass
class RestClient:
    base_url: str
    api_key: str
    bearer: str | None

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"apikey": self.api_key, "Content-Type": "application/json"}
        if self.bearer:
            headers["Authorization"] = f"Bearer {self.bearer}"
        if extra:
            headers.update(extra)
        return headers

    def select(self, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        resp = _session.get(
            f"{self.base_url}/rest/v1/{table}", params=params, headers=self._headers(), timeout=_TIMEOUT
        )
        _raise_for(resp)
        return resp.json()

    def select_one(self, table: str, params: dict[str, str]) -> dict[str, Any] | None:
        rows = self.select(table, {**params, "limit": "1"})
        return rows[0] if rows else None

    def count(self, table: str, params: dict[str, str]) -> int:
        resp = _session.head(
            f"{self.base_url}/rest/v1/{table}",
            params={**params, "select": "id"},
            headers=self._headers({"Prefer": "count=exact"}),
            timeout=_TIMEOUT,
        )
        _raise_for(resp)
        content_range = resp.headers.get("Content-Range", "*/0")
        total = content_range.split("/")[-1]
        return int(total) if total.isdigit() else 0

    def insert(self, table: str, row: dict[str, Any] | list[dict[str, Any]], select: str = "*") -> Any:
        resp = _session.post(
            f"{self.base_url}/rest/v1/{table}",
            params={"select": select},
            json=row,
            headers=self._headers({"Prefer": "return=representation"}),
            timeout=_TIMEOUT,
        )
        _raise_for(resp)
        data = resp.json()
        return data[0] if isinstance(row, dict) and data else data

    def update(self, table: str, filters: dict[str, str], values: dict[str, Any], select: str = "*") -> list[dict]:
        resp = _session.patch(
            f"{self.base_url}/rest/v1/{table}",
            params={**filters, "select": select},
            json=values,
            headers=self._headers({"Prefer": "return=representation"}),
            timeout=_TIMEOUT,
        )
        _raise_for(resp)
        return resp.json()

    def delete(self, table: str, filters: dict[str, str]) -> list[dict]:
        resp = _session.delete(
            f"{self.base_url}/rest/v1/{table}",
            params={**filters, "select": "*"} if table not in ("connectors", "api_keys") else {**filters, "select": "id"},
            headers=self._headers({"Prefer": "return=representation"}),
            timeout=_TIMEOUT,
        )
        _raise_for(resp)
        return resp.json()

    def rpc(self, fn: str, args: dict[str, Any]) -> Any:
        resp = _session.post(
            f"{self.base_url}/rest/v1/rpc/{fn}", json=args, headers=self._headers(), timeout=_TIMEOUT
        )
        _raise_for(resp)
        if not resp.content:
            return None
        return resp.json()


class Supabase:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.url = settings.supabase_url

    def user(self, access_token: str) -> RestClient:
        return RestClient(self.url, self.settings.supabase_anon_key, access_token)

    def service(self) -> RestClient:
        key = self.settings.supabase_service_key
        # New-style `sb_secret_` keys are not JWTs and must only be sent as `apikey`.
        bearer = None if key.startswith("sb_secret_") else key
        return RestClient(self.url, key, bearer)

    def anon(self) -> RestClient:
        key = self.settings.supabase_anon_key
        bearer = None if key.startswith("sb_publishable_") else key
        return RestClient(self.url, key, bearer)

    def _auth(self, method: str, path: str, *, token: str | None = None, **kwargs: Any) -> dict[str, Any]:
        headers = {"apikey": self.settings.supabase_anon_key, "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        resp = _session.request(method, f"{self.url}/auth/v1/{path}", headers=headers, timeout=_TIMEOUT, **kwargs)
        _raise_for(resp)
        return resp.json() if resp.content else {}

    def sign_up(self, email: str, password: str, metadata: dict[str, Any], redirect_to: str, code_challenge: str) -> dict:
        return self._auth(
            "POST",
            "signup",
            params={"redirect_to": redirect_to},
            json={
                "email": email,
                "password": password,
                "data": metadata,
                "code_challenge": code_challenge,
                "code_challenge_method": "s256",
            },
        )

    def sign_in_password(self, email: str, password: str) -> dict:
        return self._auth("POST", "token", params={"grant_type": "password"}, json={"email": email, "password": password})

    def refresh(self, refresh_token: str) -> dict:
        return self._auth("POST", "token", params={"grant_type": "refresh_token"}, json={"refresh_token": refresh_token})

    def exchange_code(self, auth_code: str, code_verifier: str) -> dict:
        return self._auth(
            "POST", "token", params={"grant_type": "pkce"}, json={"auth_code": auth_code, "code_verifier": code_verifier}
        )

    def get_user(self, access_token: str) -> dict:
        return self._auth("GET", "user", token=access_token)

    def recover(self, email: str, redirect_to: str, code_challenge: str) -> dict:
        return self._auth(
            "POST",
            "recover",
            params={"redirect_to": redirect_to},
            json={"email": email, "code_challenge": code_challenge, "code_challenge_method": "s256"},
        )

    def update_password(self, access_token: str, password: str) -> dict:
        return self._auth("PUT", "user", token=access_token, json={"password": password})

    def sign_out(self, access_token: str) -> None:
        try:
            self._auth("POST", "logout", token=access_token)
        except SupabaseError:
            pass
