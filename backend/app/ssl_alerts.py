"""Send once-per-certificate-and-threshold alerts (not per periodic probe)."""
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Monitor, NotificationChannel, NotificationDelivery, utcnow


def process_ssl_result(db: Session, monitor: Monitor, expires_at: datetime | None, error: str | None, *, now: datetime | None = None):
    now = now or utcnow()
    if not monitor.url.startswith("https://"):
        return
    threshold = None
    if error:
        threshold = "tls-error:" + error
    elif expires_at:
        remaining = (expires_at - now).total_seconds() / 86400
        if remaining <= 0:
            threshold = "expired"
        else:
            for days in (1, 7, 14, 30):
                if remaining <= days:
                    threshold = f"{days}d"
                    break
    if not threshold:
        return
    # Expiration timestamp differentiates renewed certificates. TLS error per monitor is deduplicated.
    identifier = expires_at.isoformat() if expires_at else "tls-invalid"
    channels = db.scalars(select(NotificationChannel).where(NotificationChannel.organization_id == monitor.organization_id, NotificationChannel.confirmed.is_(True))).all()
    import hashlib
    cert_key = hashlib.sha256((monitor.id + identifier).encode()).hexdigest()[:24]
    for channel in channels:
        key = f"ssl:{cert_key}:{threshold}:{channel.id}"
        # Avoid IntegrityError when a previous alert for this threshold was already queued.
        if db.scalar(select(NotificationDelivery.id).where(NotificationDelivery.event_key == key)):
            continue
        text = f"🔐 SiteNöbet AI — SSL uyarısı\n🌐 {monitor.name}\n⚠️ {threshold}\n📅 Bitiş: {expires_at.isoformat() if expires_at else 'TLS doğrulama başarısız'}"
        db.add(NotificationDelivery(channel_id=channel.id, event_key=key, message=text))
