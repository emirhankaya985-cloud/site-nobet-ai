"""Outbound HTTP guard: DNS targets are validated AND pinned at connection time."""
import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit
import aiohttp
from aiohttp.abc import AbstractResolver


class UnsafeTarget(ValueError):
    pass


def safe_url(raw: str) -> str:
    if not isinstance(raw, str) or not (8 <= len(raw) <= 2048):
        raise UnsafeTarget("Invalid URL length")
    try:
        u = urlsplit(raw)
        if u.scheme.lower() not in ("https", "http") or not u.hostname or u.username or u.password or u.fragment:
            raise UnsafeTarget("Only HTTP/HTTPS URLs without credentials or fragments are allowed")
        try:
            ipaddress.ip_address(u.hostname)
        except ValueError:
            literal_ip = False
            hostname = u.hostname.encode("idna").decode("ascii").lower().rstrip(".")
        else:
            literal_ip = True
            hostname = u.hostname.lower()
            verify_ip(hostname)
        if not hostname or (not literal_ip and not all(c.isalnum() or c in ".-" for c in hostname)):
            raise UnsafeTarget("Invalid hostname")
        if hostname == "localhost" or hostname.endswith(".localhost") or hostname.endswith(".local"):
            raise UnsafeTarget("Local domains are forbidden")
        port = u.port or (443 if u.scheme == "https" else 80)
        if port != (443 if u.scheme == "https" else 80):
            raise UnsafeTarget("Only default web ports are supported")
        # Do not leak fragments, embedded secrets or unusual control bytes.
        if any(ord(c) < 32 for c in raw):
            raise UnsafeTarget("Control characters forbidden")
        netloc = f"[{hostname}]" if ":" in hostname else hostname
        return urlunsplit((u.scheme.lower(), netloc, u.path or "/", u.query, ""))
    except (ValueError, UnicodeError) as exc:
        raise UnsafeTarget("Invalid or unsafe URL") from exc


def verify_ip(ip: str):
    try:
        addr = ipaddress.ip_address(ip)
        if not addr.is_global or (isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped):
            raise UnsafeTarget("Non-public IP address is blocked")
    except ValueError as exc:
        raise UnsafeTarget("Invalid IP address") from exc


async def resolve_public(hostname: str, port: int) -> list[tuple[str, int]]:
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise OSError("DNS resolution failed") from exc
    targets: list[tuple[str, int]] = sorted(set((str(info[4][0]), int(info[0])) for info in infos))
    if not targets:
        raise OSError("No DNS answers")
    for ip, _ in targets:
        verify_ip(ip)  # Mixed private/public DNS results must fail closed.
    return targets


class PinnedResolver(AbstractResolver):
    def __init__(self, hostname: str, ips: list[tuple[str, int]]):
        self.hostname, self.ips = hostname, ips

    async def resolve(self, host, port=0, family=socket.AF_INET):
        if host.lower().rstrip(".") != self.hostname.lower().rstrip("."):
            raise UnsafeTarget("Unexpected DNS request")
        return [{"hostname": host, "host": ip, "port": port, "family": fam, "proto": 0, "flags": 0} for ip, fam in self.ips]

    async def close(self):
        pass


@dataclass
class Probe:
    is_up: bool
    status_code: int | None = None
    response_ms: float | None = None
    error_kind: str | None = None


def classify_error(exc: BaseException) -> str:
    if isinstance(exc, UnsafeTarget):
        return "UNSAFE_TARGET"
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return "TIMEOUT"
    if isinstance(exc, (aiohttp.ClientConnectorCertificateError, aiohttp.ClientSSLError)):
        return "TLS"
    if isinstance(exc, (aiohttp.ClientConnectorDNSError, socket.gaierror)):
        return "DNS"
    if isinstance(exc, OSError) and "DNS" in str(exc):
        return "DNS"
    return "CONNECTION"


async def probe_http(url: str, *, timeout: int = 10, redirects: int = 5) -> Probe:
    import time
    start = time.monotonic()
    try:
        # One deadline covers DNS, every redirect and TLS; a single probe
        # must not outlive the worker lease because each redirect gets its own client.
        async with asyncio.timeout(timeout):
            current = safe_url(url)
            for hop in range(redirects + 1):
                parsed = urlsplit(current)
                host = parsed.hostname
                if host is None:
                    raise UnsafeTarget("Missing hostname")
                port = 443 if parsed.scheme == "https" else 80
                ips = await resolve_public(host, port)
                connector = aiohttp.TCPConnector(resolver=PinnedResolver(host, ips), use_dns_cache=False, limit=1, ssl=True)
                async with aiohttp.ClientSession(connector=connector, trust_env=False, timeout=aiohttp.ClientTimeout(total=timeout), cookie_jar=aiohttp.DummyCookieJar()) as client:
                    async with client.get(current, allow_redirects=False, headers={"User-Agent": "SiteNobetAI/0.1", "Accept-Encoding": "identity"}, max_redirects=0) as resp:
                        code = resp.status
                        if 300 <= code <= 399 and resp.headers.get("Location"):
                            if hop == redirects:
                                return Probe(False, code, (time.monotonic()-start)*1000, "TOO_MANY_REDIRECTS")
                            current = safe_url(urljoin(current, resp.headers["Location"]))
                            continue
                        # Don't download remote bodies; closing stream bounds bandwidth and time.
                        return Probe(200 <= code < 400, code, (time.monotonic()-start)*1000, None if code < 400 else "HTTP_ERROR")
            return Probe(False, None, (time.monotonic()-start)*1000, "TOO_MANY_REDIRECTS")
    except (UnsafeTarget, OSError, aiohttp.ClientError, TimeoutError, asyncio.TimeoutError) as exc:
        return Probe(False, None, (time.monotonic()-start)*1000, classify_error(exc))
