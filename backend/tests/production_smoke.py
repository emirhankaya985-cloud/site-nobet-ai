"""Start real API + independent worker processes against the ephemeral CI PostgreSQL.

This script does not create monitors or send any outbound notifications.
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import timedelta

PORT = 18763
BASE = f"http://127.0.0.1:{PORT}"


def request(path, payload=None, bearer=None):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    try:
        with urllib.request.urlopen(
            urllib.request.Request(BASE + path, data=data, headers=headers,
                                   method="POST" if payload is not None else "GET"),
            timeout=3,
        ) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def eventually(fn, description, timeout=25):
    start = time.monotonic()
    last = ""
    while time.monotonic() - start < timeout:
        try:
            value = fn()
            if value:
                return value
        except (OSError, ValueError, RuntimeError) as exc:
            last = str(exc)
        time.sleep(0.3)
    raise AssertionError(f"Timed out waiting for {description}: {last}")


def stop(proc):
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def main():
    assert os.getenv("CI") == "true", "Only an isolated CI test environment is permitted"
    assert os.environ.get("DATABASE_URL", "").endswith("/sitenobet_test"), "Refuse unknown database"
    assert os.environ.get("APP_ENV") == "production", "Exercise production validation"
    from app.database import session_factory
    from app.models import WorkerHeartbeat, utcnow

    api = worker = None
    try:
        api = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", str(PORT)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        eventually(lambda: request("/health")[0] == 200, "API + DB readiness")
        assert request("/health/worker")[0] == 503, "Worker should be initially absent"

        worker = subprocess.Popen(
            [sys.executable, "-m", "app.worker"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        eventually(lambda: request("/health/worker")[0] == 200, "worker startup")

        def register():
            identifier = uuid.uuid4().hex
            status, value = request("/auth/register", {
                "email": f"smoke-{identifier}@example.invalid",
                "password": "CI-strong-password-2026-and-more",
                "organization_name": "CI Production Startup",
            })
            assert status == 201, (status, value)
            return value

        alice, bob = register(), register()
        headers_a = alice["access_token"]
        status, own = request("/organizations/" + alice["organization_id"] + "/dashboard", bearer=headers_a)
        assert status == 200 and own["total"] == 0
        status, _ = request("/organizations/" + alice["organization_id"] + "/dashboard", bearer=bob["access_token"])
        assert status == 404, "Cross-tenant access must be blocked"
        print("PASS: production-configured API, DB, worker heartbeat, registration, cross-tenant denial")

        stop(worker)
        worker = None
        with session_factory()() as db:
            row = db.get(WorkerHeartbeat, "main")
            assert row is not None
            row.last_seen_at = utcnow() - timedelta(minutes=3)
            db.commit()
        assert request("/health/worker")[0] == 503, "Stale heartbeat must fail health"
        worker = subprocess.Popen(
            [sys.executable, "-m", "app.worker"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        eventually(lambda: request("/health/worker")[0] == 200, "worker restart heartbeat")
        print("PASS: worker outage detection and restart recovered")
    finally:
        stop(worker)
        stop(api)


if __name__ == "__main__":
    main()
