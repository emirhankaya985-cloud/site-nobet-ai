"""Time-based availability, with unknown/unobserved seconds excluded."""
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import CheckResult, Monitor, utcnow


def aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def uptime_summary(db: Session, monitor: Monitor, hours: int = 24):
    end = utcnow()
    start = end - timedelta(hours=hours)
    # Include one result before the window to determine state at window start.
    before = db.scalar(select(CheckResult).where(CheckResult.monitor_id == monitor.id, CheckResult.created_at < start).order_by(CheckResult.created_at.desc()).limit(1))
    rows = db.scalars(select(CheckResult).where(CheckResult.monitor_id == monitor.id, CheckResult.created_at >= start, CheckResult.created_at <= end).order_by(CheckResult.created_at)).all()
    checks = ([before] if before else []) + list(rows)
    measured = healthy = down = 0.0
    max_gap = monitor.interval_seconds * 2
    for i, check in enumerate(checks):
        at = aware(check.created_at)
        end_at = aware(checks[i+1].created_at) if i+1 < len(checks) else end
        # Gaps > 2 intervals are considered unobserved; avoid overstatement.
        seconds = max(0, (min(end, end_at, at + timedelta(seconds=max_gap)) - max(start, at)).total_seconds())
        if check.state == "UP":
            healthy += seconds
            measured += seconds
        elif check.state == "DOWN":
            down += seconds
            measured += seconds
    period = hours * 3600.0
    return {"uptime_percent": round(healthy / measured * 100, 3) if measured else None, "observed_seconds": round(measured), "unobserved_seconds": round(max(0, period - measured)), "confirmed_down_seconds": round(down), "observation_method": "State-hold, capped at 2 check intervals; suspected/recovering/unknown excluded"}
