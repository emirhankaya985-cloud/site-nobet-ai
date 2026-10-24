import asyncio
from datetime import datetime, timezone
import socket
import ssl
from urllib.parse import urlsplit
from .security import resolve_public, safe_url, UnsafeTarget


async def check_ssl(url: str) -> tuple[datetime | None, str | None]:
    """Validate TLS against system trust and hostname while dialing a pinned public IP."""
    try:
        u = urlsplit(safe_url(url))
        if u.scheme != "https":
            return None, None
        if u.hostname is None:
            raise UnsafeTarget("Missing hostname")
        ips = await resolve_public(u.hostname, 443)
        return await asyncio.to_thread(_check_tls, u.hostname, ips[0][0])
    except (OSError, ssl.SSLError, UnsafeTarget, TimeoutError) as exc:
        return None, type(exc).__name__


def _check_tls(host: str, ip: str) -> tuple[datetime, None]:
    with socket.create_connection((ip, 443), timeout=8.0) as sock:
        with ssl.create_default_context().wrap_socket(sock, server_hostname=host) as tls:
            cert = tls.getpeercert()
            if not cert or not isinstance(cert.get("notAfter"), str):
                raise ssl.SSLError("Certificate expiry missing")
            expiry = datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), tz=timezone.utc)
            return expiry, None
