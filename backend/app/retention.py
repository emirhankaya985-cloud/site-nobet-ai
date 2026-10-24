"""Retain detailed telemetry for a bounded window, while preserving incident history."""
from datetime import timedelta
from sqlalchemy import delete
from sqlalchemy.orm import Session
from .models import CheckResult, SSLCheck, NotificationDelivery, AuditLog, utcnow


def cleanup(db: Session):
    now = utcnow()
    # Detailed checks kept 90 days; audit logs and delivery records 180 days.
    db.execute(delete(CheckResult).where(CheckResult.created_at < now - timedelta(days=90)))
    db.execute(delete(SSLCheck).where(SSLCheck.checked_at < now - timedelta(days=90)))
    db.execute(delete(NotificationDelivery).where(NotificationDelivery.sent_at.is_not(None), NotificationDelivery.sent_at < now - timedelta(days=180)))
    db.execute(delete(AuditLog).where(AuditLog.created_at < now - timedelta(days=180)))
    db.commit()
