import pytest
from app.models import NotificationChannel, NotificationDelivery, Organization
from app.notifications import deliver_one


@pytest.mark.asyncio
async def test_retry_and_success(database, monkeypatch):
    with database() as db:
        org=Organization(name="Org")
        db.add(org)
        db.flush()
        channel=NotificationChannel(organization_id=org.id,kind="ntfy",destination="token",confirmed=True)
        db.add(channel)
        db.flush()
        msg=NotificationDelivery(channel_id=channel.id,event_key="outage:1",message="down")
        db.add(msg)
        db.commit()
        async def fail(*a,**kw): raise RuntimeError("service unavailable")
        monkeypatch.setattr("app.notifications.send_delivery",fail)
        assert await deliver_one(db)
        assert msg.status == "pending" and msg.attempts == 1
        from app.models import utcnow
        msg.next_attempt_at = utcnow()
        db.commit()
        async def succeed(*a,**kw): return None
        monkeypatch.setattr("app.notifications.send_delivery",succeed)
        assert await deliver_one(db)
        assert msg.status == "sent" and msg.sent_at
        assert not await deliver_one(db)


@pytest.mark.asyncio
@pytest.mark.parametrize("body,expected_ok", [
    ({"ok": True, "result": {"message_id": 123}}, True),
    ({"ok": True, "result": {"message_id": 0}}, False),
    ({"ok": True, "result": {}}, False),
    ({"ok": False, "description": "api failure"}, False),
    ({"ok": True, "result": {"message_id": True}}, False),
])
async def test_telegram_semantic_ack_is_required(monkeypatch, body, expected_ok):
    import httpx
    from types import SimpleNamespace
    from app import notifications

    recorded = []

    def respond(request):
        recorded.append(request)
        return httpx.Response(200, json=body)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(notifications.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(respond), timeout=kwargs.get("timeout", 8)))
    monkeypatch.setattr(notifications, "get_settings", lambda: SimpleNamespace(
        telegram_bot_token="ci-fake-token", ntfy_base_url="https://ntfy.invalid"))
    channel = NotificationChannel(kind="telegram", destination="123456", confirmed=True)
    if expected_ok:
        await notifications.send_delivery(channel, "Test outage")
    else:
        with pytest.raises(RuntimeError):
            await notifications.send_delivery(channel, "Test outage")
    assert len(recorded) == 1
    assert str(recorded[0].url) == "https://api.telegram.org/botci-fake-token/sendMessage"
    assert recorded[0].method == "POST"
    assert recorded[0].read().decode().count("Test outage") == 1


@pytest.mark.asyncio
async def test_telegram_unacknowledged_response_is_retried(database, monkeypatch):
    import httpx
    from types import SimpleNamespace
    from app import notifications

    real_client = httpx.AsyncClient
    monkeypatch.setattr(notifications.httpx, "AsyncClient", lambda **kwargs: real_client(
        transport=httpx.MockTransport(lambda _req: httpx.Response(200, json={"ok": False})),
        timeout=kwargs.get("timeout", 8)))
    monkeypatch.setattr(notifications, "get_settings", lambda: SimpleNamespace(
        telegram_bot_token="ci-fake-token", ntfy_base_url="https://ntfy.invalid"))
    with database() as db:
        org = Organization(name="Telegram receipt")
        db.add(org)
        db.flush()
        channel = NotificationChannel(organization_id=org.id, kind="telegram", destination="123456", confirmed=True)
        db.add(channel)
        db.flush()
        delivery = NotificationDelivery(channel_id=channel.id, event_key="receipt:failure", message="down")
        db.add(delivery)
        db.commit()
        assert await deliver_one(db)
        assert delivery.status == "pending"
        assert delivery.attempts == 1
