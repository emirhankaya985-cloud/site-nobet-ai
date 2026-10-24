import pytest
from app.models import Monitor, Organization, utcnow
from app.worker import claim_monitor


def test_monitor_claim_lease(database):
    with database() as db:
        org = Organization(name="Org")
        db.add(org)
        db.flush()
        m=Monitor(organization_id=org.id,name="One",url="https://example.com/",interval_seconds=60)
        db.add(m)
        db.commit()
        first=claim_monitor(db)
        assert first.id == m.id
        assert claim_monitor(db) is None
        assert first.next_check_at > utcnow()
        assert first.leased_until > utcnow()


@pytest.mark.asyncio
async def test_worker_processes_monitor_check(database,monkeypatch):
    from app import worker
    from app.security import Probe
    async def fake_probe(url): return Probe(True,200,42,None)
    monkeypatch.setattr(worker,"session_factory",lambda:database)
    monkeypatch.setattr(worker,"probe_http",fake_probe)
    with database() as db:
        o=Organization(name="Test")
        db.add(o)
        db.flush()
        m=Monitor(organization_id=o.id,name="Test",url="http://example.com/",interval_seconds=60)
        db.add(m)
        db.commit()
        mid=m.id
    assert await worker.check_one()
    with database() as db:
        m=db.get(Monitor,mid)
        assert m.status == "UP"
        assert m.last_status_code == 200
        assert m.last_response_ms == 42


@pytest.mark.asyncio
async def test_worker_discards_stale_probe_after_lease_is_reclaimed(database, monkeypatch):
    from datetime import timedelta
    from app import worker
    from app.security import Probe

    with database() as db:
        org = Organization(name="Lease takeover")
        db.add(org)
        db.flush()
        monitor = Monitor(organization_id=org.id, name="Test", url="http://example.com/", interval_seconds=60)
        db.add(monitor)
        db.commit()
        monitor_id = monitor.id

    async def fake_probe(_url):
        # Simulate another worker claiming the lease while the old network call is pending.
        with database() as db:
            monitor = db.get(Monitor, monitor_id)
            monitor.leased_until = utcnow() + timedelta(minutes=2)
            db.commit()
        return Probe(False, 503, 50, "HTTP_ERROR")

    monkeypatch.setattr(worker, "session_factory", lambda: database)
    monkeypatch.setattr(worker, "probe_http", fake_probe)
    assert await worker.check_one()
    with database() as db:
        monitor = db.get(Monitor, monitor_id)
        assert monitor.status == "UNKNOWN"
        assert monitor.last_checked_at is None
        assert monitor.leased_until is not None
