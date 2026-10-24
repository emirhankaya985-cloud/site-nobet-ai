from datetime import datetime, timedelta
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


def claim_delivery(db: Session, now: datetime | None = None) -> NotificationDelivery | None:
    now = now or utcnow()
    row = db.scalar(select(NotificationDelivery).where(NotificationDelivery.status == "pending", NotificationDelivery.next_attempt_at <= now, or_(NotificationDelivery.leased_until.is_(None), NotificationDelivery.leased_until < now)).order_by(NotificationDelivery.next_attempt_at).limit(1).with_for_update(skip_locked=True))
    if row:
        row.leased_until = now + timedelta(seconds=30)
        db.commit()
    return row


async def deliver_one(db: Session, now: datetime | None = None) -> bool:
    now = now or utcnow()
    row = claim_delivery(db, now)
    if row is None:
        return False
    channel = db.get(NotificationChannel, row.channel_id)
    try:
        if channel is None or not channel.confirmed:
            raise RuntimeError("Notification channel removed or inactive")
        await send_delivery(channel, row.message)
        row.status = "sent"
        row.sent_at = utcnow()
    except (httpx.HTTPError, RuntimeError, ValueError):
        row.attempts += 1
        if row.attempts >= 5:
            row.status = "failed"
        else:
            row.next_attempt_at = utcnow() + timedelta(seconds=min(3600, 30 * (2 ** (row.attempts - 1))))
    finally:
        row.leased_until = None
        db.commit()
    return True
