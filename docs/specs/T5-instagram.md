# T5: Instagram as a fast source
**Context:** 00-overview.md; T2; instagram_scraper.py (existing native client + Apify fallback in opportunity_monitor.py `scrape()`).
**Goal:** treat @zero2sudo as the top-priority source, polled continuously instead of hourly.
**Deliver:**
- Wrap the existing client as `instagram.<username>` sources; accounts come from `config/watchlist.yaml`.
- One `IG_SESSIONID`. `auth` -> disable + health alert (T2); `blocked` -> T2 cool-down.
- Interval from the watchlist (zero2sudo: 120s) with jitter. Stories live 24h, so this cannot miss one.
- Fallback: Apify only while the native source is disabled or cooling down, rate-limited to 1 run/15 min.
- Reuse OCR, keep media-ID identity so nothing already tracked re-alerts.
- Cap: max 5 accounts; README states the ToS risk plainly.
**Accept:** fake client tests for disable/cool-down and fallback rate limit; identity test (native vs Apify same media id); interval jitter test.
**Deferred:** session pool rotation and multi-account batching. Add when watching more than one account or one session keeps getting benched.
