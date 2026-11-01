from app.history_import import convert


def test_legacy_frozen_recipient_and_uncertainty_preserved():
    record=convert('node/1',{'name':'Synthetic','email':'changed@example.invalid',
        '_auto_mail':{'recipient':'original@example.invalid','state':'uncertain'}},'review','org-a')
    assert record.email=='original@example.invalid'
    assert record.delivery_state=='uncertain'
    assert record.may_send_automatically is False


def test_legacy_drafts_never_become_sendable():
    record=convert('node/1',{'name':'Synthetic','_auto_mail':{'state':'draft'}},'review','org-a')
    assert record.delivery_state=='unknown'
    assert convert('node/1',{'name':'Synthetic'},'rejected','org-a').delivery_state=='rejected'


def test_legacy_delivery_feedback_preserved_as_suppressed_states():
    for state in ('failed', 'delayed'):
        record = convert('node/14', {'name':'Synthetic', '_auto_mail':{
            'recipient':'contact@example.invalid', 'state':'accepted',
            'delivery_feedback':{'state':state, 'smtp_code':'550'}}},
            'email_sent', 'org-a')
        assert record.delivery_state == state
        assert record.may_send_automatically is False


def test_legacy_reply_stops_new_contact():
    record = convert('node/15', {'name':'Synthetic', '_auto_mail':{
        'recipient':'contact@example.invalid', 'state':'accepted',
        'reply_feedback':{'state':'sender_matched_reply'}}},
        'email_sent', 'org-a')
    assert record.delivery_state == 'replied'
    assert record.may_send_automatically is False

def test_legacy_feedback_is_claim_linked_and_idempotent(database, two_users):
    from datetime import datetime, timezone
    from sqlalchemy import select, func
    from app.models import BusinessLead, MailClaim, BusinessMailFeedback, BusinessRecipientGuard
    from app.legacy_mail_reconciliation import reconcile_frozen_history

    org = two_users[0]['organization_id']
    data = {'name': 'Synthetic', 'email': 'test@example.invalid',
            '_auto_mail': {'recipient': 'test@example.invalid',
                           'subject': 'Original subject', 'body': 'Original body',
                           'state': 'accepted', 'delivery_feedback': {
                               'state': 'failed', 'observed_at': '2026-10-31T22:07:52+00:00',
                               'telegram_message_id': 84}}}
    with database() as db:
        lead = BusinessLead(organization_id=org, source_id='node/1234',
                            name='Synthetic', email='test@example.invalid',
                            delivery_state='accepted')
        db.add(lead)
        db.flush()
        claim = MailClaim(organization_id=org, lead_id=lead.id,
                          recipient='test@example.invalid', subject='Original subject',
                          body='Original body', state='accepted')
        db.add(claim)
        db.commit()
    for iteration in range(2):
        with database() as db:
            out = reconcile_frozen_history(db, org, [('node/1234', data, 'email_sent')])
            assert out['existing_claims'] == 1
            assert out['imported_claims'] == 0
            assert out['imported_feedback'] == int(iteration == 0)
            db.commit()
    with database() as db:
        assert db.scalar(select(func.count()).select_from(MailClaim)) == 1
        assert db.scalar(select(func.count()).select_from(BusinessMailFeedback)) == 1
        assert db.scalar(select(func.count()).select_from(BusinessRecipientGuard)) == 1
        receipt = db.scalar(select(BusinessMailFeedback))
        assert receipt.kind == 'failed' and receipt.telegram_receipt_id == 84
        assert receipt.observed_at.replace(tzinfo=timezone.utc) == datetime(
            2026, 10, 31, 22, 7, 52, tzinfo=timezone.utc)


def test_legacy_reconciliation_rejects_changed_mail_body(database, two_users):
    import pytest
    from app.models import BusinessLead, MailClaim
    from app.legacy_mail_reconciliation import reconcile_frozen_history
    org = two_users[0]['organization_id']
    with database() as db:
        lead = BusinessLead(organization_id=org, source_id='node/55',
                            name='Synthetic', delivery_state='accepted')
        db.add(lead)
        db.flush()
        db.add(MailClaim(organization_id=org, lead_id=lead.id, recipient='test@example.invalid',
                         subject='Original', body='Frozen', state='accepted'))
        db.commit()
    with database() as db:
        with pytest.raises(RuntimeError, match='mismatch'):
            reconcile_frozen_history(db, org, [('node/55', {'name': 'Synthetic',
                '_auto_mail': {'state': 'accepted', 'recipient': 'test@example.invalid',
                               'subject': 'Original', 'body': 'Tampered'}}, 'email_sent')])


def test_reply_feedback_not_counted_as_new_mail(database, two_users):
    from sqlalchemy import select, func
    from app.models import BusinessLead, MailClaim, BusinessMailFeedback
    from app.legacy_mail_reconciliation import reconcile_frozen_history
    org = two_users[0]['organization_id']
    with database() as db:
        lead=BusinessLead(organization_id=org,source_id='node/78',name='Synthetic',
                          delivery_state='accepted')
        db.add(lead)
        db.flush()
        db.add(MailClaim(organization_id=org,lead_id=lead.id,recipient='reply@example.invalid',
                         subject='S',body='B',state='accepted'))
        db.commit()
    raw={'name':'Synthetic','_auto_mail':{'state':'accepted','recipient':'reply@example.invalid',
         'subject':'S','body':'B','reply_feedback':{'state':'sender_matched_reply',
         'observed_at':'2026-10-31T22:07:52+00:00'}}}
    with database() as db:
        out=reconcile_frozen_history(db,org,[('node/78',raw,'email_sent')])
        assert out['imported_claims']==0 and out['imported_feedback']==1
        db.commit()
        assert db.scalar(select(func.count()).select_from(MailClaim))==1
        assert db.scalar(select(BusinessMailFeedback)).kind=='reply'
