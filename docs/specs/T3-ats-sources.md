# T3: ATS watcher sources (the biggest speed win)
**Context:** 00-overview.md; T2 (Source, FetchContext); job_pages.py (existing Greenhouse/Lever/Ashby/SmartRecruiters parsing).
**Goal:** detect a new posting on a company's own board within minutes, before anyone posts about it.
**Deliver (one module each, shared `AtsSource` base):**
- greenhouse (`boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true`), lever (`api.lever.co/v0/postings/{slug}?mode=json`),
  ashby (`api.ashbyhq.com/posting-api/job-board/{slug}`), smartrecruiters, workable, recruitee; Workday via `/wday/cxs/{tenant}/{site}/jobs` (POST, paginated; note: 403s on some tenants, degrade to `transient`).
- Diff by `external_id` against stored set; emit only NEW ids (and removed ids -> `closed` signal for T6).
- Title filter at the source (cheap): keep intern/new grad/early career/residency/fellowship/apprentice/co-op/2026-2028; drop the rest. Emit `published_at` from API when present.
- `radar/sources/discover.py`: derive board slugs from existing tracker links + a seed list of ~300 companies in `config/watchlist.yaml`; `python -m radar.sources.discover --check` verifies every slug returns 200.
- Default interval: tier A companies 120s, tier B 300s, tier C 900s; one request per board.
**Accept:** fixtures for each API; first poll seeds state WITHOUT alerting (no backlog flood); second poll with one new job emits exactly one Item; removed job emits closed signal; bad slug -> `schema` error, not a crash.
