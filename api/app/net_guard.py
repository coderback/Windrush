"""
SSRF guard for server-side requests to user-influenced URLs.

The API runs inside the Docker network next to ollama, jobs-mcp, civic-guardrails, etc., so
any URL a user can steer us to (pasted job links, job URLs in request bodies, redirects from
those pages) must resolve only to public addresses. Every redirect hop is re-checked.

Residual risk: DNS rebinding (the name re-resolving to a private IP between our check and
httpx's own lookup). Closing that needs IP pinning at the transport layer.
"""
import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import httpx

_MAX_REDIRECTS = 5


class UnsafeURLError(ValueError):
    """The URL is malformed, non-http(s), or points at a non-public address."""


def _is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def check_public_url(url: str) -> None:
    """Raise UnsafeURLError unless `url` is http(s) and its host resolves only to public IPs."""
    parsed = urlparse(url or "")
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURLError("only http(s) links are allowed")
    host = parsed.hostname
    if not host:
        raise UnsafeURLError("the link has no host")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, ValueError) as exc:
        raise UnsafeURLError(f"could not resolve {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%", 1)[0])  # drop IPv6 zone id
        if not _is_public(ip):
            raise UnsafeURLError(f"{host} resolves to a non-public address")


async def assert_public_url(url: str) -> None:
    await asyncio.to_thread(check_public_url, url)  # getaddrinfo blocks


async def safe_get(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """GET `url`, following redirects manually so every hop passes check_public_url."""
    for _ in range(_MAX_REDIRECTS + 1):
        await assert_public_url(url)
        resp = await client.get(url, follow_redirects=False)
        if not resp.is_redirect:
            return resp
        url = urljoin(str(resp.url), resp.headers.get("location", ""))
    raise UnsafeURLError("too many redirects")
