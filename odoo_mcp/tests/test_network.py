"""Task 4: SSRF boundaries and pinned TLS peer tests."""
import socket
import pytest
from mcp_saas.network import assert_safe_odoo_url, PinnedHttpsTransport, NetworkError


@pytest.mark.parametrize("url", [
    "http://odoo.example.org", "https://localhost",
    "https://127.0.0.1", "https://10.1.1.2",
    "https://[::1]", "https://user:pass@odoo.example.org",
    "https://odoo.example.org:8443", "https://odoo.example.org/#x",
    "https://odoo.example.org/path",
])
def test_rejects_private_ips_and_credentials_in_url(url):
    with pytest.raises((ValueError, NetworkError)):
        assert_safe_odoo_url(url)


class FakeResponse:
    def __init__(self, status=200, body=b'{"ok":true}'):
        self.status = status
        self.headers = {"Content-Type": "application/json"}
        self.body = body

    def read(self, length):
        return self.body[:length]

    def release_conn(self):
        pass


class FakePool:
    instances = []
    response = FakeResponse()

    def __init__(self, host, **kwargs):
        self.host = host
        self.kwargs = kwargs
        self.calls = []
        self.instances.append(self)

    def urlopen(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.response

    def close(self):
        pass


def public_dns(host, port, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]


def private_dns(host, port, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]


def test_pins_public_ip_and_verifies_original_tls_hostname():
    FakePool.instances.clear()
    api = PinnedHttpsTransport(resolver=public_dns, pool_factory=FakePool)
    assert api.post_json("https://odoo.example.org/json/2/res.partner/search_read",
                         {}, {"domain": []}, 10) == {"ok": True}
    pool = FakePool.instances[-1]
    assert pool.host == "93.184.216.34"
    assert pool.kwargs["server_hostname"] == "odoo.example.org"
    assert pool.kwargs["assert_hostname"] == "odoo.example.org"
    _, options = pool.calls[0]
    assert options["headers"]["Host"] == "odoo.example.org"
    assert options["redirect"] is False
    assert options["retries"] is False


def test_rebinding_public_dns_to_private_peer_denied():
    FakePool.instances.clear()
    api = PinnedHttpsTransport(resolver=private_dns, pool_factory=FakePool)
    with pytest.raises(NetworkError):
        api.post_json("https://odoo.example.org/json/2/res.partner/search_read", {}, {}, 10)
    assert not FakePool.instances


def test_redirect_never_followed():
    FakePool.response = FakeResponse(status=302)
    try:
        with pytest.raises(NetworkError):
            PinnedHttpsTransport(resolver=public_dns, pool_factory=FakePool).post_json(
                "https://odoo.example.org/json/2/res.partner/search_read", {}, {}, 10)
    finally:
        FakePool.response = FakeResponse()


def test_oversized_response_rejected():
    FakePool.response = FakeResponse(body=b"a" * 1100000)
    try:
        with pytest.raises(NetworkError):
            PinnedHttpsTransport(resolver=public_dns, pool_factory=FakePool).post_json(
                "https://odoo.example.org/json/2/res.partner/search_read", {}, {}, 10)
    finally:
        FakePool.response = FakeResponse()
