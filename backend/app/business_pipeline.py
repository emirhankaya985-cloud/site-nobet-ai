"""Single-project research -> CRM -> mail -> Telegram + SiteNöbet batch."""
import asyncio
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from sqlalchemy.exc import IntegrityError
from sqlalchemy import select
from .business import import_lead, ImportLead, event
from .business_mail import run_once as mail_once
from .database import session_factory
from .models import Membership, User, BusinessBatch, MailClaim
from .notifications import deliver_one
from .research import get_osm, lead_from_osm, bbox_parse, DEFAULT_BBOX
from .worker import run_once as monitor_once


async def drain(factory):
    for _ in range(50):
        with factory() as db:
            if not await deliver_one(db):
                break


async def run(env=None, factory=None, researcher=get_osm, mailer=mail_once, monitor=monitor_once):
    env = os.environ if env is None else env
    if env.get('BUSINESS_PIPELINE_ENABLED') != 'true':
        raise RuntimeError('Unified pipeline disabled')
    # Explicit fail-closed mode: do not research, import, drain notifications, or
    # create a daily batch when SMTP is disabled. No pretend mail-free run.
    if env.get('BUSINESS_AUTO_MAIL_ENABLED') != 'true':
        raise RuntimeError('Unified mail disabled; no daily batch or side effects created')
    if env.get('BUSINESS_HISTORY_RECONCILED') != 'true' or env.get('LEGACY_MAIL_WORKFLOW_DISABLED') != 'true':
        raise RuntimeError('Reconcile history and disable legacy sender before unified activation')
    org = env.get('BUSINESS_ORGANIZATION_ID')
    factory = factory or session_factory()
    with factory() as db:
        owner = db.scalar(select(User).join(Membership, Membership.user_id==User.id).where(
            Membership.organization_id==org,Membership.role=='owner'))
        if not owner:
            raise RuntimeError('Owner organization not found')
        owner_id = owner.id
    with factory() as db:
        batch=BusinessBatch(organization_id=org,day=datetime.now(ZoneInfo('Europe/Istanbul')).date().isoformat())
        db.add(batch)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            await drain(factory)
            return {'skipped_existing_daily_batch':1}
        batch_id=batch.id
    try:
        # Pending Telegram notifications are independent of the research provider.
        await drain(factory)
        rows=researcher(bbox_parse(env.get('SCAN_BBOX') or DEFAULT_BBOX))
        counts={'imported':0,'invalid':0}
        for raw in rows[:200]:
            lead=lead_from_osm(raw)
            if not lead:
                continue
            payload={'id':lead['id'],'name':lead['name'],'website':lead['website'] or None,
                     'email':lead['email'] or None,'email_source':'OSM business contact tag' if lead['email'] else None,
                     'delivery_state':'not_sent'}
            with factory() as db:
                owner=db.get(User,owner_id)
                from fastapi import HTTPException
                try:
                    result=import_lead(org,ImportLead(**payload),owner,db)
                    counts['imported']+=int(result['created'])
                except HTTPException as exc:
                    if exc.status_code!=422:
                        raise
                    counts['invalid']+=1
        # MailClaim is durably committed inside mailer before any real SMTP call.
        # Mark this stage only after the mailer has returned; a preflight failure
        # must never masquerade as a started SMTP attempt.
        counts.update(mailer(factory,env))
        with factory() as db:
            batch=db.get(BusinessBatch,batch_id)
            batch.state='mail_started'
            db.commit()
        with factory() as db:
            event(db,org,batch_id+'-summary','İşletmePilot — Günlük tarama özeti\n'+', '.join(f'{key}={value}' for key,value in counts.items())+'\nSMTP kabulü gelen kutusu teslimi değildir.')
            db.commit()
        await drain(factory)
        await monitor(max_checks=3,max_notifications=50)
        with factory() as db:
            batch=db.get(BusinessBatch,batch_id)
            if counts.get('accepted',0) or counts.get('uncertain',0):
                batch.state='completed'
            else:
                db.delete(batch)
            db.commit()
        return counts
    except Exception:
        with factory() as db:
            batch=db.get(BusinessBatch,batch_id)
            if batch and batch.state in ('running', 'mail_started'):
                # If the sender crashed after persisting a claim, retain the
                # daily barrier. Sending or uncertain claims must never be erased.
                today = datetime.now(ZoneInfo('Europe/Istanbul')).date()
                cutoff = datetime.combine(today, datetime.min.time(), ZoneInfo('Europe/Istanbul'))
                claim = db.scalar(select(MailClaim.id).where(
                    MailClaim.organization_id == org,
                    MailClaim.created_at >= cutoff).limit(1))
                if claim is None:
                    db.delete(batch)  # No mail attempt was persisted.
                    db.commit()
        raise



if __name__=='__main__':
    try:
        print(asyncio.run(run()))
    except Exception:
        raise RuntimeError('Unified pipeline failed; private details redacted') from None
