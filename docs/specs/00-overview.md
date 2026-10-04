# Drop Radar: overview and shared contracts

Read this first, then only your task's spec. Everything shared lives here.

## Goal
Be the first to know when any relevant opportunity goes live: @zero2sudo Stories
(insider, highest priority), company career boards, community lists and feeds.
Measured by **drop latency** = alert_time - source_published_time.

## Honest limits
- Insider posts (Sudo's Stories) cannot be beaten, only matched: poll them fastest.
- Company ATS boards usually publish BEFORE anyone posts about them, so watching
  ~300 companies' boards directly is the biggest speed win after Sudo.
- Skip LinkedIn, Handshake and X scraping (login walls, ToS, bans). Instagram is
  a ToS risk already accepted for one secondary account; do not scale it past a
  handful of accounts.
- GitHub Actions cron is 5 min at best and often 15+ late: it cannot be the
  real-time engine. It stays as CI and a heartbeat fallback.

## Architecture
    sources (plugins) -> Item -> pipeline (dedupe, enrich, filter) -> store
                                        |                              |
                                        +--> alerts (push, instant)    +--> views (xlsx, LATEST.md, Google Sheet)
Runs as ONE always-on Python process (asyncio): scheduler + pipeline + FastAPI,
serving a React PWA. Users have their own watchlist/profile and application
statuses/notes; shared sources are polled once. First polls backfill already-open
ATS/list jobs silently; later matching postings trigger ntfy pushes and live drops.

## Package layout (created by T0)
    radar/
      config.py      settings + watchlist loading (YAML)
      models.py      Item, Opportunity dataclasses
      store/         SQLite (WAL) access, migrations
      sources/       one module per source, all implement Source
      pipeline/      normalize, dedupe, enrich, filter
      alerts/        channels + rules
      scheduler.py   per-source polling with backoff
    config/          watchlist.yaml, profile.yaml
    legacy: opportunity_monitor.py, job_pages.py, llm_extraction.py,
            instagram_scraper.py are MOVED into radar/, not rewritten.

## Contracts
```python
@dataclass(frozen=True)
class Item:                      # what a Source emits
    source: str                  # the emitting Source.name: "ats.greenhouse.stripe", "instagram.zero2sudo"
    external_id: str             # stable id within the source
    url: str                     # canonical link (apply link when known)
    title: str
    company: str = ""
    location: str = ""
    text: str = ""               # raw description / caption / OCR
    published_at: datetime | None = None   # when the SOURCE published it (UTC)
    seen_at: datetime = field(default_factory=utcnow)
    raw: dict = field(default_factory=dict)

class Source(Protocol):
    name: str
    interval_s: float            # base poll interval
    async def fetch(self, ctx: FetchContext) -> list[Item]: ...
    # Raises SourceError(kind="auth"|"blocked"|"transient"|"schema") so the
    # scheduler can back off correctly. Never returns partial results silently.
    # HTTP goes through `await ctx.get(url)` (per-host rate limit + global request cap).
    # fetch must not block the event loop: wrap sync code (requests, OCR) in asyncio.to_thread.
```
Identity: `opportunity_id = sha256(canonical_url or company|title|location)[:20]`;
an opportunity may have many items (one per source that saw it). The earliest
`seen_at` per opportunity is its **first_seen** and drives latency metrics.

## Database (SQLite, WAL) tables
`opportunities`, `items`, `source_state(name, etag, cursor, last_ok, fail_count,
next_run)`, `alerts(opportunity_id, channel, sent_at)`, `actions(opportunity_id,
status, notes, updated_at)`, `enrichment(key, json)`.

## Rules for every task
1. Tests first for the contract; offline (fixtures in tests/fixtures/<area>/).
2. No network in unit tests. Live probes are separate, marked `@live`, skipped by default.
3. Keep files under ~400 lines; split by responsibility.
4. Never weaken existing behaviour: IDs permanent, Actioned?/Notes preserved,
   alerts only after persistence, idempotent retries.
5. Update docs/ only for what you changed. Commit per task.

## Task graph
T0 -> T1, T2 -> (T3, T4, T5 in parallel) -> T6 -> T7 -> T8a multi-user -> T8b API -> T9 web -> T10 deploy
T10 -> T12 first to act -> T13 audit -> T14 email digest + priority push -> T15 UI (user-led)
T16 automation (independent; 16.5 feeds T14's priority list)
T15 -> T17 feed redesign (one Jobs screen; 17.4 defines "new" for T14's digest)
Deferred: T11 hardening (see PROGRESS.md for when to add it).
