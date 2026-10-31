"""Real PostgreSQL smoke tests; run after Alembic migrations in ephemeral CI database.

These tests must never target production or a persistent customer database.
"""
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import get_engine, session_factory
from app.main import app
from app.models import CheckResult, Incident, Monitor, NotificationChannel, NotificationDelivery, Organization, utcnow
from app.monitoring import apply_probe
from app.security import Probe
from app.worker import claim_monitor

pytestmark = pytest.mark.skipif(
    os.getenv("SITENOBET_TEST_POSTGRES") != "1",
    reason="Postgres integration runs only in isolated GitHub CI database",
)


@pytest.fixture(autouse=True)
def postgres_only():
    if os.getenv("SITENOBET_TEST_POSTGRES") == "1":
        assert get_engine().dialect.name == "postgresql", "This suite requires real PostgreSQL"
        assert get_engine().url.database == "sitenobet_test", "Refuse non-CI database"


def test_postgres_concurrent_claim_avoids_duplicate_monitor():
    with session_factory()() as db:
        org = Organization(name="Concurrent claim CI")
        db.add(org)
        db.flush()
        monitors = [Monitor(organization_id=org.id, name=f"CI {n}",
                            url=f"http://example{n}.com", interval_seconds=60)
                    for n in range(2)]
        db.add_all(monitors)
        db.commit()
        ids = {m.id for m in monitors}

    def claim_from_independent_session():
        with session_factory()() as db:
            claimed = claim_monitor(db)
            return claimed.id if claimed else None

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: claim_from_independent_session(), range(2)))
    assert {first, second} == ids

    with session_factory()() as db:
        for monitor_id in ids:
            row = db.get(Monitor, monitor_id)
            assert row.leased_until is not None
            assert row.next_check_at is not None


@pytest.mark.asyncio
async def test_postgres_reclaimed_lease_rejects_stale_worker(monkeypatch):
    from app import worker

    with session_factory()() as db:
        org = Organization(name="Reclaim CI")
        db.add(org)
        db.flush()
        monitor = Monitor(organization_id=org.id, name="Reclaim", url="http://example.net", interval_seconds=60)
        db.add(monitor)
        db.commit()
        mid = monitor.id

    async def simulated_delayed_probe(_url):
        with session_factory()() as db:
            row = db.get(Monitor, mid)
            row.leased_until = utcnow() + timedelta(minutes=2)
            db.commit()
        return Probe(False, 503, 25.0, "HTTP_ERROR")

    monkeypatch.setattr(worker, "probe_http", simulated_delayed_probe)
    assert await worker.check_one() is True
    with session_factory()() as db:
        row = db.get(Monitor, mid)
        assert row.status == "UNKNOWN"
        assert row.last_checked_at is None
        assert db.scalars(select(CheckResult).where(CheckResult.monitor_id == mid)).first() is None


def test_postgres_incident_and_outbox_stay_with_own_tenant():
    with session_factory()() as db:
        owner = Organization(name="Owner CI")
        stranger = Organization(name="Other tenant CI")
        db.add_all([owner, stranger])
        db.flush()
        monitor = Monitor(organization_id=owner.id, name="Owned site", url="https://example.com")
        own_channel = NotificationChannel(organization_id=owner.id, kind="ntfy", destination="ci-own", confirmed=True)
        wrong_channel = NotificationChannel(organization_id=stranger.id, kind="ntfy", destination="ci-other", confirmed=True)
        db.add_all([monitor, own_channel, wrong_channel])
        db.commit()
        for up in (False, False, False, True, True):
            apply_probe(db, monitor, Probe(up, 200 if up else 503, 42))
            db.commit()
        incidents = db.scalars(select(Incident).where(Incident.monitor_id == monitor.id)).all()
        own_deliveries = db.scalars(select(NotificationDelivery).where(NotificationDelivery.channel_id == own_channel.id)).all()
        wrong_deliveries = db.scalars(select(NotificationDelivery).where(NotificationDelivery.channel_id == wrong_channel.id)).all()
        assert len(incidents) == 1 and incidents[0].closed_at is not None
        assert monitor.status == "UP"
        assert len(own_deliveries) == 2
        assert len(wrong_deliveries) == 0
        assert all(item.status == "pending" for item in own_deliveries)


def test_postgres_api_does_not_leak_tenants():
    with TestClient(app) as client:
        def register(email):
            res = client.post("/auth/register", json={"email": email, "password": "strong-CI-password-2026", "organization_name": email})
            assert res.status_code == 201, res.text
            return res.json()
        alice = register("ci-postgres-alice@example.com")
        bob = register("ci-postgres-bob@example.com")
        owner_org = alice["organization_id"]
        headers_a = {"Authorization": f"Bearer {alice['access_token']}"}
        headers_b = {"Authorization": f"Bearer {bob['access_token']}"}
        created = client.post(f"/organizations/{owner_org}/monitors", headers=headers_a,
                              json={"name": "Isolated CI monitor", "url": "https://example.com"})
        assert created.status_code == 201, created.text
        monitor_id = created.json()["id"]
        assert client.get(f"/organizations/{owner_org}/monitors/{monitor_id}", headers=headers_a).status_code == 200
        assert client.get(f"/organizations/{owner_org}/monitors/{monitor_id}", headers=headers_b).status_code == 404
        assert client.get(f"/organizations/{owner_org}/reports", headers=headers_b).status_code == 404


