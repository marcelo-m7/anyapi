"""Cryptographic helpers: connector secret encryption, API keys, PKCE and redaction."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

API_KEY_PREFIX = "aapi"
_SENSITIVE_KEY = re.compile(
    r"(pass(word)?|secret|token|api[-_]?key|authorization|cookie|session|credential|private[-_]?key|bearer)",
    re.IGNORECASE,
)
REDACTED = "[redacted]"


class SecretBox:
    """Symmetric encryption for connector credentials (Fernet: AES-128-CBC + HMAC)."""

    def __init__(self, key_material: str):
        if not key_material:
            self._fernet = None
            return
        digest = hashlib.sha256(key_material.encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    @property
    def available(self) -> bool:
        return self._fernet is not None

    def encrypt(self, plaintext: str) -> str:
        if not self._fernet:
            raise RuntimeError("Encryption key is not configured")
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        if not self._fernet:
            raise RuntimeError("Encryption key is not configured")
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise RuntimeError("Stored secret could not be decrypted") from exc


def secret_hint(value: str) -> str:
    if len(value) <= 6:
        return "•" * len(value)
    return f"{value[:2]}…{value[-4:]}"


def generate_api_key() -> tuple[str, str, str]:
    """Return (full_key, display_prefix, sha256_hash). Only the hash is stored."""
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    full = f"{API_KEY_PREFIX}_{prefix}_{secret}"
    return full, f"{API_KEY_PREFIX}_{prefix}", hash_api_key(full)


def hash_api_key(full_key: str) -> str:
    return hashlib.sha256(full_key.encode()).hexdigest()


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def redact(value: Any, depth: int = 0) -> Any:
    """Recursively replace values whose keys look sensitive. Used before persisting logs."""
    if depth > 12:
        return "[truncated]"
    if isinstance(value, dict):
        return {
            k: (REDACTED if isinstance(k, str) and _SENSITIVE_KEY.search(k) else redact(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v, depth + 1) for v in value[:200]]
    if isinstance(value, str) and len(value) > 4000:
        return value[:4000] + "…[truncated]"
    return value


def redact_secrets_in_text(text: str, secrets_to_hide: list[str]) -> str:
    for secret in secrets_to_hide:
        if secret and len(secret) >= 4:
            text = text.replace(secret, REDACTED)
    return text
