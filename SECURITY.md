# Security policy — SiteNöbet AI

This is a development MVP. Do not invite real external customers, store sensitive production data, or represent this package as production-secure before pentesting and live acceptance. Only monitor websites you control or have permission to probe.

## Implemented safeguards

- Passwords hashed using Argon2id; signed 8-hour JWT bearer tokens.
- Server-side membership/role check for every tenant-scoped endpoint.
- Strict HTTP(S) URL checks; blocked private, link-local, loopback and cloud metadata IPs; DNS validation and IP-pinned aiohttp resolver; validation after redirects.
- Bounded outbound HTTP timeout and redirect count; no downloading bodies.
- Authorization-free Telegram webhook calls blocked by constant-time comparison with Telegram secret header; user chat IDs established only through short-lived, one-use link codes.
- High-entropy ntfy topics (access to topic must be treated like a secret).
- Durable outbox delivery with event deduplication + retry; a failure is not silently called success.
- No secrets included in source. Sensitive env vars must be injected at runtime.

## Known gaps / go-live blockers

- No email verification, password reset, SSO, session revocation, organizational invite system, IP allowlist management, or dedicated secrets vault.
- sessionStorage bearer tokens can be compromised by XSS; strict CSP and HttpOnly session cookie flow needed before public launch.
- API's database-based login limiter needs multi-worker stress validation and a stronger edge/WAF limiter. Other endpoints need global rate limits.
- Tenant and worker concurrency paths require adversarial PostgreSQL integration testing; SQLite tests alone are insufficient.
- No audited anti-abuse traffic quotas/egress cost guards, network egress firewall or independent security review.
- Externally-hosted ntfy.sh topics remain readable by anyone who learns their random topic name; confidential customers should use an authenticated ntfy instance.
- No formal backup/restore verification, automated dependency risk review or live penetration testing.

To report security issues, contact the repository owner privately; never disclose credentials in a public issue.
