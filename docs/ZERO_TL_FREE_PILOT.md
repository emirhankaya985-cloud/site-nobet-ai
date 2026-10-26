# SiteNöbet AI — 0 TL scheduled pilot (no SLA)

## Cost policy

**Only Free tiers. No paid Render worker or managed Render Postgres.** A GitHub Actions scheduled workflow drives bounded worker batches against the dedicated Neon Free project `sitenobet-ai-free`, now provisioned in Frankfurt. The website/API may be served by free hosting for a small pilot, but these providers can sleep, throttle, suspend, or have quotas.

This **cannot promise uninterrupted 24/7 monitoring, exact 15-minute checks or guaranteed delivery**. GitHub may delay/drop scheduled runs and disables cron in inactive public repositories after 60 days. Free Neon quotas may exhaust and pause database compute. Don't market this as professional-grade uptime.

## Setup

1. Keep the repo **public**. The dedicated **Free** Neon project `sitenobet-ai-free` has been created in Frankfurt with its own database `sitenobet`; do not reuse another project's database.
2. Configure GitHub repository **Actions secrets** (values go only in GitHub Secrets):
   - `SITENOBET_DATABASE_URL`: the dedicated Neon PostgreSQL connection string (TLS enabled).
   - `SITENOBET_SESSION_SECRET`: a high-entropy value 32+ characters, **also used by API if hosted**.
   - Optional `SITENOBET_TELEGRAM_BOT_TOKEN`: only your SiteNöbet bot, authorized test chat. Never reuse or print another project's tokens.
3. Set GitHub repository Actions variable `SITENOBET_FREE_MONITOR_ENABLED=true` **only after** secrets and database are ready. Until then scheduled runs are skipped without database access.
4. Initialize and migrate the dedicated DB as a separate explicit deployment action, or use the guarded bootstrap step in the scheduled workflow when first enabled.
5. Configure any hosted API with `APP_ENV=production`, `APP_ROLE=api`, `SCHEDULER_MODE=cron`, matching `DATABASE_URL` and `SESSION_SECRET`, and HTTPS `CORS_ORIGINS`. The frontend must be built with matching `NEXT_PUBLIC_API_URL` and `NEXT_PUBLIC_CHECK_INTERVAL_SECONDS=900`.
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
2. Use the **same SESSION_SECRET** as `SITENOBET_SESSION_SECRET` in the GitHub repo Actions Secrets. Save the Neon URL as `SITENOBET_DATABASE_URL` in GitHub Actions Secrets.
3. Then set Actions repository variable `SITENOBET_FREE_MONITOR_ENABLED=true`. A scheduled trigger was observed but skipped due to the disabled gate. Manually run the workflow and check success.
4. Validate API readiness, real login, consented test monitors and consented Telegram/ntfy channels. Do not enable public customer signup until full security review.

**Security limit:** Connected tools may refuse passing Neon credential values across apps. This is expected and should not be circumvented. Use each provider's own secret-setting UI and never expose values in issues or commits.
