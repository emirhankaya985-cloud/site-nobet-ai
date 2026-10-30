"""Bounded SMTP worker. Durable claims commit before external side effects."""
import os
import re
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from .models import BusinessLead, MailClaim, NotificationChannel, utcnow
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


def run_once(factory=None, env=None, sender=smtp_send, maximum=5):
    env = os.environ if env is None else env
    if env.get('BUSINESS_AUTO_MAIL_ENABLED') != 'true':
        raise RuntimeError('Unified mail worker disabled')
    if not re.fullmatch(r'[^\s@\r\n]+@[^\s@\r\n]+\.[^\s@\r\n]+',env.get('GMAIL_SENDER_ADDRESS','')) or not env.get('GMAIL_APP_PASSWORD'):
        raise RuntimeError('SMTP configuration incomplete')
    organization = env.get('BUSINESS_ORGANIZATION_ID')
    if not organization:
        raise RuntimeError('Owner organization required')
    if env.get('BUSINESS_HISTORY_RECONCILED') != 'true':
        raise RuntimeError('Existing mail history must be reconciled before activation')
    factory = factory or session_factory()
    with factory() as db:
        stale = db.scalars(select(MailClaim).where(MailClaim.organization_id==organization,
            MailClaim.state=='sending',MailClaim.created_at < utcnow()-timedelta(minutes=5)).with_for_update(skip_locked=True)).all()
        for claim in stale:
            claim.state='uncertain'
            lead=db.get(BusinessLead,claim.lead_id)
            if lead:
                lead.delivery_state='uncertain'
            event(db,organization,claim.id,'İşletmePilot — Kesilen mail işlemi; sonuç belirsiz, otomatik tekrar kapalı.\nAlıcı: '+claim.recipient+'\nKonu: '+claim.subject+'\n\n'+claim.body)
        db.commit()
    result = {'accepted':0,'uncertain':0,'duplicate':0}
    for _ in range(min(maximum,5)):
        with factory() as db:
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
            prior = db.scalar(select(BusinessLead.id).where(
                BusinessLead.organization_id==organization, BusinessLead.id!=row.id,
                BusinessLead.email==row.email, BusinessLead.delivery_state.in_(['accepted','sending','uncertain','rejected','deferred'])).limit(1))
            if prior:
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
                f'İşletmePilot — Mail sonucu\n{label}\nAlıcı: {claim.recipient}\nKonu: {claim.subject}\n\n{claim.body}')
            db.commit()
            result[state]+=1
    return result


if __name__ == '__main__':
    try:
        print(run_once())
    except Exception:
        raise RuntimeError('Unified mail worker failed; inspect private history before retry') from None
