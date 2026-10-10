"""Outbound HTTP with SSRF protections.

- Only http/https on standard web ports.
- Every resolved address must be globally routable (no loopback, private, link-local,
  CGNAT, multicast, reserved or cloud metadata ranges).
- Redirects are followed manually (max 3) and every hop is re-validated.
- Response size and total time are capped.

Known limitation: DNS is resolved for validation and again by the HTTP library, so a
hostile DNS server could rebind between the two lookups. Deploy behind an egress proxy
/ firewall for defense in depth (documented in README).
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

ALLOWED_SCHEMES = {"http", "https"}
ALLOWED_PORTS = {80, 443, 8080, 8443}
MAX_REDIRECTS = 3
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal", "metadata", "instance-data"}
_BLOCKED_NETWORKS = [
    ipaddress.ip_network(n)
    for n in (
        "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
        "192.0.0.0/24", "192.168.0.0/16", "198.18.0.0/15", "224.0.0.0/4", "240.0.0.0/4",
        "::1/128", "fc00::/7", "fe80::/10", "ff00::/8", "::ffff:0:0/96", "64:ff9b::/96",
    )
]
_SAFE_RESPONSE_HEADERS = {"content-type", "content-length", "etag", "last-modified", "cache-control", "x-request-id"}


class EgressBlocked(Exception):
    pass


@dataclass
class HttpResult:
    status: int
    headers: dict[str, str]
    body: Any
    duration_ms: int
    url: str


def _ip_allowed(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if any(ip in net for net in _BLOCKED_NETWORKS):
        return False
    return ip.is_global


def validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise EgressBlocked("Only http and https URLs are allowed")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise EgressBlocked("URL has no host")
    if parsed.username or parsed.password:
        raise EgressBlocked("Credentials in URLs are not allowed; use connector auth instead")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise EgressBlocked(f"Port {port} is not allowed")
    if host in BLOCKED_HOSTNAMES or host.endswith((".internal", ".local", ".localhost")):
        raise EgressBlocked("Internal hostnames are not allowed")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise EgressBlocked(f"Could not resolve host {host}") from exc
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise EgressBlocked(f"Could not resolve host {host}")
    for address in addresses:
        if not _ip_allowed(ipaddress.ip_address(address.split("%")[0])):
            raise EgressBlocked("Destination resolves to a private or reserved address")
    return url


def request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    json_body: Any = None,
    timeout_s: float = 8.0,
) -> HttpResult:
    if os.environ.get("ANYAPI_HTTP_EGRESS_ENABLED", "").lower() != "true":
        raise EgressBlocked("HTTP connectors require an explicitly configured protected egress environment")
    started = time.monotonic()
    deadline = started + timeout_s
    current_url, current_method, body = url, method.upper(), json_body
    for _ in range(MAX_REDIRECTS + 1):
        validate_url(current_url)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("HTTP request timed out")
        resp = requests.request(
            current_method,
            current_url,
            headers={"User-Agent": "AnyAPI-Connector/1.0", **(headers or {})},
            params=params,
            json=body if current_method not in ("GET", "HEAD") else None,
            timeout=(min(3.0, remaining), remaining),
            allow_redirects=False,
            stream=True,
        )
        if resp.is_redirect and resp.headers.get("Location"):
            current_url = urljoin(current_url, resp.headers["Location"])
            params = None
            if resp.status_code in (301, 302, 303):
                current_method, body = "GET", None
            resp.close()
            continue
        content = b""
        for chunk in resp.iter_content(chunk_size=65536):
            content += chunk
            if len(content) > MAX_RESPONSE_BYTES:
                resp.close()
                raise EgressBlocked("Upstream response exceeds 2 MB limit")
            if time.monotonic() > deadline:
                resp.close()
                raise TimeoutError("HTTP request timed out")
        text = content.decode(resp.encoding or "utf-8", errors="replace")
        parsed_body: Any = text
        if "json" in resp.headers.get("Content-Type", "") or text[:1] in ("{", "["):
            try:
                parsed_body = json.loads(text)
            except ValueError:
                parsed_body = text
        return HttpResult(
            status=resp.status_code,
            headers={k.lower(): v for k, v in resp.headers.items() if k.lower() in _SAFE_RESPONSE_HEADERS},
            body=parsed_body,
            duration_ms=int((time.monotonic() - started) * 1000),
            url=current_url,
        )
    raise EgressBlocked("Too many redirects")
