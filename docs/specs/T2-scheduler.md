# T2: Source framework and scheduler
**Context:** 00-overview.md (Source/Item contracts); T0 models/errors.
**Goal:** run many sources concurrently, each at its own pace, without one failure hurting others.
**Deliver:**
- `radar/scheduler.py`: asyncio loop; per-source `next_run` from `source_state`; jitter +-10%;
  exponential backoff on `transient` (cap 15 min); `blocked` -> cool-down 30 min; `auth` -> disable source + raise health alert;
  global concurrency limit and per-host rate limit (default 1 req/s/host).
- `FetchContext`: shared `httpx.AsyncClient`, conditional-request helper (ETag / If-Modified-Since, stored in `source_state`), `now()`.
- `radar/sources/registry.py`: sources register by name from watchlist config.
- Adaptive interval: a source that just produced items polls at 0.5x interval for 10 min (drops cluster); quiet sources drift to 2x, bounded.
- Health snapshot: per source last_ok, fail_count, last_error, items_24h.
**Accept:** fake sources test: slow source does not delay fast one; transient failures back off; auth failure disables and surfaces; 304 responses cost no items; clock injected so tests run in ms.
