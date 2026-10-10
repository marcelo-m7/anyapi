"""Versioned symmetric encryption for Odoo credentials (never sent to the browser)."""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


class CredentialsService:
    VERSION = "v1"

    def __init__(self, key_material: str):
        if not key_material or len(key_material) < 24:
            raise ValueError("Dedicated encryption key must have at least 24 characters")
        digest = hashlib.sha256(key_material.encode()).digest()
        self._cipher = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt_key(self, plaintext: str) -> str:
        if not plaintext:
            raise ValueError("API key cannot be empty")
        return self.VERSION + ":" + self._cipher.encrypt(plaintext.encode()).decode()

    def decrypt_key(self, ciphertext: str) -> str:
        if not ciphertext.startswith(self.VERSION + ":"):
            raise ValueError("Unknown key version")
        try:
            return self._cipher.decrypt(ciphertext.split(":", 1)[1].encode()).decode()
        except (InvalidToken, ValueError, UnicodeError) as exc:
            raise ValueError("Could not decrypt stored secret") from exc

    def rotate_key(self, ciphertext: str, replacement: "CredentialsService") -> str:
        return replacement.encrypt_key(self.decrypt_key(ciphertext))
