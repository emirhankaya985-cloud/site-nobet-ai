"""Bounded SMTP worker. Durable claims commit before external side effects."""
import os
import re
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from email.message import EmailMessage
from sqlalchemy import select, func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from .models import BusinessLead, MailClaim, NotificationChannel, BusinessRecipientGuard, utcnow
from .business import event
from .database import session_factory


def smtp_send(claim, env):
    msg = EmailMessage()
    msg['From'] = env['GMAIL_SENDER_ADDRESS']
    msg['To'] = claim.recipient
    msg['Subject'] = claim.subject
    msg['Message-ID'] = f'<{claim.id}@isletmepilot.local>'
    msg.set_content(claim.body)
    with smtplib.SMTP_SSL('smtp.gmail.com',465,context=ssl.create_default_context(),timeout=30) as smtp:
        smtp.login(env['GMAIL_SENDER_ADDRESS'], env['GMAIL_APP_PASSWORD'])
        refused = smtp.send_message(msg)
        if refused:
            raise RuntimeError('SMTP did not accept recipient')


def ensure_mail_ready(factory, env):
    """Confirm outbound mail can run without touching leads or sending messages."""
    if env.get('BUSINESS_AUTO_MAIL_ENABLED') != 'true':
        raise RuntimeError('Unified mail worker disabled')
    if not re.fullmatch(r'[^\s@\r\n]+@[^\s@\r\n]+\.[^\s@\r\n]+', env.get('GMAIL_SENDER_ADDRESS', '')) or not env.get('GMAIL_APP_PASSWORD'):
        raise RuntimeError('SMTP configuration incomplete')
    organization = env.get('BUSINESS_ORGANIZATION_ID')
    if not organization:
        raise RuntimeError('Owner organization required')
    if env.get('BUSINESS_HISTORY_RECONCILED') != 'true':
        raise RuntimeError('Existing mail history must be reconciled before activation')
    if env.get('LEGACY_MAIL_WORKFLOW_DISABLED') != 'true':
        raise RuntimeError('Legacy sender must be disabled before unified mail activation')
    with factory() as db:
        channel = db.scalar(select(NotificationChannel.id).where(
            NotificationChannel.organization_id == organization,
            NotificationChannel.kind == 'telegram',
            NotificationChannel.confirmed.is_(True)))
        if not channel:
            raise RuntimeError('Confirmed private Telegram channel required')


def reserve_recipient(db, org, recipient, origin, source_id=None):
    """Atomically reserve a normalized address in one shared PostgreSQL database.

    Both sender implementations must call this before SMTP; this cannot protect
    a legacy sender which still uses a separate database.
    """
    normalized = recipient.strip().casefold()
    if not re.fullmatch(r'[^\s@\r\n]+@[^\s@\r\n]+\.[^\s@\r\n]+', normalized):
        raise ValueError('Invalid recipient for shared guard')
    values = dict(recipient_normalized=normalized, organization_id=org,
                  origin=origin, source_id=source_id)
    dialect = db.get_bind().dialect.name
    if dialect == 'postgresql':
        statement = pg_insert(BusinessRecipientGuard).values(**values)
    elif dialect == 'sqlite':
        statement = sqlite_insert(BusinessRecipientGuard).values(**values)
    else:
        raise RuntimeError('Recipient guard requires PostgreSQL or isolated SQLite test')
    statement = statement.on_conflict_do_nothing(
        index_elements=[BusinessRecipientGuard.recipient_normalized])
    return db.execute(statement).rowcount == 1


