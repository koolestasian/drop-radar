# T7: Instant alerts and latency metric
**Context:** 00-overview.md; T6 (Opportunity, score); existing ntfy_alert/github_issue.
**Goal:** the right phone buzz within seconds of persistence, no spam.
**Deliver:**
- Channels: ntfy (existing), Telegram bot, Discord webhook, email (SMTP), GitHub issue (existing, optional). One `Channel` protocol.
- Rules in `config/alerts.yaml`: e.g. `score>=80 -> push now`, `company in tierA -> push now`, `zero2sudo -> push now`, `score 50-79 -> hourly digest`, else dashboard only. Quiet hours with override for tier A.
- Idempotent: alert row inserted BEFORE send with unique (opportunity, channel); retries safe; failures retried with backoff, never duplicated.
- Message: company, title, location, deadline, score reasons, one-tap Apply link, source + "seen Xs after posted".
- Latency metric: `drop_latency_s = alert_sent - published_at` (fallback first_seen); exposed per source on the health/metrics endpoint.
**Accept:** fake channels; rule engine tests; no duplicate on retry; digest batching; latency computed and stored.
