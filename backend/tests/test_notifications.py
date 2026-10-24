import pytest
from app.models import NotificationChannel, NotificationDelivery, Organization
from app.notifications import deliver_one


@pytest.mark.asyncio
async def test_retry_and_success(database, monkeypatch):
    with database() as db:
        org=Organization(name="Org");db.add(org);db.flush()
        channel=NotificationChannel(organization_id=org.id,kind="ntfy",destination="token",confirmed=True)
        db.add(channel);db.flush()
        msg=NotificationDelivery(channel_id=channel.id,event_key="outage:1",message="down")
        db.add(msg);db.commit()
        async def fail(*a,**kw): raise RuntimeError("service unavailable")
        monkeypatch.setattr("app.notifications.send_delivery",fail)
        assert await deliver_one(db)
        assert msg.status == "pending" and msg.attempts == 1
        from app.models import utcnow
        msg.next_attempt_at = utcnow();db.commit()
        async def succeed(*a,**kw): return None
        monkeypatch.setattr("app.notifications.send_delivery",succeed)
        assert await deliver_one(db)
        assert msg.status == "sent" and msg.sent_at
        assert not await deliver_one(db)
