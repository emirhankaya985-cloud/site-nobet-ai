from unittest.mock import AsyncMock
import pytest
from sqlalchemy import select
from app.business_pipeline import run
from app.models import BusinessLead, NotificationChannel


@pytest.mark.asyncio
async def test_research_import_mail_monitor_chain_is_idempotent(database,two_users):
    org=two_users[0]['organization_id']
    with database() as db:
        db.add(NotificationChannel(organization_id=org,kind='telegram',destination='123',confirmed=True))
        db.commit()
    env={'BUSINESS_PIPELINE_ENABLED':'true','BUSINESS_HISTORY_RECONCILED':'true',
         'LEGACY_MAIL_WORKFLOW_DISABLED':'true','BUSINESS_ORGANIZATION_ID':org,
         'BUSINESS_AUTO_MAIL_ENABLED':'true'}
    rows=[{'type':'node','id':1,'tags':{'name':'Synthetic','shop':'beauty','email':'info@example.invalid'}}]
    calls=[]
    def mailer(factory, _):
        with factory() as db:
            assert len(db.scalars(select(BusinessLead)).all())==1
        calls.append(1)
        return {'accepted':0}
    monitor=AsyncMock()
    from unittest.mock import patch
    with patch('app.business_pipeline.drain',new_callable=AsyncMock):
        first=await run(env,database,lambda _:rows,mailer,monitor)
        again=await run(env,database,lambda _:rows,mailer,monitor)
    assert first['imported']==1 and again['imported']==0
    assert len(calls)==2 and monitor.await_count==2


@pytest.mark.asyncio
async def test_activation_requires_legacy_sender_disabled():
    with pytest.raises(RuntimeError,match='legacy'):
        await run({'BUSINESS_PIPELINE_ENABLED':'true','BUSINESS_HISTORY_RECONCILED':'true','BUSINESS_AUTO_MAIL_ENABLED':'true'})


@pytest.mark.asyncio
async def test_successful_daily_batch_blocks_second_mail_stage(database,two_users):
    org=two_users[0]['organization_id']
    env={'BUSINESS_PIPELINE_ENABLED':'true','BUSINESS_HISTORY_RECONCILED':'true',
         'LEGACY_MAIL_WORKFLOW_DISABLED':'true','BUSINESS_ORGANIZATION_ID':org,
         'BUSINESS_AUTO_MAIL_ENABLED':'true'}
    from unittest.mock import patch
    calls=[]
    def mailer(*_):
        calls.append(1)
        return {'accepted':1}
    with patch('app.business_pipeline.drain',new_callable=AsyncMock):
        await run(env,database,lambda _:[],mailer,AsyncMock())
        result=await run(env,database,lambda _:pytest.fail('second scan'),mailer,AsyncMock())
    assert result['skipped_existing_daily_batch']==1
    assert len(calls)==1


@pytest.mark.asyncio
async def test_disabled_mail_never_leaves_a_daily_batch_or_imports(database, two_users):
    """Regression: old code recorded mail_started before raising and blocked the day."""
    from sqlalchemy import func
    from app.models import BusinessBatch
    org = two_users[0]['organization_id']
    env = {'BUSINESS_PIPELINE_ENABLED':'true', 'BUSINESS_HISTORY_RECONCILED':'true',
           'LEGACY_MAIL_WORKFLOW_DISABLED':'true', 'BUSINESS_AUTO_MAIL_ENABLED':'false',
           'BUSINESS_ORGANIZATION_ID':org}
    calls = []
    def forbidden(*_args, **_kwargs):
        calls.append(1)
        raise RuntimeError('mail disabled')
    with pytest.raises(RuntimeError, match='mail disabled'):
        await run(env=env, factory=database, researcher=lambda _: [], mailer=forbidden, monitor=AsyncMock())
    with database() as db:
        assert db.scalar(select(func.count()).select_from(BusinessBatch)) == 0
        assert db.scalar(select(func.count()).select_from(BusinessLead)) == 0
    assert not calls, 'Disabled mail must fail before any mailer invocation'


