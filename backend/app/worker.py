"""Run separately from FastAPI. Never use GitHub Actions as uptime scheduler."""
import asyncio
import logging
from datetime import timedelta, timezone
from sqlalchemy import select, or_
from sqlalchemy.orm import Session
from .database import session_factory
from .models import Monitor, SSLCheck, WorkerHeartbeat, utcnow
from .security import probe_http
from .monitoring import apply_probe
from .notifications import deliver_one
from .ssl_checks import check_ssl
from .ssl_alerts import process_ssl_result
from .retention import cleanup

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("sitenobet.worker")


def claim_monitor(db: Session) -> Monitor | None:
    now = utcnow()
    monitor = db.scalar(select(Monitor).where(Monitor.paused.is_(False), Monitor.next_check_at <= now, or_(Monitor.leased_until.is_(None), Monitor.leased_until < now)).order_by(Monitor.next_check_at).limit(1).with_for_update(skip_locked=True))
    if monitor:
        monitor.leased_until = now + timedelta(seconds=45)
        monitor.next_check_at = now + timedelta(seconds=monitor.interval_seconds)
        db.commit()
    return monitor


async def check_one() -> bool:
    with session_factory()() as db:
        monitor = claim_monitor(db)
        if monitor is None:
            return False
        # The timestamp is a claim token: if another worker reclaims the lease,
        # discard this stale result instead of overwriting the new owner.
        claimed_lease = monitor.leased_until
        if claimed_lease and claimed_lease.tzinfo is None:
            claimed_lease = claimed_lease.replace(tzinfo=timezone.utc)
        probe = await probe_http(monitor.url)
        try:
            # No competing update to monitor state after lease: lock the row.
            locked = db.scalar(select(Monitor).where(Monitor.id == monitor.id).with_for_update().execution_options(populate_existing=True))
            current_lease = locked.leased_until if locked else None
            if current_lease and current_lease.tzinfo is None:
                current_lease = current_lease.replace(tzinfo=timezone.utc)
            if not locked or locked.paused or current_lease != claimed_lease:
                db.rollback()
                log.warning("probe discarded after lease change monitor=%s", monitor.id)
                return True
            outcome = apply_probe(db, locked, probe)
            locked.leased_until = None
            db.commit()
            log.info("probe complete monitor=%s state=%s event=%s", monitor.id, outcome.current, outcome.event)
        except Exception:
            db.rollback()
            log.exception("monitor probe persistence failure monitor=%s", monitor.id)
            raise
        if monitor.url.startswith("https://"):
            last_ssl = db.scalar(select(SSLCheck).where(SSLCheck.monitor_id == monitor.id).order_by(SSLCheck.checked_at.desc()).limit(1))
            if last_ssl is None or (utcnow() - last_ssl.checked_at.replace(tzinfo=last_ssl.checked_at.tzinfo or __import__('datetime').timezone.utc)).total_seconds() >= 86400:
                expires_at, error = await check_ssl(monitor.url)
                db.add(SSLCheck(monitor_id=monitor.id, expires_at=expires_at, error=error))
                process_ssl_result(db, monitor, expires_at, error)
                db.commit()
        return True


def heartbeat(db: Session):
    now = utcnow()
    row = db.get(WorkerHeartbeat, "main")
    if row is None:
        db.add(WorkerHeartbeat(worker_name="main", last_seen_at=now))
    else:
        row.last_seen_at = now
    db.commit()


async def main():
    last_cleanup = None
    while True:
        processed = False
        try:
            with session_factory()() as db:
                heartbeat(db)
                if last_cleanup is None or (utcnow() - last_cleanup).total_seconds() > 86400:
                    cleanup(db)
                    last_cleanup = utcnow()
            processed = await check_one() or processed
            with session_factory()() as db:
                processed = await deliver_one(db) or processed
        except Exception:
            log.exception("worker loop failure")
        await asyncio.sleep(1 if processed else 5)


if __name__ == "__main__":
    asyncio.run(main())
