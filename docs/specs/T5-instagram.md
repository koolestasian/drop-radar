# T5: Instagram, fast and multi-account
**Context:** 00-overview.md; T2; instagram_scraper.py (existing native client + Apify fallback in opportunity_monitor.py `scrape()`).
**Goal:** treat @zero2sudo as the top-priority source and allow a few more accounts (company recruiting pages, university orgs).
**Deliver:**
- Wrap existing client as `instagram.<username>` sources; accounts come from `config/watchlist.yaml`.
- Stories: one `reels_media` request can carry several user ids -> batch all accounts into one call per tick.
- Intervals: zero2sudo 60-120s with jitter; others 10-15 min. Stories live 24h, so 2 min is enough not to miss one.
- Session pool: multiple `IG_SESSIONID`s rotate per tick; a session that hits `auth`/`blocked` is benched with cool-down.
- Fallback: Apify only when ALL sessions are benched, rate-limited to 1 run/15 min.
- Reuse OCR, keep media-ID identity so nothing already tracked re-alerts.
- Cap: max 5 accounts; README states the ToS risk plainly.
**Accept:** fake client tests for batching, rotation, benching and fallback; identity test (native vs Apify same media id); interval jitter test.
