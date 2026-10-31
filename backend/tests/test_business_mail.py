import pytest
from sqlalchemy import select
from app.business_mail import run_once
from app.models import BusinessLead, MailClaim, NotificationChannel, NotificationDelivery


def setup(database, org):
    with database() as db:
        db.add(NotificationChannel(organization_id=org,kind='telegram',destination='123',confirmed=True))
        db.add(BusinessLead(organization_id=org,source_id='node/1',name='Synthetic',email='info@example.invalid',email_source='OSM business contact tag',delivery_state='not_sent'))
        db.commit()
    return dict(BUSINESS_AUTO_MAIL_ENABLED='true',BUSINESS_HISTORY_RECONCILED='true',LEGACY_MAIL_WORKFLOW_DISABLED='true',BUSINESS_ORGANIZATION_ID=org,GMAIL_SENDER_ADDRESS='owner@example.invalid',GMAIL_APP_PASSWORD='synthetic')


def test_once_with_full_report(database,two_users):
    env=setup(database,two_users[0]['organization_id'])
    calls=[]
    def sender(claim, _):
        with database() as db:
            assert db.get(MailClaim,claim.id).state=='sending'
        calls.append(claim.body)
    assert run_once(database,env,sender)['accepted']==1
    assert run_once(database,env,sender)['accepted']==0
    assert len(calls)==1
    with database() as db:
        assert calls[0] in db.scalar(select(NotificationDelivery.message))


def test_uncertain_never_retries(database,two_users):
    env=setup(database,two_users[0]['organization_id'])
    calls=[]
    def sender(*_):
        calls.append(1)
        raise TimeoutError('synthetic')
    assert run_once(database,env,sender)['uncertain']==1
    run_once(database,env,sender)
    assert len(calls)==1


def test_historic_recipient_blocked(database,two_users):
    org=two_users[0]['organization_id']
    env=setup(database,org)
    with database() as db:
        db.add(BusinessLead(organization_id=org,source_id='node/2',name='Historic',email='info@example.invalid',delivery_state='accepted'))
        db.commit()
    assert run_once(database,env,lambda *_:pytest.fail('SMTP'))['duplicate']==1


def test_missing_history_blocks(database,two_users):
    env=setup(database,two_users[0]['organization_id'])
    env.pop('BUSINESS_HISTORY_RECONCILED')
    with pytest.raises(RuntimeError,match='reconciled'):
        run_once(database,env,lambda *_:pytest.fail('SMTP'))


def test_crashed_claim_is_reported_without_resending(database,two_users):
    from datetime import timedelta
    from app.models import utcnow
    org=two_users[0]['organization_id']
    env=setup(database,org)
    with database() as db:
        lead=db.scalar(select(BusinessLead))
        lead.delivery_state='sending'
        db.add(MailClaim(organization_id=org,lead_id=lead.id,recipient=lead.email,subject='Frozen subject',body='Frozen full body',state='sending',created_at=utcnow()-timedelta(minutes=10)))
        db.commit()
    run_once(database,env,lambda *_:pytest.fail('must not resend'))
    with database() as db:
        claim=db.scalar(select(MailClaim))
        assert claim.state=='uncertain'
        assert 'Frozen full body' in db.scalar(select(NotificationDelivery.message))


def test_legacy_sender_must_be_disabled(database,two_users):
    env=setup(database,two_users[0]['organization_id'])
    env['LEGACY_MAIL_WORKFLOW_DISABLED']='false'
    with pytest.raises(RuntimeError,match='Legacy sender'):
        run_once(database,env,lambda *_:pytest.fail('No SMTP before cutover'))


def test_quota_counts_prior_claims_even_if_pending(database,two_users):
    org=two_users[0]['organization_id']
    env=setup(database,org)
    with database() as db:
        for i in range(5):
            lead=BusinessLead(organization_id=org,source_id=f'node/{i+100}',
                              name='Prior',email=f'prior{i}@example.invalid',
                              email_source='OSM business contact tag',delivery_state='uncertain')
            db.add(lead)
            db.flush()
            db.add(MailClaim(organization_id=org,lead_id=lead.id,recipient=lead.email,
                             subject='Prior subject',body='Prior body',state='uncertain'))
        db.commit()
    calls=[]
    result=run_once(database,env,lambda *_:calls.append(1))
    assert result['daily_limit_reached']==1
    assert result['accepted']==0 and calls==[]


def test_mail_body_only_routes_to_confirmed_telegram(database,two_users):
    org=two_users[0]['organization_id']
    env=setup(database,org)
    with database() as db:
        db.add(NotificationChannel(organization_id=org,kind='ntfy',destination='synthetic-topic',confirmed=True))
        db.commit()
    result=run_once(database,env,lambda *_:None)
    assert result['accepted']==1
    with database() as db:
        deliveries=db.scalars(select(NotificationDelivery)).all()
        private_reports=[d for d in deliveries if 'Mail sonucu' in d.message]
        assert len(private_reports)==1
        channel=db.get(NotificationChannel,private_reports[0].channel_id)
        assert channel.kind=='telegram'
