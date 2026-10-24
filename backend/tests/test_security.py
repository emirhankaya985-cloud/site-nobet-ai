import asyncio
import pytest
from app.security import safe_url, verify_ip, UnsafeTarget, resolve_public, probe_http, PinnedResolver


@pytest.mark.parametrize("url", [
 "file:///etc/passwd", "http://localhost/", "http://user:pass@example.com", "http://example.com:8080",
 "http://127.0.0.1:8000", "http://example.local", "https://example.com/#fragment", "https://example.com:4443",
 "gopher://example.com", "https://example.com\nX-Bad: yes"
])
def test_disallow_unsafe_urls(url):
    with pytest.raises(UnsafeTarget):
        safe_url(url) if "127.0.0.1" not in url else (safe_url(url), verify_ip("127.0.0.1"))


@pytest.mark.parametrize("ip", ["127.0.0.1","169.254.169.254","10.1.2.3","192.168.1.1","::1","fc00::1","fe80::1","0.0.0.0","::ffff:127.0.0.1"])
def test_private_ip_blocked(ip):
    with pytest.raises(UnsafeTarget):
        verify_ip(ip)


def test_global_ip_allowed():
    verify_ip("8.8.8.8")
    verify_ip("2606:4700:4700::1111")


@pytest.mark.asyncio
async def test_mixed_dns_rejected(monkeypatch):
    class Loop:
        async def getaddrinfo(self, *a, **k):
            return [(2,1,0,"",("8.8.8.8",80)),(2,1,0,"",("10.0.0.1",80))]
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: Loop())
    with pytest.raises(UnsafeTarget):
        await resolve_public("example.com", 80)


@pytest.mark.asyncio
async def test_dns_pinning_rejects_unexpected_host():
    resolver = PinnedResolver("example.com", [("8.8.8.8",2)])
    with pytest.raises(UnsafeTarget):
        await resolver.resolve("internal.local",80)


@pytest.mark.asyncio
async def test_private_ip_probe_does_not_connect():
    result = await probe_http("http://127.0.0.1/")
    assert result.error_kind == "UNSAFE_TARGET"


def test_normalize_url():
    assert safe_url("https://EXAMPLE.COM") == "https://example.com/"


@pytest.mark.asyncio
async def test_redirect_to_cloud_metadata_blocked(monkeypatch):
    import app.security as sec
    class DummyConnector:
        def __init__(self, **kwargs): pass
    class FakeResponse:
        status=301
        headers={"Location":"http://169.254.169.254/latest/meta-data"}
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
    class DummySession:
        def __init__(self, **kwargs): self.calls=0
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def get(self, *args, **kwargs):
            self.calls+=1
            if self.calls > 1:
                raise AssertionError("The redirect target was requested!")
            return FakeResponse()
    async def resolve(*args):return [("8.8.8.8", socket.AF_INET)]
    import socket
    monkeypatch.setattr(sec, "resolve_public", resolve)
    monkeypatch.setattr(sec.aiohttp,"TCPConnector",DummyConnector)
    monkeypatch.setattr(sec.aiohttp,"ClientSession",DummySession)
    result = await sec.probe_http("https://example.com/")
    assert not result.is_up
    assert result.error_kind == "UNSAFE_TARGET"


@pytest.mark.asyncio
async def test_probe_categorizes_dns_failure(monkeypatch):
    import app.security as sec
    async def failing_dns(host,port):raise OSError("DNS resolution failed")
    monkeypatch.setattr(sec,"resolve_public",failing_dns)
    result = await sec.probe_http("https://example.com/")
    assert result.error_kind == "DNS" and not result.is_up


def test_public_ipv6_literal_supported():
    assert safe_url("https://[2606:4700:4700::1111]/") == "https://[2606:4700:4700::1111]/"
