"""SiteNöbet AI REST API — multi-tenant, bearer-authenticated MVP."""
from datetime import timedelta
import hashlib
import hmac
import re
import secrets
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .auth import current_user, hash_password, make_token, org_membership, verify_password
from .config import get_settings
from .database import db_session
from .models import (AuditLog, CheckResult, Incident, Membership, Monitor, NotificationChannel,
                     Organization, RateLimitBucket, SSLCheck, Subscription, TelegramLinkCode, User, WorkerHeartbeat, utcnow)
from .security import safe_url, UnsafeTarget
from .uptime import uptime_summary

app = FastAPI(title="SiteNöbet AI", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_credentials=False, allow_methods=["GET", "POST", "PATCH"], allow_headers=["Authorization", "Content-Type"])


class Register(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=12, max_length=200)
    organization_name: str = Field(min_length=2, max_length=150)

    @field_validator("email")
    @classmethod
    def email_valid(cls, v):
        v = v.strip().lower()
        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", v):
            raise ValueError("Valid email required")
        return v


class Login(BaseModel):
    email: str
    password: str


class CreateMonitor(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    url: str = Field(min_length=8, max_length=2048)
    interval_seconds: int = 300


class PauseUpdate(BaseModel):
    paused: bool


def membership_of(db: Session, user: User, org_id: str, write=False):
    return org_membership(user, org_id, db, write=write)


def rate_limit(db: Session, subject: str, max_hits: int, period: int):
    """Persisted throttling; no Redis required for a first release."""
    now = utcnow()
    key = hashlib.sha256((get_settings().session_secret + subject).encode()).hexdigest()
    bucket = db.scalar(select(RateLimitBucket).where(RateLimitBucket.key == key).with_for_update())
    if bucket is None:
        bucket = RateLimitBucket(key=key, window_started=now, count=0)
        db.add(bucket)
    else:
        started = bucket.window_started
        if started.tzinfo is None:
            started = started.replace(tzinfo=__import__("datetime").timezone.utc)
        if (now - started).total_seconds() >= period:
            bucket.count = 0
            bucket.window_started = now
    bucket.count += 1
    db.commit()
    if bucket.count > max_hits:
        raise HTTPException(429, "Rate limit exceeded")


def audit(db: Session, user_id: str | None, org_id: str | None, action: str):
    db.add(AuditLog(user_id=user_id, organization_id=org_id, action=action))


def get_monitor(db: Session, user: User, org_id: str, monitor_id: str, write=False) -> Monitor:
    membership_of(db, user, org_id, write)
    monitor = db.scalar(select(Monitor).where(Monitor.id == monitor_id, Monitor.organization_id == org_id))
    if monitor is None:
        raise HTTPException(404, "Resource not found")
    return monitor


def monitor_json(m: Monitor):
    return {"id":m.id, "organization_id":m.organization_id, "name":m.name, "url":m.url, "status": "PAUSED" if m.paused else m.status,
            "paused":m.paused, "interval_seconds":m.interval_seconds, "last_checked_at":m.last_checked_at, "last_success_at":m.last_success_at,
            "last_status_code":m.last_status_code, "last_response_ms":m.last_response_ms, "last_error":m.last_error}


@app.get("/health")
def health(db: Session = Depends(db_session)):
    # Render should not mark an API healthy when PostgreSQL or migrations are down.
    try:
        db.scalar(select(WorkerHeartbeat.worker_name).limit(1))
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Database unavailable or migrations missing") from exc
    return {"status": "ok", "service": "api", "database": "ok"}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health/worker")
def worker_health(db: Session = Depends(db_session)):
    row = db.get(WorkerHeartbeat, "main")
    if not row:
        raise HTTPException(503, "Worker has not reported a heartbeat")
    last = row.last_seen_at.replace(tzinfo=row.last_seen_at.tzinfo or __import__("datetime").timezone.utc)
    threshold_seconds = 32 * 60 if get_settings().scheduler_mode == "cron" else 60
    if (utcnow() - last).total_seconds() > threshold_seconds:
        raise HTTPException(503, "Worker heartbeat is stale")
    return {"status":"ok", "last_seen_at":row.last_seen_at}


@app.post("/auth/register", status_code=201)
def register(data: Register, request: Request, db: Session = Depends(db_session)):
    rate_limit(db, f"register:{request.client.host if request.client else 'unknown'}", 5, 3600)
    if db.scalar(select(User.id).where(User.email == data.email)):
        raise HTTPException(409, "Account already exists")
    user = User(email=data.email, password_hash=hash_password(data.password))
    org = Organization(name=data.organization_name)
    db.add_all([user, org])
    db.flush()
    db.add_all([Membership(user_id=user.id, organization_id=org.id, role="owner"), Subscription(organization_id=org.id, plan="starter")])
    audit(db, user.id, org.id, "register")
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Account already exists")
    return {"access_token": make_token(user.id), "token_type": "bearer", "organization_id": org.id}


@app.post("/auth/login")
def login(data: Login, request: Request, db: Session = Depends(db_session)):
    rate_limit(db, f"login:{request.client.host if request.client else 'unknown'}", 15, 900)
    user = db.scalar(select(User).where(User.email == data.email.strip().lower()))
    if user is None or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    membership = db.scalar(select(Membership).where(Membership.user_id == user.id))
    return {"access_token": make_token(user.id), "token_type": "bearer", "organization_id": membership.organization_id if membership else None}


@app.get("/auth/me")
def me(user: User = Depends(current_user), db: Session = Depends(db_session)):
    memberships = db.scalars(select(Membership).where(Membership.user_id == user.id)).all()
    return {"id": user.id, "email": user.email, "organizations": [{"id": m.organization_id, "role": m.role} for m in memberships]}


@app.get("/organizations/{org_id}/monitors")
def list_monitors(org_id: str, user: User = Depends(current_user), db: Session = Depends(db_session)):
    membership_of(db, user, org_id)
    return [monitor_json(m) for m in db.scalars(select(Monitor).where(Monitor.organization_id == org_id).order_by(Monitor.created_at.desc())).all()]


@app.post("/organizations/{org_id}/monitors", status_code=201)
def create_monitor(org_id: str, data: CreateMonitor, user: User = Depends(current_user), db: Session = Depends(db_session)):
    membership_of(db, user, org_id, write=True)
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(404, "Organization not found")
    if get_settings().scheduler_mode == "cron":
        # The 0-TL scheduled runner is deliberately slower than an always-on worker.
        limit, allowed = (3, [900])
    else:
        limit, allowed = {"starter": (3, [300]), "pro": (20, [60, 180, 300]), "agency": (100, [60, 180, 300])}.get(org.plan, (3, [300]))
    if (db.scalar(select(func.count(Monitor.id)).where(Monitor.organization_id == org_id)) or 0) >= limit:
        raise HTTPException(403, "Plan monitor limit reached")
    if data.interval_seconds not in allowed:
        raise HTTPException(400, "Check interval not allowed by your plan")
    try:
        url = safe_url(data.url)
    except UnsafeTarget as exc:
        raise HTTPException(400, str(exc))
    m = Monitor(organization_id=org_id, name=data.name.strip(), url=url, interval_seconds=data.interval_seconds)
    db.add(m)
    audit(db, user.id, org_id, "monitor.create")
    db.commit()
    return monitor_json(m)


@app.get("/organizations/{org_id}/monitors/{monitor_id}")
def get_monitor_detail(org_id: str, monitor_id: str, user: User = Depends(current_user), db: Session = Depends(db_session)):
    m = get_monitor(db, user, org_id, monitor_id)
    summary = uptime_summary(db, m)
    recent = db.scalars(select(CheckResult).where(CheckResult.monitor_id == m.id).order_by(CheckResult.created_at.desc()).limit(100)).all()
    incidents = db.scalars(select(Incident).where(Incident.monitor_id == m.id).order_by(Incident.opened_at.desc()).limit(30)).all()
    ssl_result = db.scalar(select(SSLCheck).where(SSLCheck.monitor_id == m.id).order_by(SSLCheck.checked_at.desc()).limit(1))
    return {**monitor_json(m), "uptime":summary, "checks": [{"at":c.created_at,"status_code":c.status_code,"response_ms":c.response_ms,"state":c.state,"error":c.error_kind} for c in recent],
            "incidents": [{"id":i.id,"opened_at":i.opened_at,"closed_at":i.closed_at,"closed_reason":i.closed_reason,"reason":i.reason} for i in incidents],
            "ssl": {"expires_at":ssl_result.expires_at,"checked_at":ssl_result.checked_at,"error":ssl_result.error} if ssl_result else None}


@app.patch("/organizations/{org_id}/monitors/{monitor_id}")
def pause_monitor(org_id: str, monitor_id: str, data: PauseUpdate, user: User = Depends(current_user), db: Session = Depends(db_session)):
    m = get_monitor(db, user, org_id, monitor_id, write=True)
    if m.paused != data.paused:
        db.add(CheckResult(monitor_id=m.id, created_at=utcnow(), is_up=False, state="UNKNOWN", error_kind="PAUSED" if data.paused else "RESUMED"))
    if data.paused:
        active = db.scalar(select(Incident).where(Incident.monitor_id == m.id, Incident.closed_at.is_(None)))
        if active:
            active.closed_at = utcnow()
            active.closed_reason = "paused"
    m.paused = data.paused
    if not data.paused:
        m.status = "UNKNOWN"  # pause creates an unobserved gap
        m.consecutive_failures = m.consecutive_successes = 0
        m.next_check_at = utcnow()
    audit(db, user.id, org_id, "monitor.pause" if data.paused else "monitor.resume")
    db.commit()
    return monitor_json(m)


@app.get("/organizations/{org_id}/dashboard")
def dashboard(org_id: str, user: User = Depends(current_user), db: Session = Depends(db_session)):
    membership_of(db, user, org_id)
    items = db.scalars(select(Monitor).where(Monitor.organization_id == org_id)).all()
    statuses = {"up": 0, "down": 0, "unknown": 0}
    for item in items:
        key = "up" if item.status == "UP" and not item.paused else "down" if item.status == "DOWN" and not item.paused else "unknown"
        statuses[key] += 1
    percents = [v["uptime_percent"] for v in (uptime_summary(db, m) for m in items) if v["uptime_percent"] is not None]
    return {"total": len(items), **statuses, "average_uptime_percent": round(sum(percents)/len(percents), 3) if percents else None,
            "last_24h_incidents": db.scalar(select(func.count(Incident.id)).join(Monitor, Monitor.id == Incident.monitor_id).where(Monitor.organization_id == org_id, Incident.opened_at >= utcnow()-timedelta(days=1)))}


@app.get("/organizations/{org_id}/notifications")
def list_channels(org_id: str, user: User = Depends(current_user), db: Session = Depends(db_session)):
    membership_of(db, user, org_id, write=True)
    items = db.scalars(select(NotificationChannel).where(NotificationChannel.organization_id == org_id)).all()
    return [{"id": c.id, "kind":c.kind, "confirmed":c.confirmed, "topic":c.destination if c.kind=="ntfy" else None} for c in items]


@app.post("/organizations/{org_id}/notifications/ntfy", status_code=201)
def create_ntfy(org_id: str, user: User = Depends(current_user), db: Session = Depends(db_session)):
    membership_of(db, user, org_id, write=True)
    count = db.scalar(select(func.count(NotificationChannel.id)).where(NotificationChannel.organization_id == org_id))
    if (count or 0) >= 5:
        raise HTTPException(403, "Channel limit reached")
    topic = "sitenobet-" + secrets.token_urlsafe(32)
    c = NotificationChannel(organization_id=org_id, kind="ntfy", destination=topic, confirmed=True)
    db.add(c)
    audit(db, user.id, org_id, "channel.create.ntfy")
    db.commit()
    return {"id":c.id, "kind":"ntfy", "topic":topic, "subscription_url":f"{get_settings().ntfy_base_url.rstrip('/')}/{topic}"}


@app.post("/organizations/{org_id}/notifications/telegram/link-code")
def telegram_link_code(org_id: str, user: User = Depends(current_user), db: Session = Depends(db_session)):
    membership_of(db, user, org_id, write=True)
    if not get_settings().telegram_bot_token or not get_settings().telegram_webhook_secret:
        raise HTTPException(503, "Telegram integration not configured")
    token = secrets.token_urlsafe(24)
    db.add(TelegramLinkCode(organization_id=org_id, code_hash=hashlib.sha256(token.encode()).hexdigest(), expires_at=utcnow() + timedelta(minutes=10)))
    audit(db, user.id, org_id, "channel.telegram.link_requested")
    db.commit()
    return {"instruction": "Send /start followed by the code to the configured Telegram bot within 10 minutes", "code":token}


@app.post("/integrations/telegram/webhook")
def telegram_webhook(payload: dict, x_telegram_bot_api_secret_token: str | None = Header(default=None), db: Session = Depends(db_session)):
    secret = get_settings().telegram_webhook_secret
    if not secret or not x_telegram_bot_api_secret_token or not hmac.compare_digest(secret, x_telegram_bot_api_secret_token):
        raise HTTPException(403, "Forbidden")
    msg = payload.get("message") or {}
    chat = msg.get("chat") or {}
    parts = str(msg.get("text", "")).split()
    if chat.get("type") != "private" or len(parts) != 2 or not parts[0].startswith("/start"):
        return {"ok":True}
    digest = hashlib.sha256(parts[1].encode()).hexdigest()
    now = utcnow()
    item = db.scalar(select(TelegramLinkCode).where(TelegramLinkCode.code_hash == digest, TelegramLinkCode.redeemed_at.is_(None)).with_for_update())
    if item:
        expires_at = item.expires_at.replace(tzinfo=item.expires_at.tzinfo or __import__('datetime').timezone.utc)
        if expires_at > now and isinstance(chat.get("id"), int):
            item.redeemed_at = now
            db.add(NotificationChannel(organization_id=item.organization_id, kind="telegram", destination=str(chat["id"]), confirmed=True))
            db.commit()
    return {"ok": True}


@app.get("/organizations/{org_id}/reports")
def reports(org_id: str, period_days: int = 1, user: User = Depends(current_user), db: Session = Depends(db_session)):
    membership_of(db, user, org_id)
    if period_days not in (1, 7):
        raise HTTPException(400, "Only 1-day and 7-day periods are supported")
    monitors = db.scalars(select(Monitor).where(Monitor.organization_id == org_id)).all()
    metrics = []
    for monitor in monitors:
        metrics.append({"monitor_id":monitor.id, "name":monitor.name, **uptime_summary(db, monitor, hours=period_days*24)})
    observed = sum(m["observed_seconds"] for m in metrics)
    down = sum(m["confirmed_down_seconds"] for m in metrics)
    start = utcnow() - timedelta(days=period_days)
    outages = db.scalar(select(func.count(Incident.id)).join(Monitor, Monitor.id == Incident.monitor_id).where(Monitor.organization_id == org_id, Incident.opened_at >= start))
    return {"period_days":period_days, "monitor_count":len(monitors), "incidents":outages,
            "uptime_percent":round((observed-down)/observed*100,3) if observed else None,
            "observed_seconds":observed, "unobserved_seconds":sum(m["unobserved_seconds"] for m in metrics),
            "confirmed_down_seconds":down, "monitors":metrics}

# Four-module integration shares the existing account and organization boundary.
from .business import router as business_router  # noqa: E402
app.include_router(business_router)
