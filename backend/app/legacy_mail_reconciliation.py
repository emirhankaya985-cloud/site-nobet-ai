"""Idempotent, SMTP-free reconciliation of legacy immutable mail claims and feedback."""
from datetime import datetime, timezone

from sqlalchemy import select

from .business_mail import reserve_recipient
from .models import BusinessLead, MailClaim, BusinessMailFeedback


def _observation(value):
    if not isinstance(value, str):
        raise RuntimeError("Legacy feedback observation timestamp required")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise RuntimeError("Invalid legacy feedback timestamp") from None
    if dt.tzinfo is None:
        raise RuntimeError("Legacy feedback timestamp requires timezone")
    return dt.astimezone(timezone.utc)


def reconcile_frozen_history(db, organization, source_rows):
    """Preserve accepted SMTP evidence without claiming any new external sends.

    source_rows: (OSM source ID, old lead_data dict, old owner status).
    Must run inside a database transaction; caller commits once after validation.
    """
    result = dict(existing_claims=0, imported_claims=0,
                  imported_feedback=0, existing_feedback=0, guarded=0)
    for source_id, data, status in source_rows:
        if not isinstance(data, dict):
            raise RuntimeError("Invalid legacy source record")
        mail = data.get("_auto_mail") or data.get("_mail") or {}
        lead = db.scalar(select(BusinessLead).where(
            BusinessLead.organization_id == organization,
            BusinessLead.source_id == source_id))
        if lead is None:
            raise RuntimeError("Legacy identity not imported")
        # Decisions and any frozen contact must block future sends independently
        # of whether a past SMTP acceptance record exists.
        if status in ("rejected", "deferred"):
            if lead.delivery_state not in ("accepted", "sending", "uncertain"):
                lead.delivery_state = status
            recipient = mail.get("recipient") or data.get("email")
            if recipient and reserve_recipient(db, organization, recipient,
                                                "legacy_suppression", source_id):
                result["guarded"] += 1

        if status != "email_sent" or mail.get("state") != "accepted":
            continue
        recipient, subject, body = (mail.get(k) for k in ("recipient", "subject", "body"))
        if not all(isinstance(v, str) and v for v in (recipient, subject, body)):
            raise RuntimeError("Frozen accepted SMTP claim incomplete")
        claim = db.scalar(select(MailClaim).where(
            MailClaim.organization_id == organization, MailClaim.lead_id == lead.id))
        if claim:
            if (claim.recipient.strip().casefold() != recipient.strip().casefold()
                    or claim.subject != subject or claim.body != body):
                raise RuntimeError("Frozen SMTP claim mismatch; no overwrite")
            result["existing_claims"] += 1
        else:
            claim = MailClaim(organization_id=organization, lead_id=lead.id,
                              recipient=recipient.strip().casefold(), subject=subject,
                              body=body, state="accepted")
            db.add(claim)
            db.flush()
            # Keep later failure, delay, reply and suppression states.
            if lead.delivery_state not in ("failed", "delayed", "replied", "rejected", "deferred"):
                lead.delivery_state = "accepted"
            result["imported_claims"] += 1
        if reserve_recipient(db, organization, recipient, "legacy", source_id):
            result["guarded"] += 1

        for field in ("delivery_feedback", "reply_feedback"):
            feedback = mail.get(field)
            if not isinstance(feedback, dict):
                continue
            kind = feedback.get("state")
            if field == "reply_feedback" and kind == "sender_matched_reply":
                kind = "reply"
            if kind not in (("failed", "delayed") if field == "delivery_feedback"
                            else ("reply",)):
                raise RuntimeError("Unexpected legacy feedback state")
            receipt = feedback.get("telegram_message_id")
            if receipt is not None and (type(receipt) is not int or receipt <= 0):
                raise RuntimeError("Invalid legacy Telegram receipt")
            when = _observation(feedback.get("observed_at"))
            old = db.scalar(select(BusinessMailFeedback).where(
                BusinessMailFeedback.claim_id == claim.id,
                BusinessMailFeedback.provider == "legacy_gmail_watch",
                BusinessMailFeedback.kind == kind))
            if old:
                if (old.observed_at.replace(tzinfo=old.observed_at.tzinfo or timezone.utc)
                        .astimezone(timezone.utc) != when
                        or old.telegram_receipt_id != receipt):
                    raise RuntimeError("Legacy feedback conflict; preserve original")
                result["existing_feedback"] += 1
            else:
                db.add(BusinessMailFeedback(
                    organization_id=organization, claim_id=claim.id,
                    provider="legacy_gmail_watch", kind=kind,
                    observed_at=when, telegram_receipt_id=receipt))
                result["imported_feedback"] += 1
    return result
