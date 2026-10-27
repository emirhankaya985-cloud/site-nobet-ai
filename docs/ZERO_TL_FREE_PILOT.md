# SiteNöbet AI — 0 TL scheduled pilot (no SLA)

## Cost policy

**Only Free tiers. No paid Render worker or managed Render Postgres.** A GitHub Actions scheduled workflow drives bounded worker batches against the dedicated Neon Free project `sitenobet-ai-free`, now provisioned in Frankfurt. The website/API may be served by free hosting for a small pilot, but these providers can sleep, throttle, suspend, or have quotas.

This **cannot promise uninterrupted 24/7 monitoring, exact 15-minute checks or guaranteed delivery**. GitHub may delay/drop scheduled runs and disables cron in inactive public repositories after 60 days. Free Neon quotas may exhaust and pause database compute. Don't market this as professional-grade uptime.

## Setup

1. Keep the repo **public**. The dedicated **Free** Neon project `sitenobet-ai-free` has been created in Frankfurt with its own database `sitenobet`; do not reuse another project's database.
2. Configure GitHub repository **Actions secrets** (values go only in GitHub Secrets):
   - `SITENOBET_DATABASE_URL`: the dedicated Neon PostgreSQL connection string (TLS enabled).
   - Optional `SITENOBET_TELEGRAM_BOT_TOKEN`: only your SiteNöbet bot, authorized test chat. Never reuse or print another project's tokens.
3. The scheduled workflow now automatically skips the monitor job if `SITENOBET_DATABASE_URL` is missing. Once this GitHub Action Secret exists, the monitoring job can run without a separate enable variable. Verify credentials are for the dedicated Free SiteNöbet database before setting the secret.
4. Initialize and migrate the dedicated DB as a separate explicit deployment action, or use the guarded bootstrap step in the scheduled workflow when first enabled.
5. Configure any hosted API with `APP_ENV=production`, `APP_ROLE=api`, `SCHEDULER_MODE=cron`, the same `DATABASE_URL` and an API-only strong `SESSION_SECRET`, and HTTPS `CORS_ORIGINS`. The frontend must be built with matching `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_CHECK_INTERVAL_SECONDS=900`.
6. Visit Actions → **SiteNobet Free Scheduled Monitor** → Run workflow to test the first job. Confirm logs without exposing credentials.
7. Check data freshness. In cron mode `/health/worker` reports stale after approximately 32 minutes (rather than 60 seconds), which can still false-alarm on GitHub schedule delays.

## Behavior and limits

- Cron: minutes 7, 22, 37, 52 of each hour (UTC), nominally every 15 minutes.
- Runner: bounded one-shot process, up to 20 due monitors and 50 queued notifications per invocation, with a six-minute in-process deadline.
- For the free mode, the API accepts **3 monitors at 900-second intervals**, regardless of paid-plan flags. It does not falsely advertise 5-minute checks.
- Scheduling latency and GitHub outages **are not counted as uptime**. The dashboard can become stale while the external runner is delayed. User-facing quality must remain explicitly "pilot".
- **Neon Free** (October 2026): 1 GB storage/project, 100 CU-hours/project/month and compute suspend when idle. Monitor usage to avoid free quota suspension.
- No public credentials or tokens should ever be copied into GitHub source or chat.
- A real production SLA or immediate incident alert needs continuously available infrastructure, which is not guaranteed by this no-cost architecture.

## Honest limitations

GitHub Actions *schedule* may be delayed, skipped, or disabled after 60 idle days. A public GitHub CI runner and sleeping free API cannot meet guaranteed 24/7 commitments. Remote notifications are at-least-once; a crash after provider acceptance may produce a duplicate. Real provider delivery, backup/restore, pilot incident drills and security hardening must be tested before allowing public customers.


## Real Free provisioning evidence (2026-10-26)

The following two web services were created using the **Render Free** plan; neither a paid Render worker nor Render PostgreSQL was created:
- `sitenobet-web-free`: https://sitenobet-web-free.onrender.com — first deployment LIVE.
- `sitenobet-api-free`: https://sitenobet-api-free.onrender.com — first deployment failed *securely* at start because the production `SESSION_SECRET` is not yet configured. Keep this failed-closed configuration until variables are entered in Render itself.

**Owner-only missing steps (never paste secrets in chat):**
1. Render Dashboard → `sitenobet-api-free` → Environment: configure `DATABASE_URL` with the dedicated Neon Free database URI and `SESSION_SECRET` with a securely random 32+ character secret. API should automatically migrate Neon schema on startup. Environment already has `APP_ENV=production`, `APP_ROLE=api`, `SCHEDULER_MODE=cron`, `CORS_ORIGINS=https://sitenobet-web-free.onrender.com`.
2. Save the Neon URL as `SITENOBET_DATABASE_URL` in GitHub Actions Secrets. The worker does **not** need the API's `SESSION_SECRET`; do not copy it to GitHub.
3. No Actions variable is required. The scheduled monitor starts only after `SITENOBET_DATABASE_URL` exists; until then the monitor job remains skipped. Trigger the workflow manually after adding the secret, and check that the worker job succeeds.
4. Validate API readiness, real login, consented test monitors and consented Telegram/ntfy channels. Do not enable public customer signup until full security review.

**Security limit:** Connected tools may refuse passing Neon credential values across apps. This is expected and should not be circumvented. Use each provider's own secret-setting UI and never expose values in issues or commits.

## 2026-10-27 — Reduced secret requirements

The worker uses PostgreSQL monitoring state and notification outbox, not JWT authentication. Production `APP_ROLE=worker` no longer requires `SESSION_SECRET`; the HTTP API still requires a cryptographically strong `SESSION_SECRET` in its own Render environment. The GitHub Actions worker requires only `SITENOBET_DATABASE_URL` (and optional `SITENOBET_TELEGRAM_BOT_TOKEN`). This avoids duplicating an unnecessary sensitive secret across services.

## 2026-10-27 — One less account setting

The GitHub Actions repository variable `SITENOBET_FREE_MONITOR_ENABLED` is no longer needed. The workflow has a separate configuration job that checks whether the dedicated `SITENOBET_DATABASE_URL` secret exists **without printing its value**. The actual monitor job is skipped until it is configured. This avoids asking for an unnecessary GitHub variable and keeps the 0-TL pilot safe while unconfigured.
