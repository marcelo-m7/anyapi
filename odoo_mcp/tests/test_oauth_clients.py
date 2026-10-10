"""Client ID metadata documents must be HTTPS, exact and SSRF-safe."""
import pytest
from mcp_saas.oauth import ClientMetadataResolver
from mcp_saas.errors import AppError


class FakeFetch:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def get_metadata_json(self, url, timeout_s):
        self.calls.append(url)
        return self.data


def test_client_metadata_redirect_uri_must_match():
    url = "https://client.example.org/oauth/client.json"
    metadata = {"client_id": url, "client_name": "Example Client",
                "redirect_uris": ["https://client.example.org/callback"],
                "token_endpoint_auth_method": "none"}
    resolver = ClientMetadataResolver(FakeFetch(metadata))
    assert resolver.validate_client(url, "https://client.example.org/callback")["client_id"] == url
    with pytest.raises(AppError):
        resolver.validate_client(url, "https://evil.example.org/callback")


def test_client_metadata_document_id_must_equal_location_exactly():
    url = "https://client.example.org/client.json"
    metadata = {"client_id": "https://other.example.org/client.json",
                "client_name": "Other", "redirect_uris": ["https://client.example.org/callback"]}
    with pytest.raises(AppError):
        ClientMetadataResolver(FakeFetch(metadata)).validate_client(url, "https://client.example.org/callback")


def test_client_metadata_ssrf_denied_before_fetch():
    fetch = FakeFetch({})
    resolver = ClientMetadataResolver(fetch)
    for url in ("http://client.example.org/client.json",
                "https://127.0.0.1/client.json",
                "https://client.example.org:8000/client.json",
                "https://client.example.org",
                "https://localhost/client.json"):
        with pytest.raises(AppError):
            resolver.validate_client(url, "https://example.org/callback")
    assert fetch.calls == []


def test_client_requires_nonempty_name_and_redirect_uris():
    url = "https://client.example.org/client.json"
    bad = {"client_id": url, "client_name": "", "redirect_uris": []}
    with pytest.raises(AppError):
        ClientMetadataResolver(FakeFetch(bad)).validate_client(url, url)


def test_redirect_match_is_exact_even_with_fragment_or_query():
    url = "https://client.example.org/client.json"
    redirect = "https://client.example.org/callback"
    meta = {"client_id": url, "client_name": "Client", "redirect_uris": [redirect]}
    with pytest.raises(AppError):
        ClientMetadataResolver(FakeFetch(meta)).validate_client(url, redirect + "?next=evil")
