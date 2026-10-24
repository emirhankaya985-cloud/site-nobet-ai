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
