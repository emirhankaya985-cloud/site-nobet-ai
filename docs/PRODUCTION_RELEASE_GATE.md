# SiteNöbet AI — Production release gate

**Current verdict: code/CI hardening in progress; PRODUCTION NOT ACCEPTED.**

## Costs & explicit owner approval

Render's free web instances spin down after 15 minutes of inactivity; Render's free PostgreSQL expires after 30 days. Free plans are not appropriate for an always-on public uptime monitor. Background workers require paid compute.

The `render.yaml` Blueprint declares four **paid** resources: web frontend (`0.5c-512mb`), FastAPI web (`0.5c-512mb`), dedicated worker (`0.5c-512mb`), and PostgreSQL (`0.1c-256mb`). Reference baseline is **around US $27 per month** (three $7 services and a $6 database), excluding variable charges, currency conversion and taxes. Check current checkout pricing before applying.

**Never create or apply the Blueprint without explicit owner approval.** No cost has been authorized yet.

## Required variables / secrets — names only

- FastAPI: `APP_ENV=production`, `APP_ROLE=api` (implicit default), `DATABASE_URL` (Render Postgres), `SESSION_SECRET` (shared generated value from worker), `CORS_ORIGINS` (exact HTTPS web domain).
- If Telegram is enabled: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_WEBHOOK_SECRET` (16+ chars) on API; `TELEGRAM_BOT_TOKEN` on worker. Set Telegram `setWebhook` to the public HTTPS API webhook with the matching `secret_token`.
- Worker: `APP_ENV=production`, `APP_ROLE=worker`, shared `DATABASE_URL` and `SESSION_SECRET`. Worker does **not** require web CORS or Telegram webhook secret.
- Frontend: `NEXT_PUBLIC_API_URL` set to the API's final HTTPS origin **before build**.
- Optional: `NTFY_BASE_URL` HTTPS endpoint on both API and worker if overriding the default.

**Never place secret values into a public issue, repository commit or this report.** User-managed variable values need verification by name, not disclosure.

## CI gates before go-live

1. GitHub main CI must pass backend unit tests, PostgreSQL integration tests, production-configured API/worker process smoke, PostgreSQL migration, dependency audit, frontend lint/typecheck/build and both Docker builds.
2. Worker health (`GET /health/worker`) must show 200 while worker lives, 503 after stale heartbeat, 200 after restart. API `GET /health` must require database and applied migrations.
3. Verify TLS, live authorization isolation, queue fencing and retry, negative security scenarios and rate limits.
4. Branch ruleset: protect `main`; require backend, frontend and docker CI checks, block force push and deletion.

## Live acceptance (required; not covered by ephemeral CI)

1. Deploy approved services with correct origins and secrets. Confirm API, worker and frontend health checks.
2. Verify Telegram delivery using a **user-approved test chat**, and ntfy delivery using a **test topic**; record provider receipt IDs without logging credentials or secret topic URLs.
3. Run a controlled outage -> DOWN -> recovery -> UP test **only against an owned/authorized target**, verify correct notifications and tenant isolation.
4. Add **independent external** watchdog against `/health/worker`, alert on 503 and unreachable HTTP. An in-process heartbeat without an external observer cannot alert on worker failure.
5. Validate database backup/export and restoration in a disposable environment. Record RPO/RTO; rehearse rollback.
6. Run at least 7 days with observation logs and clear availability gaps. Only then consider full production acceptance.

## Important delivery limitation

Remote Telegram/ntfy sends are not atomic with the local database commit. If the provider accepts a message but the worker crashes before marking it sent, a retry may duplicate it. Lease fencing prevents stale local state writes but does not provide exactly-once remote delivery.

Keep no-charge CI work separate from deployment acceptance. Never claim FULL PASS just because builds are green.
