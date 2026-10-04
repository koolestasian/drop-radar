# T7: Instant alerts and latency metric
**Context:** 00-overview.md; T6 (Opportunity, matches_profile); existing ntfy_alert/github_issue.
**Goal:** the right phone buzz within seconds of persistence, no spam.
**Deliver:**
- Channel: ntfy (existing). GitHub issue (existing, optional) stays as-is.
- Rule: zero2sudo items and items where `matches_profile` is true -> push now; everything else is stored and visible in the Sheet only.
- Idempotent: alert row inserted BEFORE send with unique (opportunity, channel); retries safe; failures retried with backoff, never duplicated.
- Message: company, title, location, deadline, match reasons, one-tap Apply link, source + "seen Xs after posted".
- Latency metric: `drop_latency_s = alert_sent - published_at` (fallback first_seen), stored on the alert row; `python -m radar stats` prints p50/p95 per source.
**Accept:** fake channel; rule tests; no duplicate on retry; latency computed and stored.
**Deferred:** Telegram/Discord/email channels, `alerts.yaml` rule engine, quiet hours, digests. Add when ntfy alone is too noisy or misses you.
