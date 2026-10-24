"""Deterministic outage state transitions, persisted transactionally."""
from dataclasses import dataclass
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Monitor, CheckResult, Incident, NotificationChannel, NotificationDelivery, utcnow
from .security import Probe


@dataclass(frozen=True)
class Transition:
    previous: str
    current: str
    event: str | None


def transition(status: str, successes: int, failures: int, healthy: bool) -> tuple[str, int, int, str | None]:
    if status == "PAUSED":
        return status, successes, failures, None
    if healthy:
        successes += 1
        failures = 0
        if status in ("DOWN", "RECOVERING"):
            if successes >= 2:
                return "UP", successes, failures, "recovered"
            return "RECOVERING", successes, failures, None
        return "UP", successes, failures, None
    failures += 1
    successes = 0
    if status in ("DOWN", "RECOVERING"):
        return "DOWN", successes, failures, None
    if failures >= 2:
        return "DOWN", successes, failures, "down"
    return "SUSPECTED_DOWN", successes, failures, None


def enqueue_event(db: Session, monitor: Monitor, incident: Incident, kind: str, now: datetime):
    channels = db.scalars(select(NotificationChannel).where(NotificationChannel.organization_id == monitor.organization_id, NotificationChannel.confirmed.is_(True))).all()
    icon = "🚨" if kind == "down" else "✅"
    label = "ERİŞİLEMİYOR" if kind == "down" else "SİTE DÜZELDİ"
    msg = f"{icon} SİTENÖBET AI — {label}\n🌐 {monitor.name}\n🔗 {monitor.url}\n🕒 {now.isoformat()}\n📍 Durum: {monitor.status}"
    for channel in channels:
        db.add(NotificationDelivery(channel_id=channel.id, incident_id=incident.id, event_key=f"incident:{incident.id}:{kind}:{channel.id}", message=msg))


def apply_probe(db: Session, monitor: Monitor, probe: Probe, *, now: datetime | None = None) -> Transition:
    now = now or utcnow()
    previous = monitor.status
    if monitor.paused:
        return Transition(previous, previous, None)
    state, successes, failures, event = transition(monitor.status, monitor.consecutive_successes, monitor.consecutive_failures, probe.is_up)
    monitor.status = state
    monitor.consecutive_successes = successes
    monitor.consecutive_failures = failures
    monitor.last_checked_at = now
    monitor.last_status_code = probe.status_code
    monitor.last_response_ms = probe.response_ms
    monitor.last_error = probe.error_kind
    if probe.is_up:
        monitor.last_success_at = now
    db.add(CheckResult(monitor_id=monitor.id, created_at=now, is_up=probe.is_up, state=state, status_code=probe.status_code, response_ms=probe.response_ms, error_kind=probe.error_kind))
    if event == "down":
        active = db.scalar(select(Incident).where(Incident.monitor_id == monitor.id, Incident.closed_at.is_(None)))
        if active is None:
            active = Incident(monitor_id=monitor.id, opened_at=now, reason=probe.error_kind or f"HTTP {probe.status_code}")
            db.add(active)
            db.flush()
            enqueue_event(db, monitor, active, "down", now)
    elif event == "recovered":
        active = db.scalar(select(Incident).where(Incident.monitor_id == monitor.id, Incident.closed_at.is_(None)))
        if active is not None:
            active.closed_at = now
            active.closed_reason = "recovered"
            enqueue_event(db, monitor, active, "recovered", now)
    return Transition(previous, monitor.status, event)