def run_once(factory=None, env=None, sender=smtp_send, maximum=5):
    env = os.environ if env is None else env
    factory = factory or session_factory()
    ensure_mail_ready(factory, env)
    organization = env['BUSINESS_ORGANIZATION_ID']
    with factory() as db:
        stale = db.scalars(select(MailClaim).where(MailClaim.organization_id==organization,
            MailClaim.state=='sending',MailClaim.created_at < utcnow()-timedelta(minutes=5)).with_for_update(skip_locked=True)).all()
        for claim in stale:
            claim.state='uncertain'
            lead=db.get(BusinessLead,claim.lead_id)
            if lead:
                lead.delivery_state='uncertain'
            event(db,organization,claim.id,'İşletmePilot — Kesilen mail işlemi; sonuç belirsiz, otomatik tekrar kapalı.\nAlıcı: '+claim.recipient+'\nKonu: '+claim.subject+'\n\n'+claim.body,telegram_only=True)
        db.commit()
    result = {'accepted':0,'uncertain':0,'duplicate':0,'daily_limit_reached':0}
    # Day boundaries are calculated in Turkey, claims are compared as UTC timestamps.
    today = datetime.now(ZoneInfo('Europe/Istanbul')).date()
    midnight = datetime.combine(today, datetime.min.time(), ZoneInfo('Europe/Istanbul')).astimezone(timezone.utc)
    tomorrow = datetime.combine(today + timedelta(days=1), datetime.min.time(), ZoneInfo('Europe/Istanbul')).astimezone(timezone.utc)
    for _ in range(min(maximum,5)):
        with factory() as db:
            # Serialize quota checks and inserts across independent PostgreSQL runners.
            # This transaction-level advisory lock releases on commit, before SMTP.
            if db.get_bind().dialect.name == 'postgresql':
                db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:org))"),
                           {'org': 'isletmepilot:mail:' + organization})
            used = db.scalar(select(func.count(MailClaim.id)).where(
                MailClaim.organization_id == organization,
                MailClaim.created_at >= midnight, MailClaim.created_at < tomorrow)) or 0
            # Count uncertain and in-flight claims too: retries must not increase the quota.
            if used >= 5:
                result['daily_limit_reached'] = 1
                break
            channel = db.scalar(select(NotificationChannel.id).where(
                NotificationChannel.organization_id==organization,
                NotificationChannel.kind=='telegram',NotificationChannel.confirmed.is_(True)))
            if not channel:
                raise RuntimeError('Confirmed private Telegram channel required')
            row = db.scalar(select(BusinessLead).where(BusinessLead.organization_id==organization,
                BusinessLead.delivery_state=='not_sent',BusinessLead.email.is_not(None)).order_by(
                    BusinessLead.created_at).limit(1).with_for_update(skip_locked=True))
            if row is None:
                break
            if not row.email_source:
                row.delivery_state='unknown'
                db.commit()
                continue
            historic_claim = db.scalar(select(MailClaim.id).where(
                MailClaim.organization_id == organization,
                func.lower(func.trim(MailClaim.recipient)) == row.email).limit(1))
            prior = db.scalar(select(BusinessLead.id).where(
                BusinessLead.organization_id==organization, BusinessLead.id!=row.id,
                func.lower(func.trim(BusinessLead.email))==row.email,
                BusinessLead.delivery_state.in_(['accepted','sending','uncertain','rejected','deferred'])).limit(1))
            if prior or historic_claim or not reserve_recipient(
                    db, organization, row.email, 'unified', row.source_id):
                row.delivery_state='duplicate'
                db.commit()
                result['duplicate']+=1
                continue
            claim = MailClaim(organization_id=organization,lead_id=row.id,recipient=row.email,
                subject=f'{row.name[:100]} için yazılım çözümleri',
                body=f'Merhaba {row.name} ekibi,\n\nBen Emirhan Kaya. İşletmenizin web sitesi ve iş süreçleri için yazılım çözümleri geliştiriyorum. İhtiyaçlarınızı öğrenip uygun bir çalışma önermek isterim. Böyle bir çalışmayı değerlendirmek ister misiniz?\n\nTekrar iletişim istemiyorsanız yanıtınızda belirtmeniz yeterli.\n\nİyi çalışmalar,\nEmirhan Kaya')
            row.delivery_state='sending'
            db.add(claim)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                row=db.get(BusinessLead,row.id)
                if row and row.delivery_state=='not_sent':
                    row.delivery_state='duplicate'
                    db.commit()
                result['duplicate']+=1
                continue
            # Never release this claim after an ambiguous network outcome.
            state='accepted'
            try:
                sender(claim,env)
            except Exception:
                state='uncertain'
            claim.state=state
            row.delivery_state=state
            label='SMTP kabulü; gelen kutusu teslimi doğrulanmadı' if state=='accepted' else 'Sonuç belirsiz; otomatik tekrar kapalı'
            event(db,organization,claim.id,
                f'İşletmePilot — Mail sonucu\n{label}\nAlıcı: {claim.recipient}\nKonu: {claim.subject}\n\n{claim.body}',telegram_only=True)
            db.commit()
            result[state]+=1
    return result


if __name__ == '__main__':
    try:
        print(run_once())
    except Exception:
        raise RuntimeError('Unified mail worker failed; inspect private history before retry') from None
