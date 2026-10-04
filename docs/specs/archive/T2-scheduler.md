# T2: Source framework and scheduler
**Context:** 00-overview.md (Source/Item contracts); T0 models/errors.
**Goal:** run many sources concurrently, each at its own pace, without one failure hurting others.
**Deliver:**
- `radar/scheduler.py`: asyncio loop; per-source `next_run` from `source_state`; jitter +-10%;
  exponential backoff on `transient` (cap 15 min); `blocked` -> cool-down 30 min; `auth` -> disable source + raise health alert;
  global concurrency limit and per-host rate limit (default 1 req/s/host).
- `FetchContext`: shared `httpx.AsyncClient`, `now()`, and `source_state` access so a source can keep its own ETag/cursor.
- `radar/sources/registry.py`: sources register by name from watchlist config.
- Health snapshot: per source last_ok, fail_count, last_error, items_24h.
**Accept:** fake sources test: slow source does not delay fast one; transient failures back off; auth failure disables and surfaces; clock injected so tests run in ms.
**Deferred:** adaptive intervals (poll faster after a drop). Add if latency numbers show drops cluster.
