import asyncio
import pytest
from app import ssl_checks


@pytest.mark.asyncio
async def test_ssl_dns_delay_respects_total_timeout(monkeypatch):
    async def slow_dns(_hostname, _port):
        await asyncio.sleep(1)
        return [("8.8.8.8", 2)]

    monkeypatch.setattr(ssl_checks, "resolve_public", slow_dns)
    expires_at, error = await ssl_checks.check_ssl("https://example.com/", timeout=0.01)
    assert expires_at is None
    assert error == "TimeoutError"


@pytest.mark.asyncio
async def test_http_url_skips_ssl_lookup(monkeypatch):
    async def dns_must_not_run(_hostname, _port):
        raise AssertionError("HTTP must not trigger a TLS probe")

    monkeypatch.setattr(ssl_checks, "resolve_public", dns_must_not_run)
    expires_at, error = await ssl_checks.check_ssl("http://example.com/")
    assert expires_at is None and error is None
