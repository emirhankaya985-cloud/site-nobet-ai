# SiteNöbet AI

A multi-tenant web monitoring SaaS MVP prototype: independent Python background worker, FastAPI API, PostgreSQL with Alembic, Telegram / ntfy event outbox, and a responsive Next.js dashboard.

> **Development status (2026-10-26):** Verified GitHub CI [#40280592303](https://github.com/emirhankaya985-cloud/site-nobet-ai/actions/runs/40280592303) on commit `83d94891`: all 3 jobs green; 55 default backend tests passed (6 PostgreSQL-only tests intentionally skipped in that step), then all **6 real PostgreSQL 17 integration tests passed** separately; dependency audit, PostgreSQL migrations, frontend build, and Docker builds succeeded. **This is CI acceptance, NOT production acceptance.** SiteNöbet has not been deployed to Render; real Telegram/ntfy delivery, external outage/recovery drill, independently watched worker heartbeat, backup/restore and 7-day pilot remain unverified.

## Architecture

- `backend/app/main.py`: account, organization, monitor, reports, ntfy & Telegram binding API
- `backend/app/security.py`: SSRF policy, public IP / DNS validation, per-hop pinned DNS resolver, no environment proxies, limited redirects, TLS validation
- `backend/app/monitoring.py`: durable monitor states and transactional incident + notification outbox
- `backend/app/worker.py`: independent schedule loop, row leases, HTTP and SSL checks, deliveries, heartbeat
- `backend/app/notifications.py`: delivery retries, exponential backoff, event-level deduplication
- `backend/app/uptime.py`: time-weighted observed uptime; unknown time reported separately
- `backend/app/ssl_alerts.py`: 30/14/7/1 day threshold notices, cert-renewal-aware deduplication
- `frontend`: premium responsive Next.js interface; API-backed registration/login, dashboard, monitor details, reports, notifications

## Local setup

Recommended: Docker Compose with PostgreSQL:

```bash
docker compose up --build
```

Open web UI at <http://localhost:3000> and API at <http://localhost:8000/docs>.

Manual Python-only setup (SQLite for local development, NOT production):

```bash
cd backend
python -m venv .venv
# activate .venv
pip install -e '.[test]'
alembic upgrade head
uvicorn app.main:app --reload
# separate terminal with same environment:
python -m app.worker
```

Frontend separately:

```bash
cd frontend
npm install
npm run dev
```

The code uses `NEXT_PUBLIC_API_URL` at build time. When hosting the frontend on Render, configure the API's final public HTTPS URL *before* building. Backend `CORS_ORIGINS` must contain the frontend's exact HTTPS origin, comma-separated if needed.

## Production deployment

- `render.yaml` is provided as an **infrastructure proposal**, NOT applied. It creates **four billable resources** (frontend web, API web, always-on worker, Postgres); approval required before deployment.
- The service needs a real PostgreSQL DB, a strong `SESSION_SECRET` shared between API and worker, secure `CORS_ORIGINS`, and TLS URLs.
- Telegram requires `TELEGRAM_BOT_TOKEN` **and** `TELEGRAM_WEBHOOK_SECRET` in the API. Configure Telegram `setWebhook` to `https://YOUR-API/integrations/telegram/webhook` with `secret_token` matching the webhook secret, then link via short-lived user-specific `/start <code>` messages to the bot. Keep all bot secrets out of GitHub.
- ntfy uses high-entropy topic names. The topic link is a secret bearer capability; for stricter tenant privacy, deploy private authenticated ntfy or a separate provider. Never put the topic in public logs.
- An **external, independent** HTTP monitor must periodically call `/health/worker` and alert if it returns 503. API health alone cannot detect an idle or crashed worker. Configure after deployment.
- Set up managed database backups and test recovery before collecting paid users. Always confirm Render billing and domain/network limits.

## Verification commands

```bash
cd backend
python -m pytest -q
DATABASE_URL=sqlite:///./test-migrate.db alembic upgrade head
DATABASE_URL=sqlite:///./test-migrate.db alembic downgrade base
cd ../frontend
npm test
npm run lint
npm run typecheck
npm run build
```

A GitHub Actions workflow is included. Do not report CI as passed until real Actions logs are green.

## API behavior and limits

- Register an owner user and organization with `/auth/register`; token lifespan is 8 hours and stored only in the current browser tab sessionStorage (an MVP compromise; stronger cookie/session architecture remains).
- Starter plan: up to 3 monitors, fixed 300-second checks. Plan upgrade and payment endpoint not included.
- `DOWN` confirmed after two consecutive failures; return to `UP` after two consecutive successes. A single failed check results in `SUSPECTED_DOWN`.
- URL guards block loopback, RFC1918/private, link-local, metadata targets, non-HTTP(S) schemes, redirects to forbidden IPs, and nonstandard web ports. DNS answers are checked and pinned to the connection. Requires further third-party pentesting before production.
- Measurement hold capped at two check intervals; suspected, recovering and unknown time isn't declared healthy. A true SLA still requires a documented external contract.
- Detailed checks and TLS results kept 90 days; sent delivery records and audit logs 180 days. Open incidents retained.
- Rate limits: register 5/hour per connecting IP, login 15/15min; quotas are not a substitute for reverse-proxy request filtering.

## Outstanding production acceptance criteria

- Current source and test evidence: [GitHub Actions #40280592303](https://github.com/emirhankaya985-cloud/site-nobet-ai/actions/runs/40280592303), commit `83d94891`, 55 general + 6 real PostgreSQL test passes; all backend, frontend and Docker CI jobs green. Never push `.env`.
- GitHub CI has validated frontend installation, build, TypeScript, lint, Docker builds, backend tests, pip-audit, and PostgreSQL migration. Production-host PostgreSQL and startup tests are **unverified**.
- Email verification, password reset, complete organization member management, billing, production-grade rate limiting, scheduled emailed reports, per-channel channel management, alert analytics, 24-hour / 7-day / 30-day response graphs, and broader recovery / TLS tests remain.
- **Real multi-worker PostgreSQL integration smoke is now verified in CI** (monitor and notification claims, stale lease fencing, tenant isolation), but sustained high-volume stress, kill/restart/failover and production-host concurrency remain **unverified**.
- Outbox delivery is **at-least-once**, not guaranteed exactly-once: a crash after an external provider accepted a message but before local commit can produce a duplicate retry. Claim fencing protects database state from stale worker writes, but cannot make a remote Telegram/ntfy send transactional.
- Real delivery to Telegram / ntfy and live HTTP outage / recovery, independent heartbeat alert, backup restore, and 7-day pilot remain **unverified**.

## Security

See [SECURITY.md](SECURITY.md). Never send API tokens or credentials over chat or commit them to public code. Any external monitoring target must be owned or authorized by its owner.