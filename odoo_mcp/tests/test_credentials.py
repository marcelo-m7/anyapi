"""Task 3: credentials remain encrypted and versioned."""
from mcp_saas.credentials import CredentialsService
import pytest


def test_ciphertext_roundtrip_is_versioned_and_not_plaintext():
    service = CredentialsService("test-key-material-must-be-strong-123456")
    encoded = service.encrypt_key("odoo-password-api-abc")
    assert encoded.startswith("v1:")
    assert "odoo-password-api-abc" not in encoded
    assert service.decrypt_key(encoded) == "odoo-password-api-abc"


def test_wrong_decryption_key_fails_closed():
    one = CredentialsService("one-secret-material-for-tests-123456")
    other = CredentialsService("other-secret-material-for-tests-987654")
    with pytest.raises(ValueError):
        other.decrypt_key(one.encrypt_key("secret"))


def test_blank_or_unknown_key_version_fails():
    with pytest.raises(ValueError):
        CredentialsService("short")
    box = CredentialsService("one-secret-material-for-tests-123456")
    with pytest.raises(ValueError):
        box.decrypt_key("v2:anything")