def test_postgres_concurrent_claim_avoids_duplicate_delivery():
    from app.notifications import claim_delivery

    with session_factory()() as db:
        org = Organization(name="Delivery claim CI")
        db.add(org)
        db.flush()
        channel = NotificationChannel(
            organization_id=org.id, kind="ntfy", destination="ci-topic", confirmed=True
        )
        db.add(channel)
        db.flush()
        deliveries = [
            NotificationDelivery(channel_id=channel.id, event_key=f"ci:delivery:claim:{n}", message="outage", next_attempt_at=utcnow() - timedelta(days=1))
            for n in range(2)
        ]
        db.add_all(deliveries)
        db.commit()
        ids = {d.id for d in deliveries}

    def claim_from_independent_session():
        with session_factory()() as db:
            row = claim_delivery(db)
            return row.id if row else None

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda _: claim_from_independent_session(), range(2)))
    assert {first, second} == ids


@pytest.mark.asyncio
async def test_postgres_expired_delivery_lease_fencing(monkeypatch):
    from app import notifications

    with session_factory()() as db:
        org = Organization(name="Fenced notification CI")
        db.add(org)
        db.flush()
        channel = NotificationChannel(organization_id=org.id, kind="ntfy", destination="ci-topic", confirmed=True)
        db.add(channel)
        db.flush()
        delivery = NotificationDelivery(channel_id=channel.id, event_key="ci:delivery:fencing", message="outage", next_attempt_at=utcnow() - timedelta(days=1))
        db.add(delivery)
        db.commit()
        delivery_id = delivery.id

    async def delayed_send(_channel, _message):
        with session_factory()() as successor:
            row = successor.get(NotificationDelivery, delivery_id)
            row.leased_until = utcnow() + timedelta(minutes=2)
            successor.commit()

    monkeypatch.setattr(notifications, "send_delivery", delayed_send)
    with session_factory()() as sender:
        assert await notifications.deliver_one(sender)
    with session_factory()() as db:
        row = db.get(NotificationDelivery, delivery_id)
        assert row.status == "pending"
        assert row.sent_at is None
        assert row.leased_until is not None


def test_postgres_concurrent_business_mail_deduplicates_recipient():
    from app.models import BusinessLead
    from app.business_mail import run_once
    with session_factory()() as db:
        org=Organization(name='Synthetic mail race')
        db.add(org)
        db.flush()
        oid=org.id
        db.add(NotificationChannel(organization_id=oid,kind='telegram',destination='123',confirmed=True))
        for n in range(2):
            db.add(BusinessLead(organization_id=oid,source_id=f'node/{n}',name='Synthetic',email='race@example.invalid',email_source='OSM business contact tag',delivery_state='not_sent'))
        db.commit()
    env=dict(BUSINESS_AUTO_MAIL_ENABLED='true',BUSINESS_HISTORY_RECONCILED='true',LEGACY_MAIL_WORKFLOW_DISABLED='true',BUSINESS_ORGANIZATION_ID=oid,GMAIL_SENDER_ADDRESS='owner@example.invalid',GMAIL_APP_PASSWORD='synthetic')
    calls=[]
    def sender(claim, _):
        calls.append(claim.id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _:run_once(session_factory(),env,sender),range(2)))
    assert len(calls)==1


def test_postgres_parallel_send_limit_remains_five():
    from app.models import BusinessLead, MailClaim
    from app.business_mail import run_once
    with session_factory()() as db:
        org=Organization(name='Synthetic quota race')
        db.add(org)
        db.flush()
        oid=org.id
        db.add(NotificationChannel(organization_id=oid,kind='telegram',destination='123',confirmed=True))
        for n in range(10):
            db.add(BusinessLead(organization_id=oid,source_id=f'node/{n+900}',
                name='Synthetic',email=f'quota{n}@example.invalid',
                email_source='OSM business contact tag',delivery_state='not_sent'))
        db.commit()
    env=dict(BUSINESS_AUTO_MAIL_ENABLED='true',BUSINESS_HISTORY_RECONCILED='true',
        LEGACY_MAIL_WORKFLOW_DISABLED='true',BUSINESS_ORGANIZATION_ID=oid,
        GMAIL_SENDER_ADDRESS='owner@example.invalid',GMAIL_APP_PASSWORD='synthetic')
    calls=[]
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _:run_once(session_factory(),env,lambda c,e:calls.append(c.id)),range(3)))
    with session_factory()() as db:
        assert len(db.scalars(select(MailClaim).where(MailClaim.organization_id==oid)).all())==5
    assert len(calls)==5


