"""HTTPS-only, DNS-pinned Odoo transport with TLS hostname verification.

A public DNS result is explicitly pinned as the socket destination while SNI
and certificate hostname verification stay bound to the original Odoo host.
Never fall back to a client that re-resolves the hostname or honors proxies.
"""
from __future__ import annotations

import ipaddress
import json
import re
import socket
import ssl
from urllib.parse import urlsplit

import urllib3

from .errors import AppError

_API_PATH = re.compile(r"^/json/2/[a-z_][a-z0-9_.]*/(?:search_read|read|fields_get|create|write)$")
_MAX_BODY_BYTES = 1_048_576


class NetworkError(AppError):
    def __init__(self, message: str = "Odoo network request was blocked"):
        super().__init__("upstream_error", 502, message)


def _is_public_ip(value: str) -> bool:
    try:
        addr = ipaddress.ip_address(value)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        return addr.is_global
    except ValueError:
        return False


def assert_safe_odoo_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 2048:
        raise NetworkError("Invalid Odoo URL")
    try:
        parsed = urlsplit(url.strip())
        host = parsed.hostname
        if (parsed.scheme != "https" or not host
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")
            or parsed.port not in (None, 443)):
            raise NetworkError("Odoo URL must be a public HTTPS origin")
        host = host.rstrip(".").encode("idna").decode("ascii").lower()
        if not host or host in ("localhost",) or host.endswith((".localhost", ".local", ".internal")):
            raise NetworkError("Private Odoo host is not permitted")
        if (ipaddress.ip_address(host) if _is_ip_literal(host) else None) is not None:
            if not _is_public_ip(host):
                raise NetworkError("Private IP address is not permitted")
        if any(c in host for c in ("%", "/", " ", "\\", "@")):
            raise NetworkError("Invalid hostname")
        if ":" in host:  # bracket any globally routed IPv6 literal
            host = "[" + host + "]"
        return "https://" + host
    except (ValueError, UnicodeError) as exc:
        raise NetworkError("Invalid Odoo URL") from exc


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


