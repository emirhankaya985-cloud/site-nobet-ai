# SiteNöbet AI — strict 0 TL production gate

## Absolute cost rule

The owner explicitly requires **zero TL**. **Do not create paid Render resources or change Neon/GitHub/Render plans.** Existing Free Neon project: `sitenobet-ai-free` (aws-eu-central-1). Render Blueprint in `render.yaml` now defines only two `plan: free` web services. GitHub Actions scheduled worker uses Free public-repo runners, subject to GitHub policy and reliability limitations.

## Existing technical evidence

- GitHub pipeline: https://github.com/emirhankaya985-cloud/site-nobet-ai/actions/runs/40288528400 — 3/3 CI PASS on free-scheduler commit `08f6300d`.
- Prior production-mode real-process and frontend HTTP startup gates: https://github.com/emirhankaya985-cloud/site-nobet-ai/actions/runs/40282414672 — PASS.
- API + DB + worker, worker failure/restart, cross-tenant access, frontend security headers, Docker, PostgreSQL integration and migration gates passed in ephemeral CI.

## Setup sequence (do not reveal secrets)

1. Existing Neon Free project `sitenobet-ai-free` has database `sitenobet`; copy its connection string using Neon Dashboard; never post it in chat or commit.
2. Owner configures GitHub Secrets: `SITENOBET_DATABASE_URL`, `SITENOBET_SESSION_SECRET` (and optional `SITENOBET_TELEGRAM_BOT_TOKEN`).
3. Owner sets GitHub Actions variable `SITENOBET_FREE_MONITOR_ENABLED=true`, then triggers the `SiteNobet Free Scheduled Monitor` workflow manually and verifies a successful log. GitHub schedule runs every nominal 15 min UTC and may be delayed or skipped.
4. Configure the two Render **Free** web services *only* after DB credentials and exact HTTPS origins exist. API: `APP_ENV=production`, `APP_ROLE=api`, `SCHEDULER_MODE=cron`, shared `DATABASE_URL` and `SESSION_SECRET`, `CORS_ORIGINS`. Frontend: `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_CHECK_INTERVAL_SECONDS=900`. Render Free web services may sleep and cold-start.
5. Limit to three monitors per organization at 900-second intervals and explicitly label as **free pilot**. Confirm authorized destinations for Telegram/ntfy. Check Neon quota usage regularly.

## Still required before full acceptance

- Actual authenticated user end-to-end dashboard and API access on HTTPS.
- Real user-approved test Telegram and ntfy notification and controlled outage/recovery.
- Independent watcher not hosted only inside the monitored worker itself.
- Tested backup/restore, retry/lease crash scenarios, auth hardening including email verification and password recovery.
- Seven-day observation period plus documented dropped/delayed GitHub schedule events and data staleness.
- GitHub main branch protection is off and should be enabled in repository Settings.

**Honest verdict:** free pilot can be functional, but uninterrupted 24/7 monitoring or guaranteed SLA is **not achievable reliably with the free scheduler and sleeping free API**. Do not mark FULL PASS based only on CI.
