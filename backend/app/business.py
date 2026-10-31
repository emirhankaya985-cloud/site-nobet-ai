"""Shared CRM/review API. Imports never send outreach or publish Google replies."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .auth import current_user, org_membership
from .database import db_session
from .lead_import import parse_import
from .review_analysis import RuleBasedProvider
from .leadpilot_intent import rule_intent
from .models import BusinessLead, ReviewDraft, User, NotificationChannel, NotificationDelivery, Monitor, MailClaim

router = APIRouter(prefix='/organizations/{org_id}/business', tags=['İşletmePilot'])


class ImportLead(BaseModel):
    id: str
    name: str
    website: str | None = None
    email: str | None = None
    email_source: str | None = None
    delivery_state: str = 'unknown'
    model_config = {'extra':'forbid'}


class ImportReview(BaseModel):
    source_id: str = Field(min_length=1, max_length=200)
    review_text: str = Field(min_length=1, max_length=5000)
    stars: int = Field(default=3, ge=1, le=5)
    model_config = {'extra':'forbid'}


def event(db, org_id, key, message, *, telegram_only=False):
    # Full email text must never leak to ntfy or another non-private channel.
    query = select(NotificationChannel).where(
        NotificationChannel.organization_id == org_id,
        NotificationChannel.confirmed.is_(True))
    if telegram_only:
        query = query.where(NotificationChannel.kind == 'telegram')
    channels = db.scalars(query).all()
    for channel in channels:
        db.add(NotificationDelivery(channel_id=channel.id,
            event_key=f'business:{key}:{channel.id}', message=message))


def lead_json(row):
    return {k:getattr(row,k) for k in ('id','source_id','name','website','email','email_source','delivery_state')}


@router.post('/leads/import')
def import_lead(org_id: str, data: ImportLead, user: User = Depends(current_user), db: Session = Depends(db_session)):
    org_membership(user, org_id, db, write=True)
    try:
        record = parse_import(data.model_dump(), org_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    existing = db.scalar(select(BusinessLead).where(BusinessLead.organization_id == org_id,
                                                  BusinessLead.source_id == record.source_id))
    if existing:
        # Existing immutable history wins over an incoming retry or stale snapshot.
        return {'created':False, 'lead':lead_json(existing)}
    row = BusinessLead(organization_id=org_id, source_id=record.source_id, name=record.name,
        website=record.website,email=record.email,email_source=record.email_source,
        delivery_state=record.delivery_state)
    db.add(row)
    try:
        db.flush()
        event(db,org_id,row.id,'İşletmePilot — CRM adayı kaydedildi: '+row.name+'\nMail durumu: '+row.delivery_state)
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(BusinessLead).where(BusinessLead.organization_id == org_id,
                                                       BusinessLead.source_id == record.source_id))
        if existing is None:
            raise HTTPException(409,'Import conflict; retry safely') from None
        return {'created':False,'lead':lead_json(existing)}
    return {'created':True,'lead':lead_json(row)}


@router.get('/leads')
def list_leads(org_id: str, user: User = Depends(current_user), db: Session = Depends(db_session)):
    org_membership(user,org_id,db)
    return [lead_json(row) for row in db.scalars(select(BusinessLead).where(
        BusinessLead.organization_id == org_id).order_by(BusinessLead.created_at.desc()).limit(100))]


@router.post('/reviews/import')
def import_review(org_id: str, data: ImportReview, user: User = Depends(current_user), db: Session = Depends(db_session)):
    org_membership(user,org_id,db,write=True)
    existing = db.scalar(select(ReviewDraft).where(ReviewDraft.organization_id == org_id,
                                                 ReviewDraft.source_id == data.source_id))
    if existing:
        return {'id':existing.id,'status':existing.status,'reply_text':existing.reply_text,'created':False}
    # Deterministic draft with no invented commitments, discounts or facts.
    analysis = RuleBasedProvider().analyze(data.review_text, data.stars)
    reply = analysis.reply_draft
    row = ReviewDraft(organization_id=org_id,source_id=data.source_id,
                      review_text=data.review_text,reply_text=reply)
    db.add(row)
    try:
        db.flush()
        event(db,org_id,row.id,'İşletmePilot — Yeni yorum yanıt taslağı hazır. İnsan incelemesi bekliyor.')
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,'Review already imported; reload existing draft') from None
    return {'id':row.id,'status':row.status,'reply_text':reply,'created':True}


@router.get('/reviews')
def reviews(org_id: str, user: User = Depends(current_user), db: Session = Depends(db_session)):
    org_membership(user,org_id,db)
    return [{'id':r.id,'source_id':r.source_id,'review_text':r.review_text,'reply_text':r.reply_text,
             'status':r.status} for r in db.scalars(select(ReviewDraft).where(
                 ReviewDraft.organization_id == org_id).order_by(ReviewDraft.created_at.desc()).limit(100))]


@router.get('/summary')
def summary(org_id: str, user: User = Depends(current_user), db: Session = Depends(db_session)):
    org_membership(user,org_id,db)
    def count(model):
        return db.scalar(select(func.count()).select_from(model).where(model.organization_id == org_id))
    confirmed_telegram = db.scalar(select(func.count(NotificationChannel.id)).where(
        NotificationChannel.organization_id == org_id, NotificationChannel.kind == 'telegram',
        NotificationChannel.confirmed.is_(True))) or 0
    mail_claims = count(MailClaim)
    # API cannot inspect GitHub Actions variables/secrets: never imply live send readiness.
    return {'leads':count(BusinessLead),'review_drafts':count(ReviewDraft),'monitors':count(Monitor),
            'mail_claims':mail_claims, 'telegram_confirmed':bool(confirmed_telegram),
            'google_connected':False,'autonomous_mail_connected':False}


class CustomerMessage(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


@router.post('/assistant/analyze')
def analyze_message(org_id: str, data: CustomerMessage, user: User = Depends(current_user), db: Session = Depends(db_session)):
    org_membership(user,org_id,db)
    intent = rule_intent(data.text)
    return {'intent':intent,'needs_human':intent!='greeting',
            'reply_draft':'Merhaba, talebinizi işletme yetkilisinin değerlendirmesine sunabiliriz.',
            'external_message_sent':False}