def test_postgres_concurrent_owner_telegram_confirm_once(monkeypatch):
    """Real PG row locking: only one browser confirmation can create a channel."""
    from app import main
    from types import SimpleNamespace
    from uuid import uuid4
    monkeypatch.setattr(main, 'get_settings', lambda: SimpleNamespace(
        telegram_bot_token='synthetic', telegram_webhook_secret='pg-CI-webhook-secret'))
    with TestClient(app) as client:
        payload={'email':f'owner-{uuid4().hex}@example.invalid',
                 'password':'very-strong-CI-password', 'organization_name':'Owner PG CI'}
        issued=client.post('/auth/register',json=payload)
        assert issued.status_code==201
        credentials=issued.json()
        org=credentials['organization_id']
        headers={'Authorization':'Bearer '+credentials['access_token']}
        base=f'/organizations/{org}/notifications/telegram'
        response=client.post(base+'/link-code',headers=headers)
        assert response.status_code==200,response.text
        link=response.json()
        webhook=client.post('/integrations/telegram/webhook',
            headers={'X-Telegram-Bot-Api-Secret-Token':'pg-CI-webhook-secret'},
            json={'message':{'text':'/start '+link['code'],
                  'chat':{'id':456123,'type':'private'},
                  'from':{'id':456123,'is_bot':False}}})
        assert webhook.status_code==200
        path=base+'/confirm/'+link['id']
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses=list(pool.map(lambda _: client.post(path,headers=headers).status_code,range(2)))
        assert sorted(responses)==[200,409]
    with session_factory()() as db:
        channels=db.scalars(select(NotificationChannel).where(
            NotificationChannel.organization_id==org,
            NotificationChannel.kind=='telegram')).all()
        assert len(channels)==1 and channels[0].confirmed
        assert channels[0].destination=='456123'


@pytest.mark.asyncio
async def test_postgres_disabled_mail_never_claims_daily_batch():
    from app.business_pipeline import run
    from app.models import BusinessBatch, MailClaim
    with session_factory()() as db:
        org=Organization(name='Disabled mail PG CI')
        db.add(org)
        db.commit()
        org_id=org.id
    env={'BUSINESS_PIPELINE_ENABLED':'true', 'BUSINESS_HISTORY_RECONCILED':'true',
         'LEGACY_MAIL_WORKFLOW_DISABLED':'true', 'BUSINESS_AUTO_MAIL_ENABLED':'false',
         'BUSINESS_ORGANIZATION_ID':org_id}
    def forbidden(*_a,**_kw):
        raise AssertionError('Research/mail/database side effect must be impossible')
    async def invoke():
        with pytest.raises(RuntimeError,match='mail disabled'):
            await run(env=env,factory=forbidden,researcher=forbidden,mailer=forbidden,
                      monitor=forbidden)
    await invoke()
    await invoke()
    with session_factory()() as db:
        assert db.scalars(select(BusinessBatch).where(BusinessBatch.organization_id==org_id)).all()==[]
        assert db.scalars(select(MailClaim).where(MailClaim.organization_id==org_id)).all()==[]


@pytest.mark.asyncio
async def test_postgres_mail_crash_preserves_claim_and_daily_barrier():
    """No actual SMTP; a persisted in-flight claim must bar automatic retry."""
    from app.business_pipeline import run
    from app.models import BusinessBatch, BusinessLead, MailClaim
    from unittest.mock import AsyncMock
    with session_factory()() as db:
        org=Organization(name='Crash before SMTP acknowledgement PG CI')
        db.add(org)
        db.flush()
        oid=org.id
        lead=BusinessLead(organization_id=oid,source_id='node/CI-claim',name='Synthetic',
            email='pg-uncertain@example.invalid',email_source='synthetic',
            delivery_state='not_sent')
        db.add(lead)
        db.commit()
        lid=lead.id
    env={'BUSINESS_PIPELINE_ENABLED':'true', 'BUSINESS_HISTORY_RECONCILED':'true',
         'LEGACY_MAIL_WORKFLOW_DISABLED':'true', 'BUSINESS_AUTO_MAIL_ENABLED':'true',
         'BUSINESS_ORGANIZATION_ID':oid}
    def interrupted(factory,_env):
        with factory() as db:
            lead=db.get(BusinessLead,lid)
            lead.delivery_state='sending'
            db.add(MailClaim(organization_id=oid,lead_id=lid,
                recipient=lead.email,subject='Synthetic',body='Synthetic',
                state='sending'))
            db.commit()
        raise RuntimeError('Simulated process crash after claim, before SMTP status')
    with pytest.raises(RuntimeError,match='Simulated process crash'):
        await run(env=env,factory=session_factory(),researcher=lambda _:[],
                  mailer=interrupted,monitor=AsyncMock())
    with session_factory()() as db:
        batch=db.scalars(select(BusinessBatch).where(BusinessBatch.organization_id==oid)).one()
        assert batch.state=='running'
        assert db.scalars(select(MailClaim).where(MailClaim.organization_id==oid)).one().state=='sending'
    result=await run(env=env,factory=session_factory(),researcher=lambda _: pytest.fail('retry'),
                     mailer=lambda *_:pytest.fail('SMTP retry'),monitor=AsyncMock())
    assert result['skipped_existing_daily_batch']==1
