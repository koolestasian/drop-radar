# T0: Foundations (package, config, models)
**Context to read:** 00-overview.md; opportunity_monitor.py top 120 lines (constants only).
**Goal:** create the `radar/` package skeleton and move legacy modules in without behaviour change.
**Deliver:**
- `radar/models.py` (Item, Opportunity), `radar/config.py` (env + `config/*.yaml`, validated, typed),
  `radar/errors.py` (SourceError with `kind`).
- `config/watchlist.yaml` schema: companies (name, ats, slug, tier), instagram accounts
  (username, interval_s, priority), feeds (url, kind), repos (owner/name, path).
- `config/profile.yaml`: target roles, grad year, locations, company tiers, keywords, exclude words.
- Move legacy modules into `radar/legacy/` with import shims so `python opportunity_monitor.py` and all 88 tests still pass.
**Accept:** `python -m unittest` still 88/88; `python -c "import radar"` works; config loader rejects bad YAML with a clear message.
**Out of scope:** any new source or DB.