class PinnedHttpsTransport:
    """Always resolve, require globally routable addresses, then connect by IP."""

    def __init__(self, resolver=None, pool_factory=None):
        self.resolver = resolver or socket.getaddrinfo
        self.pool_factory = pool_factory or urllib3.HTTPSConnectionPool

    def _public_peer(self, host: str) -> str:
        try:
            info = self.resolver(host, 443, type=socket.SOCK_STREAM)
            addresses = sorted({row[4][0] for row in info})
        except (socket.gaierror, OSError, KeyError, IndexError) as exc:
            raise NetworkError("Odoo hostname could not be resolved") from exc
        if not addresses or not all(_is_public_ip(ip) for ip in addresses):
            raise NetworkError("Odoo hostname resolves to a private or invalid address")
        return addresses[0]

    def post_json(self, url: str, headers: dict, payload: dict, timeout_s: int) -> object:
        parsed = urlsplit(url)
        origin = assert_safe_odoo_url(parsed.scheme + "://" + parsed.netloc)
        if not _API_PATH.fullmatch(parsed.path) or parsed.query or parsed.fragment:
            raise NetworkError("Odoo API path is not permitted")
        if not isinstance(payload, dict):
            raise NetworkError("Odoo payload must be an object")
        if not 1 <= timeout_s <= 15:
            raise NetworkError("Odoo timeout must be between 1 and 15 seconds")
        host = urlsplit(origin).hostname
        peer = self._public_peer(host)
        data = json.dumps(payload, separators=(",", ":")).encode()
        if len(data) > _MAX_BODY_BYTES:
            raise NetworkError("Odoo request exceeded size limit")
        clean_headers = dict(headers)
        clean_headers.update({"Host": host, "Content-Type": "application/json",
                              "Accept": "application/json"})
        pool = self.pool_factory(peer, port=443, server_hostname=host,
                                 assert_hostname=host, cert_reqs=ssl.CERT_REQUIRED,
                                 maxsize=1, retries=False)
        response = None
        try:
            response = pool.urlopen(
                "POST", parsed.path, body=data, headers=clean_headers,
                redirect=False, retries=False,
                timeout=urllib3.Timeout(total=timeout_s, connect=min(5, timeout_s),
                                        read=timeout_s),
                preload_content=False,
            )
            if response.status in (301, 302, 303, 307, 308):
                raise NetworkError("Redirects are not permitted for Odoo connections")
            if response.status == 401:
                raise AppError("authentication_failed", 401, "Odoo rejected the supplied API key")
            if response.status == 403:
                raise AppError("unsupported_odoo_api", 403,
                               "Odoo external API access denied; check your plan and API-user permissions")
            if response.status == 429:
                raise AppError("rate_limited", 429, "Odoo is rate limiting requests")
            if response.status >= 400:
                raise AppError("upstream_error", 502, "Odoo returned an upstream error")
            if not response.headers.get("Content-Type", "").lower().startswith("application/json"):
                raise NetworkError("Odoo returned a non-JSON response")
            if int(response.headers.get("Content-Length", "0")) > _MAX_BODY_BYTES:
                raise NetworkError("Odoo response exceeded size limit")
            body = response.read(_MAX_BODY_BYTES + 1)
            if len(body) > _MAX_BODY_BYTES:
                raise NetworkError("Odoo response exceeded size limit")
            try:
                return json.loads(body)
            except (ValueError, UnicodeError) as exc:
                raise NetworkError("Odoo response was not valid JSON") from exc
        except (urllib3.exceptions.TimeoutError, TimeoutError) as exc:
            raise AppError("timeout", 504, "Odoo request timed out") from exc
        except urllib3.exceptions.HTTPError as exc:
            raise NetworkError("Odoo TLS/network connection failed") from exc
        finally:
            if response is not None:
                response.release_conn()
            pool.close()

    def get_metadata_json(self, url: str, timeout_s: int = 5) -> object:
        """Fetch HTTPS Client ID metadata using a public-IP pinned TLS peer."""
        if not isinstance(url, str) or len(url) > 1024:
            raise NetworkError("Invalid client metadata URL")
        parsed = urlsplit(url)
        host = urlsplit(assert_safe_odoo_url(parsed.scheme + "://" + parsed.netloc)).hostname
        if (not parsed.path.startswith("/") or parsed.path == "/" or
                parsed.query or parsed.fragment or not 1 <= timeout_s <= 5):
            raise NetworkError("Client metadata URL must have a path and no query")
        peer = self._public_peer(host)
        pool = self.pool_factory(peer, port=443, server_hostname=host,
                                 assert_hostname=host, cert_reqs=ssl.CERT_REQUIRED,
                                 maxsize=1, retries=False)
        response = None
        try:
            response = pool.urlopen(
                "GET", parsed.path, headers={"Host": host, "Accept": "application/json"},
                redirect=False, retries=False,
                timeout=urllib3.Timeout(total=timeout_s, connect=min(3, timeout_s),
                                        read=timeout_s),
                preload_content=False,
            )
            if response.status != 200:
                raise NetworkError("Client metadata request failed")
            if not response.headers.get("Content-Type", "").lower().startswith("application/json"):
                raise NetworkError("Client metadata must be JSON")
            if int(response.headers.get("Content-Length", "0")) > 32768:
                raise NetworkError("Client metadata too large")
            body = response.read(32769)
            if len(body) > 32768:
                raise NetworkError("Client metadata too large")
            try:
                return json.loads(body)
            except ValueError as exc:
                raise NetworkError("Invalid JSON in client metadata") from exc
        except (urllib3.exceptions.TimeoutError, urllib3.exceptions.HTTPError) as exc:
            raise NetworkError("Client metadata HTTPS request failed") from exc
        finally:
            if response is not None:
                response.release_conn()
            pool.close()