@pytest.mark.asyncio
async def test_missing_smtp_prevents_research_and_batch_creation(database, two_users):
    from sqlalchemy import func
    from app.models import BusinessBatch
    org = two_users[0]['organization_id']
    env = {'BUSINESS_PIPELINE_ENABLED': 'true', 'BUSINESS_AUTO_MAIL_ENABLED': 'true',
           'BUSINESS_HISTORY_RECONCILED': 'true', 'LEGACY_MAIL_WORKFLOW_DISABLED': 'true',
           'BUSINESS_ORGANIZATION_ID': org}
    with pytest.raises(RuntimeError, match='SMTP configuration incomplete'):
        await run(env=env, factory=database,
                  researcher=lambda _: pytest.fail('No research before SMTP preflight'),
                  monitor=AsyncMock())
    with database() as db:
        assert db.scalar(select(func.count()).select_from(BusinessBatch)) == 0
        assert db.scalar(select(func.count()).select_from(BusinessLead)) == 0


@pytest.mark.asyncio
async def test_unconfirmed_telegram_prevents_research(database, two_users):
    from sqlalchemy import func
    from app.models import BusinessBatch
    org = two_users[0]['organization_id']
    env = {'BUSINESS_PIPELINE_ENABLED': 'true', 'BUSINESS_AUTO_MAIL_ENABLED': 'true',
           'BUSINESS_HISTORY_RECONCILED': 'true', 'LEGACY_MAIL_WORKFLOW_DISABLED': 'true',
           'BUSINESS_ORGANIZATION_ID': org, 'GMAIL_SENDER_ADDRESS': 'test@example.invalid',
           'GMAIL_APP_PASSWORD': 'synthetic'}
    with pytest.raises(RuntimeError, match='Confirmed private Telegram'):
        await run(env=env, factory=database,
                  researcher=lambda _: pytest.fail('No research without confirmed Telegram'),
                  monitor=AsyncMock())
    with database() as db:
        assert db.scalar(select(func.count()).select_from(BusinessBatch)) == 0


@pytest.mark.asyncio
async def test_early_istanbul_mail_claim_prevents_batch_deletion_on_failure(database, two_users):
    from datetime import datetime, timezone
    from unittest.mock import patch
    from zoneinfo import ZoneInfo
    from app.models import BusinessBatch, MailClaim

    org = two_users[0]['organization_id']
    env = {'BUSINESS_PIPELINE_ENABLED': 'true', 'BUSINESS_HISTORY_RECONCILED': 'true',
           'LEGACY_MAIL_WORKFLOW_DISABLED': 'true', 'BUSINESS_ORGANIZATION_ID': org,
           'BUSINESS_AUTO_MAIL_ENABLED': 'true'}

    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 1, 0, 40, tzinfo=ZoneInfo('Europe/Istanbul'))

    def interrupted_mailer(factory, _env):
        with factory() as db:
            lead = BusinessLead(organization_id=org, source_id='node/999',
                                name='Synthetic', email='synthetic@example.invalid',
                                email_source='test', delivery_state='sending')
            db.add(lead)
            db.flush()
            db.add(MailClaim(organization_id=org, lead_id=lead.id,
                             recipient=lead.email, subject='Synthetic',
                             body='Synthetic', state='sending',
                             created_at=datetime(2026, 10, 31, 21, 10,
                                                 tzinfo=timezone.utc)))
            db.commit()
        raise RuntimeError('Synthetic crash after persistent mail claim')

    with patch('app.business_pipeline.datetime', FrozenDateTime), patch(
            'app.business_pipeline.drain', new_callable=AsyncMock):
        with pytest.raises(RuntimeError, match='Synthetic crash'):
            await run(env=env, factory=database, researcher=lambda _: [],
                      mailer=interrupted_mailer, monitor=AsyncMock())
    with database() as db:
        assert db.scalar(select(BusinessBatch).where(
            BusinessBatch.organization_id == org)) is not None
        assert db.scalar(select(MailClaim).where(
            MailClaim.organization_id == org)) is not None
