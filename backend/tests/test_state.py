from datetime import timedelta
from sqlalchemy import select
from app.monitoring import apply_probe, transition
from app.models import Organization, Monitor, Incident, NotificationChannel, NotificationDelivery, CheckResult, utcnow
from app.security import Probe
from app.uptime import uptime_summary


def test_state_machine_sequence():
    s, ok, fail = "UNKNOWN", 0, 0
    events = []
    for healthy in [True, False, False, False, True, False, True, True]:
        s,ok,fail,event = transition(s,ok,fail,healthy)
        events.append((s,event))
    assert events == [("UP",None),("SUSPECTED_DOWN",None),("DOWN","down"),("DOWN",None),("RECOVERING",None),("DOWN",None),("RECOVERING",None),("UP","recovered")]


def test_incident_idempotent_and_recovery(database):
    with database() as db:
        org = Organization(name="Test")
        db.add(org); db.flush()
        monitor = Monitor(organization_id=org.id,name="Example",url="https://example.com/")
        channel = NotificationChannel(organization_id=org.id,kind="ntfy",destination="private-random-token",confirmed=True)
        db.add_all([monitor,channel]);db.commit()
        for x in [False,False,False,True,True]:
            apply_probe(db,monitor,Probe(x,200 if x else 503,20,"HTTP_ERROR" if not x else None));db.commit()
        incidents = db.scalars(select(Incident).where(Incident.monitor_id==monitor.id)).all()
        deliveries = db.scalars(select(NotificationDelivery)).all()
        assert monitor.status == "UP"
        assert len(incidents) == 1 and incidents[0].closed_at is not None
        assert len(deliveries) == 2
        assert {d.event_key.split(":")[2] for d in deliveries} == {"down","recovered"}
        assert len(db.scalars(select(CheckResult)).all()) == 5


def test_uptime_reports_unknown_not_100_percent(database):
    with database() as db:
        org = Organization(name="Org");db.add(org);db.flush()
        m=Monitor(organization_id=org.id,name="Site",url="https://example.com/",interval_seconds=300)
        db.add(m);db.commit()
        report = uptime_summary(db,m)
        assert report["uptime_percent"] is None
        assert report["unobserved_seconds"] == 86400


def test_ssl_threshold_dedup_and_renewal(database):
    from app.ssl_alerts import process_ssl_result
    with database() as db:
        org = Organization(name="Org"); db.add(org); db.flush()
        m = Monitor(organization_id=org.id, name="HTTPS", url="https://example.com/")
        c = NotificationChannel(organization_id=org.id, kind="ntfy", destination="secret", confirmed=True)
        db.add_all([m,c]); db.commit()
        exp = utcnow() + timedelta(days=6)
        process_ssl_result(db,m,exp,None); db.commit()
        process_ssl_result(db,m,exp,None); db.commit()
        assert len(db.scalars(select(NotificationDelivery)).all()) == 1
        process_ssl_result(db,m,exp + timedelta(days=20),None); db.commit()
        assert len(db.scalars(select(NotificationDelivery)).all()) == 2


def test_uptime_sqlite_datetime_round_trip(database):
    """SQLite strips UTC tzinfo; production reports must not crash after DB read."""
    with database() as db:
        org = Organization(name="Org");db.add(org);db.flush()
        m=Monitor(organization_id=org.id,name="Site",url="https://example.com/",interval_seconds=60)
        db.add(m);db.commit()
        apply_probe(db,m,Probe(True,200,5));db.commit()
    with database() as db:
        m=db.get(Monitor,m.id)
        report=uptime_summary(db,m)
        assert report["observed_seconds"] >= 0
        assert report["uptime_percent"] == 100.0
