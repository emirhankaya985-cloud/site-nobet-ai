"""Owner-initiated Telegram handoff tests: no live bot and no direct confirmed SQL."""
from datetime import timedelta
import hashlib

from sqlalchemy import func, select

from app.models import Membership, NotificationChannel, TelegramLinkCode, utcnow


WEBHOOK = "/integrations/telegram/webhook"
SECRET = "CI-only-telegram-webhook-secret"
HEADER = {"X-Telegram-Bot-Api-Secret-Token": SECRET}


def h(user):
    return {"Authorization": "Bearer " + user["access_token"]}


def configured(monkeypatch):
    from app import main
    from types import SimpleNamespace
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(
        telegram_bot_token="synthetic-CI-token", telegram_webhook_secret=SECRET))


def start_url(org):
    return f"/organizations/{org}/notifications/telegram/link-code"


def webhook_message(code, chat_id=31337, chat_type="private", sender_id=None):
    if sender_id is None:
        sender_id = chat_id
    return {"message": {"text": "/start " + code,
                        "chat": {"id": chat_id, "type": chat_type},
                        "from": {"id": sender_id, "is_bot": False}}}


def issue(client, owner):
    response = client.post(start_url(owner["organization_id"]), headers=h(owner))
    assert response.status_code == 200, response.text
    return response.json()


def test_only_owner_may_issue_even_when_admin_has_write_permissions(
        client, database, two_users, monkeypatch):
    configured(monkeypatch)
    owner, admin = two_users
    org = owner["organization_id"]
    admin_id = client.get("/auth/me", headers=h(admin)).json()["id"]
    with database() as db:
        db.add(Membership(organization_id=org, user_id=admin_id, role="admin"))
        db.commit()
    assert client.post(start_url(org), headers=h(admin)).status_code == 403
    assert client.post(start_url(org), headers=h(owner)).status_code == 200
    assert client.post(start_url(org), headers=h(two_users[1])).status_code == 403


def test_pending_handoff_requires_owner_browser_confirmation_and_is_one_time(
        client, database, two_users, monkeypatch):
    configured(monkeypatch)
    owner, stranger = two_users
    org = owner["organization_id"]
    issued = issue(client, owner)
    code, link_id = issued["code"], issued["id"]
    status = f"/organizations/{org}/notifications/telegram/link-status/{link_id}"
    confirm = f"/organizations/{org}/notifications/telegram/confirm/{link_id}"
    with database() as db:
        item = db.get(TelegramLinkCode, link_id)
        assert item.code_hash == hashlib.sha256(code.encode()).hexdigest()
        assert code not in item.code_hash
        assert item.initiated_by_user_id == client.get("/auth/me", headers=h(owner)).json()["id"]
    assert client.get(status, headers=h(owner)).json()["state"] == "awaiting_telegram"
    assert client.post(confirm, headers=h(owner)).status_code == 409
    assert client.post(WEBHOOK, json=webhook_message(code)).status_code == 403
    assert client.post(WEBHOOK, json=webhook_message(code), headers=HEADER).status_code == 200
    assert client.get(status, headers=h(owner)).json() == {
        "state": "pending_confirmation", "telegram_user_id": "31337"}
    with database() as db:
        assert db.scalar(select(func.count()).select_from(NotificationChannel)) == 0
        assert db.get(TelegramLinkCode, link_id).redeemed_at is not None
    assert client.get(status, headers=h(stranger)).status_code == 404
    assert client.post(confirm, headers=h(stranger)).status_code == 404
    assert client.post(f"/organizations/{stranger['organization_id']}/notifications/telegram/confirm/{link_id}",
                       headers=h(stranger)).status_code == 404
    assert client.post(WEBHOOK, json=webhook_message(code, chat_id=999), headers=HEADER).status_code == 200
    assert client.get(status, headers=h(owner)).json()["telegram_user_id"] == "31337"
    assert client.post(confirm, headers=h(owner)).json()["confirmed"] is True
    assert client.post(confirm, headers=h(owner)).status_code == 409
    assert client.get(status, headers=h(owner)).json()["state"] == "confirmed"
    with database() as db:
        channels = db.scalars(select(NotificationChannel)).all()
        assert len(channels) == 1 and channels[0].confirmed
        assert channels[0].destination == "31337"


def test_expired_private_only_sender_match_and_unbound_legacy_codes(
        client, database, two_users, monkeypatch):
    configured(monkeypatch)
    owner = two_users[0]
    org = owner["organization_id"]
    issued = issue(client, owner)
    link_id, code = issued["id"], issued["code"]
    assert client.post(WEBHOOK, json=webhook_message(code, chat_type="group"), headers=HEADER).status_code == 200
    assert client.post(WEBHOOK, json=webhook_message(code, sender_id=9), headers=HEADER).status_code == 200
    assert client.get(f"/organizations/{org}/notifications/telegram/link-status/{link_id}",
                      headers=h(owner)).json()["state"] == "awaiting_telegram"
    with database() as db:
        row = db.get(TelegramLinkCode, link_id)
        row.expires_at = utcnow() - timedelta(seconds=1)
        # Legacy codes have no initiating owner and cannot complete a link after migration.
        db.add(TelegramLinkCode(organization_id=org,
                                code_hash=hashlib.sha256(b"legacy-code").hexdigest(),
                                expires_at=utcnow() + timedelta(minutes=3)))
        db.commit()
    assert client.post(WEBHOOK, json=webhook_message(code), headers=HEADER).status_code == 200
    assert client.post(WEBHOOK, json=webhook_message("legacy-code"), headers=HEADER).status_code == 200
    assert client.post(f"/organizations/{org}/notifications/telegram/confirm/{link_id}",
                       headers=h(owner)).status_code == 409
    with database() as db:
        assert db.scalar(select(func.count()).select_from(NotificationChannel)) == 0


def test_confirm_expires_between_telegram_and_owner_click(client, database, two_users, monkeypatch):
    configured(monkeypatch)
    owner = two_users[0]
    issued = issue(client, owner)
    assert client.post(WEBHOOK, json=webhook_message(issued["code"]), headers=HEADER).status_code == 200
    with database() as db:
        row = db.get(TelegramLinkCode, issued["id"])
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    confirm = f"/organizations/{owner['organization_id']}/notifications/telegram/confirm/{issued['id']}"
    assert client.post(confirm, headers=h(owner)).status_code == 409
    with database() as db:
        assert db.scalar(select(func.count()).select_from(NotificationChannel)) == 0
