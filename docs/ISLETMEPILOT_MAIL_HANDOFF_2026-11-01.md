# İşletmePilot — no-downtime, no-re-send mail handoff

**Status:** data reconciled; outbound send remains disabled. This is not approval to turn SMTP on.

## Read-only evidence and additive data copy (2026-11-01)

- Source Neon: `musteri-avcisi-ai-review`, 50 leads (15 `email_sent`, 35 `review`).
- Target Neon: `sitenobet-ai-free`, 50 CRM leads. Source-id import inserted 15 then 0 on rerun. All 35 previously matched.
- Frozen 15 accepted SMTP claims match the old database by source ID, normalized recipient, full subject, and full body. No new SMTP sends occurred.
- Four Gmail delivery feedback facts (3 `failed`, 1 `delayed`) are linked to the original 15 claims, and prior Telegram receipt IDs are preserved. Replayed insertions inserted 0. SMTP accepted does **not** mean delivered.
- 15 historic recipients reserved in `business_recipient_guard`, insertion replay 0. 20 old `skipped` records were not converted into send permission. 15 newer leads remain `unknown`. One newer lead has an email address but **no mail authorization**.
- No reply feedback or rejected/deferred entries were recorded at audit time. Do not interpret absence as permission to send.

## Safe schema migration

The two **additive** target tables were created in Neon before the application deploy:
`business_mail_feedback` and `business_recipient_guard`. The target Alembic revision
remains `0004_owner_telegram_link` until deploy. The checked-in
`0005_business_mail_history` uses `checkfirst=True`; it is safe with already
populated tables and does not replace or delete prior CRM/claims/feedback.
The history importer reconciles frozen accepts and feedback in one transaction.
No mail is ever sent from the import.

Before any deploy: verify target counts and capture a read-only comparison with
source IDs and complete message fingerprints; keep the source and a database
restore point. In ephemeral CI, test migration, duplicate import and PostgreSQL
concurrent claims. Only then deploy the exact tested HEAD.

## Sender handoff — strict gates

1. Maintain legacy hourly **research**, owner Telegram digest and read-only Gmail
   delivery/reply watcher. Do not disable them as a group.
2. Ensure delivery failures/opt-outs/replies stay immutable and block recipient
   re-contact, including alternate source IDs. A reply does not imply consent.
3. `business_recipient_guard` is an **atomic shared-DB recipient exclusion table**.
   It is used by the new sender, and the PostgreSQL test exercises two
   independent simulated origins (`legacy`, `unified`). **The old repository
   is not yet wired to this table; a test does not magically protect a legacy
   process using another database.**
4. Keep `LEGACY_MAIL_WORKFLOW_DISABLED` **false/unset** and
   `BUSINESS_AUTO_MAIL_ENABLED` / `BUSINESS_PIPELINE_ENABLED` disabled.
   Before enabling the new sender, actually disable *only* the legacy SMTP
   path in the old repository, confirm no in-flight SMTP work, verify all
   old recipient claims/suppressions exist in the shared ledger and verify
   the bounce circuit root cause has been addressed.
5. Require a confirmed owner Telegram private-chat channel and verified GitHub
   secret presence (never print values). The new sender is fail-closed if these
   are missing; no random Telegram chat IDs.
6. Test one synthetic SMTP-free claim, same-address concurrency, recipient
   suppression, backup-slot idempotence, and delivery/reply watcher continuity.
   Enable a bounded real send only on explicit owner production authorization.
7. Watch first true schedule, SMTP acceptance records, Telegram message IDs,
   bounce rate and reply blocks. Stop senders immediately if any duplicate or
   missing historical claim is detected; leave scans/watchers running.

## Non-destructive rollback

Disable the **unified send flags only**; leave old send path disabled until
reconciliation is investigated. Keep research and read-only watcher running.
Roll API/web deployments back to the prior proven SHA
`95809a3bb0ff1b29713fc76647c6478061f211de`.
Both new tables and all copied facts intentionally **remain**; the Alembic
downgrade performs no deletion. Never delete recipient guards or requeue
`accepted`, `uncertain`, `failed`, `delayed`, `rejected`, `deferred`,
`reply`, or `opt-out` facts during rollback.

## Other modules

- A successful SiteNöbet free scheduler with `0` monitors and `0` checks
  proves scheduling and DB heartbeat only, **not** any actual website uptime.
  Do not seed example or guessed websites.
- The Google API integration for YorumPilot is absent. The offline language and
  complaint classifier can still be tested safely without claiming Google
  synchronization or auto-posting.
