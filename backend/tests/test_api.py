
def h(user): return {"Authorization": "Bearer " + user["access_token"]}


def test_register_login_me(client):
    response = client.post("/auth/register",json={"email":"hi@example.com","password":"correct horse battery","organization_name":"Startup"})
    assert response.status_code == 201
    token = response.json()
    assert client.get("/auth/me",headers=h(token)).json()["email"] == "hi@example.com"
    bad = client.post("/auth/login",json={"email":"hi@example.com","password":"incorrect"})
    assert bad.status_code == 401
    good = client.post("/auth/login",json={"email":"hi@example.com","password":"correct horse battery"})
    assert good.status_code == 200


def test_cross_tenant_isolation(client,two_users):
    alice,bob = two_users
    org_a=alice["organization_id"]
    result=client.post(f"/organizations/{org_a}/monitors",headers=h(alice),json={"name":"Site","url":"https://example.com"})
    assert result.status_code == 201, result.text
    mid=result.json()["id"]
    assert client.get(f"/organizations/{org_a}/monitors",headers=h(bob)).status_code == 404
    assert client.get(f"/organizations/{org_a}/monitors/{mid}",headers=h(bob)).status_code == 404
    assert client.get(f"/organizations/{org_a}/monitors/{mid}",headers=h(alice)).status_code == 200
    assert client.patch(f"/organizations/{org_a}/monitors/{mid}",headers=h(bob),json={"paused":True}).status_code == 404
    assert client.get(f"/organizations/{org_a}/dashboard",headers=h(bob)).status_code == 404


def test_plan_restrictions(client,two_users):
    person = two_users[0];org=person["organization_id"]
    base = f"/organizations/{org}/monitors"
    assert client.post(base,headers=h(person),json={"name":"too fast","url":"https://example.com","interval_seconds":60}).status_code == 400
    for i in range(3):
        response = client.post(base,headers=h(person),json={"name":f"Monitor{i}","url":f"https://example{i}.com"})
        assert response.status_code == 201, response.text
    assert client.post(base,headers=h(person),json={"name":"fourth","url":"https://example4.com"}).status_code == 403
    assert client.get(f"/organizations/{org}/dashboard",headers=h(person)).json()["total"] == 3


def test_channel_and_telegram_security(client,two_users):
    user=two_users[0]; org=user["organization_id"]
    p=f"/organizations/{org}/notifications"
    result=client.post(p+"/ntfy",headers=h(user))
    assert result.status_code==201
    assert len(result.json()["topic"]) >= 40
    assert client.post("/integrations/telegram/webhook",json={"message":{"chat":{"id":1},"text":"/start fake"}}).status_code==403
    assert client.get(p,headers=h(two_users[1])).status_code==404


def test_auth_required(client):
    assert client.get("/auth/me").status_code==401
    assert client.get("/organizations/xxx/monitors").status_code==401


def test_worker_health_without_heartbeat(client):
    assert client.get("/health/worker").status_code == 503


def test_daily_weekly_reports(client,two_users):
    user=two_users[0]; org=user["organization_id"]
    daily=client.get(f"/organizations/{org}/reports?period_days=1",headers=h(user))
    weekly=client.get(f"/organizations/{org}/reports?period_days=7",headers=h(user))
    assert daily.status_code==200 and weekly.status_code==200
    assert daily.json()["uptime_percent"] is None
    assert daily.json()["period_days"] == 1
    assert weekly.json()["period_days"] == 7
    assert client.get(f"/organizations/{org}/reports?period_days=22",headers=h(user)).status_code==400
    assert client.get(f"/organizations/{org}/reports",headers=h(two_users[1])).status_code==404


def test_pause_marks_unknown_time_and_does_not_falsely_recover(client,two_users,database):
    from app.models import Incident, Monitor
    from app.monitoring import apply_probe
    from app.security import Probe
    from sqlalchemy import select
    person=two_users[0];org=person["organization_id"]
    r=client.post(f"/organizations/{org}/monitors",headers=h(person),json={"name":"Website","url":"https://example.com"})
    mid=r.json()["id"]
    with database() as db:
        monitor=db.get(Monitor,mid)
        apply_probe(db,monitor,Probe(False,503,100,"HTTP_ERROR"))
        apply_probe(db,monitor,Probe(False,503,100,"HTTP_ERROR"))
        db.commit()
    r=client.patch(f"/organizations/{org}/monitors/{mid}",headers=h(person),json={"paused":True})
    assert r.status_code==200 and r.json()["status"] == "PAUSED"
    with database() as db:
        incident=db.scalar(select(Incident).where(Incident.monitor_id==mid))
        assert incident.closed_reason == "paused"
        assert incident.closed_at is not None
    r=client.patch(f"/organizations/{org}/monitors/{mid}",headers=h(person),json={"paused":False})
    assert r.json()["status"] == "UNKNOWN"
