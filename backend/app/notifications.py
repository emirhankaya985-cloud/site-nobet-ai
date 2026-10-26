from datetime import datetime, timedelta, timezone
from urllib.parse import quote
import httpx
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from .config import get_settings
from .models import NotificationChannel, NotificationDelivery, utcnow


async def send_delivery(channel: NotificationChannel, message: str) -> None:
    config = get_settings()
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=False, trust_env=False) as client:
        if channel.kind == "telegram":
            if not config.telegram_bot_token or not channel.destination.isdigit():
                raise RuntimeError("Telegram channel not configured")
            response = await client.post(f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage", json={"chat_id": channel.destination, "text": message})
        elif channel.kind == "ntfy":
            # Only administrator-configured HTTPS server, topic has 256 bits entropy.
            if not config.ntfy_base_url.startswith("https://"):
                raise RuntimeError("NTFY_BASE_URL must be HTTPS")
            response = await client.post(f"{config.ntfy_base_url.rstrip('/')}/{quote(channel.destination, safe='')}", content=message.encode(), headers={"Title": "SiteNobet AI", "Priority": "high"})
        else:
            raise RuntimeError("Unsupported notification channel")
        response.raise_for_status()
        if channel.kind == "telegram":
            # HTTP 200 is not enough: validate Telegram's application-level receipt.
            try:
                receipt = response.json()
            except ValueError as exc:
                raise RuntimeError("Telegram response is not valid JSON") from exc
            if not isinstance(receipt, dict) or receipt.get("ok") is not True:
                raise RuntimeError("Telegram did not acknowledge the message")
            result = receipt.get("result")
            if (not isinstance(result, dict) or type(result.get("message_id")) is not int
                    or result["message_id"] <= 0):
                raise RuntimeError("Telegram did not provide a valid message ID")


def claim_delivery(db: Session, now: datetime | None = None) -> NotificationDelivery | None:
    now = now or utcnow()
    row = db.scalar(select(NotificationDelivery).where(NotificationDelivery.status == "pending", NotificationDelivery.next_attempt_at <= now, or_(NotificationDelivery.leased_until.is_(None), NotificationDelivery.leased_until < now)).order_by(NotificationDelivery.next_attempt_at).limit(1).with_for_update(skip_locked=True))
    if row:
        row.leased_until = now + timedelta(seconds=30)
        db.commit()
    return row


def _utc_aware(value: datetime | None) -> datetime | None:
    """Postgres stores timezone-aware timestamps; SQLite may discard tzinfo."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def deliver_one(db: Session, now: datetime | None = None) -> bool:
    now = now or utcnow()
    row = claim_delivery(db, now)
    if row is None:
        return False

    delivery_id = row.id
    claim_deadline = _utc_aware(row.leased_until)
    message = row.message
    channel = db.get(NotificationChannel, row.channel_id)
    failure = False
    try:
        if channel is None or not channel.confirmed:
            raise RuntimeError("Notification channel removed or inactive")
        await send_delivery(channel, message)
    except (httpx.HTTPError, RuntimeError, ValueError):
        failure = True

    try:
        # Reload from the database, not the identity map. Another worker may
        # have reclaimed the expired lease while the external send was in flight.
        locked = db.scalar(
            select(NotificationDelivery).where(NotificationDelivery.id == delivery_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (locked is None or locked.status != "pending"
                or _utc_aware(locked.leased_until) != claim_deadline):
            db.rollback()  # Never overwrite a successor worker's claim or outcome.
            return True

        if failure:
            locked.attempts += 1
            if locked.attempts >= 5:
                locked.status = "failed"
            else:
                locked.next_attempt_at = utcnow() + timedelta(
                    seconds=min(3600, 30 * (2 ** (locked.attempts - 1)))
                )
        else:
            locked.status = "sent"
            locked.sent_at = utcnow()
        locked.leased_until = None
        db.commit()
    except Exception:
        db.rollback()
        raise
    return True
