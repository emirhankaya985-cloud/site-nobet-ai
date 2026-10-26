# SiteNöbet AI — Development CI Acceptance (2026-10-26)

**Decision:** Development code and CI: **PASS**. Security: **PARTIAL**. Public production service: **NOT ACCEPTED / NOT DEPLOYED**.

## Confirmed evidence (GitHub)

- Repo: https://github.com/emirhankaya985-cloud/site-nobet-ai (public)
- Commit: `83d94891fbe673da20614d0a5805a1adc07e2502`
- GitHub Actions: https://github.com/emirhankaya985-cloud/site-nobet-ai/actions/runs/40280592303 — backend, frontend and Docker jobs all **success**.
- Default backend suite: **55 passed, 6 skipped**, 1 non-fatal warning; skip is intentional for PostgreSQL-only tests.
- Real ephemeral PostgreSQL 17 integration suite: **6 passed**. Tests cover concurrent claim, monitor stale lease, notification claim and stale lease, API tenant isolation, incident/recovery outbox isolation.
- PostgreSQL Alembic migration up → down → up: **success**.
- Ruff, mypy, Next.js lint/typecheck/test/build, two Docker builds: **success**.
- `pip-audit`: **No known vulnerabilities found** for the CI-installed dependency set.

## Fixes made

- Telegram success requires a valid positive `message_id` in `ok: true` response; HTTP 200 is insufficient.
- HTTP redirect chain and SSL DNS resolution use bounded overall deadlines.
- Monitor DB lease and notification delivery DB lease finalization verify ownership, discarding stale worker commits after a successor reclaims the item.
- The notification provider is mocked in tests; no messages were sent to real accounts.

## Not yet verified (NOT FULL PASS)

- No SiteNöbet Render web, API, background worker or database deployed. No paid resources created.
- No externally observed live Telegram or ntfy delivery; no end-to-end real outage/recovery drill.
- No independent external worker heartbeat watcher, backup + restore or seven-day pilot.
- No production-grade auth hardening: email verification, password recovery, HttpOnly cookie flow/CSRF and edge rate limits remain open.
- `main` protection was observed off, so protected merge workflow remains outstanding.
- Notification providers do not support atomic commit with this database. **At-least-once** delivery may duplicate on post-send worker crashes; lease fencing only prevents stale local DB overwrites.
- Cloud-host egress, multi-worker long-run stress, TLS real-world edge cases require dedicated acceptance.

## Follow-up tickets

- Production acceptance checklist: https://github.com/emirhankaya985-cloud/site-nobet-ai/issues/1
- Branch protection and secret metadata: https://github.com/emirhankaya985-cloud/site-nobet-ai/issues/2

**Zero-TL policy:** keep development and ephemeral GitHub CI tests free. Do not create billable Render services, paid Postgres, or send live customer notifications without explicit owner approval.

**Important project separation:** Overpass API failover and 🔴/🟢 lead classification belong to *Müşteri Avcısı AI*, not SiteNöbet AI.
