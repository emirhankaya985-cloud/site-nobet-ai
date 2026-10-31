"""Read-only legacy history -> shared CRM. No SMTP and no source writes."""
import os
from sqlalchemy import select
from .database import session_factory
from .lead_import import parse_import
from .models import BusinessLead, Organization


def convert(source_id, data, status, org):
    record=data.get('_auto_mail') or data.get('_mail') or {}
    state=record.get('state','unknown')
    if status in ('rejected','deferred'):
        state=status
    elif status=='email_sent':
        state='accepted'
    if state not in ('accepted','sending','uncertain','rejected','deferred'):
        state='unknown'  # Old draft/skipped state never becomes new send permission.
    email=record.get('recipient') or data.get('email') or None
    source=record.get('recipient_source') or data.get('email_source')
    if email and not source and source_id.startswith(('node/','way/','relation/')):
        source='OSM business contact tag'
    payload={'id':source_id,'name':data.get('name'),'email':email,'email_source':source,
             'website':data.get('website') or None,'delivery_state':state}
    return parse_import(payload,org)


def run(env=None, factory=None):
    import json
    import psycopg
    env=os.environ if env is None else env
    url=env.get('LEGACY_REVIEW_DATABASE_URL','')
    if not url.startswith(('postgresql://','postgres://')) or 'sslmode=require' not in url:
        raise RuntimeError('Legacy source must use SSL')
    org=env.get('BUSINESS_ORGANIZATION_ID')
    # An explicitly read-only source transaction cannot modify production history.
    with psycopg.connect(url,connect_timeout=15) as source:
        source.execute('SET TRANSACTION READ ONLY')
        rows=source.execute('SELECT osm_id,lead_data,status FROM owner_leads').fetchmany(100001)
        if len(rows)>100000:
            raise RuntimeError('History exceeds bounded migration limit')
        records=[convert(lid,json.loads(data) if isinstance(data,str) else data,status,org)
                 for lid,data,status in rows]
    factory=factory or session_factory()
    with factory() as db:
        if db.get(Organization,org) is None:
            raise RuntimeError('Target organization does not exist')
        inserted=0
        for record in records:
            existing=db.scalar(select(BusinessLead).where(BusinessLead.organization_id==org,
                                                         BusinessLead.source_id==record.source_id))
            if existing:
                # Never discard evidence of an earlier send when a new draft exists.
                frozen = ('accepted', 'sending', 'uncertain', 'rejected', 'deferred')
                # Never downgrade a prior send or explicit owner decision.
                if existing.delivery_state not in frozen and record.delivery_state in frozen:
                    existing.delivery_state = record.delivery_state
                continue
            db.add(BusinessLead(organization_id=org,source_id=record.source_id,name=record.name,
                email=record.email,email_source=record.email_source,website=record.website,
                delivery_state=record.delivery_state))
            inserted+=1
        db.commit()
    return {'source_rows':len(records),'inserted':inserted,'business_mail_sent':0}


if __name__=='__main__':
    try:
        print(run())
    except Exception:
        raise RuntimeError('Private history migration failed; no mail sent; details redacted') from None
