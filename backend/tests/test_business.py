from app.models import NotificationChannel, NotificationDelivery
from sqlalchemy import select


def headers(user):
    return {'Authorization':'Bearer '+user['access_token']}


def test_import_idempotent_preserves_history_and_tenant(client,two_users,database):
    a,b=two_users
    url=f"/organizations/{a['organization_id']}/business/leads/import"
    payload={'id':'node/123','name':'Synthetic','email':'info@example.invalid',
             'email_source':'OSM business contact tag','delivery_state':'accepted'}
    with database() as db:
        db.add(NotificationChannel(organization_id=a['organization_id'],kind='telegram',destination='123',confirmed=True))
        db.commit()
    first=client.post(url,headers=headers(a),json=payload)
    assert first.status_code==200 and first.json()['created']
    again=client.post(url,headers=headers(a),json={**payload,'delivery_state':'not_sent'})
    assert again.status_code==200 and not again.json()['created']
    assert again.json()['lead']['delivery_state']=='accepted'
    assert client.post(url,headers=headers(b),json=payload).status_code==404
    assert client.get(url.removesuffix('/import'),headers=headers(b)).status_code==404
    with database() as db:
        rows=db.scalars(select(NotificationDelivery)).all()
        assert len(rows)==1
    bad=client.post(url,headers=headers(a),json={**payload,'organization_id':b['organization_id']})
    assert bad.status_code==422


def test_review_drafts_never_publish_and_are_tenant_scoped(client,two_users):
    a,b=two_users
    url=f"/organizations/{a['organization_id']}/business/reviews"
    payload={'source_id':'synthetic-review-1','review_text':'Synthetic feedback'}
    first=client.post(url+'/import',headers=headers(a),json=payload)
    assert first.status_code==200 and first.json()['status']=='draft'
    again=client.post(url+'/import',headers=headers(a),json=payload)
    assert again.json()['id']==first.json()['id'] and not again.json()['created']
    assert len(client.get(url,headers=headers(a)).json())==1
    assert client.get(url,headers=headers(b)).status_code==404
    summary=client.get(f"/organizations/{a['organization_id']}/business/summary",headers=headers(a)).json()
    assert summary['review_drafts']==1
    assert summary['google_connected'] is False
    assert summary['autonomous_mail_connected'] is False


def test_original_leadpilot_and_yorumpilot_rules_are_wired(client,two_users):
    a=two_users[0]
    base=f"/organizations/{a['organization_id']}/business"
    result=client.post(base+'/assistant/analyze',headers=headers(a),json={'text':'Randevu almak istiyorum'})
    assert result.json()['intent']=='appointment'
    assert result.json()['external_message_sent'] is False
    result=client.post(base+'/reviews/import',headers=headers(a),json={'source_id':'bad-service','review_text':'Çok bekledim, hizmet kötüydü','stars':1})
    assert result.status_code==200
    assert 'olumsuz deneyim' in result.json()['reply_text']
