# T1: Storage and migration (SQLite + views)
**Context:** 00-overview.md; T0 output (`radar/models.py`); workbook_records()/save_records() in legacy; enrichment_cache.json format.
**Goal:** SQLite becomes the source of truth; xlsx, LATEST.md and Google Sheet become generated views.
**Deliver:**
- `radar/store/` with one `schema.sql` (CREATE TABLE IF NOT EXISTS; add `PRAGMA user_version` migrations the first time the schema changes), WAL mode, a small repository API:
  `upsert_item`, `get_opportunity`, `mark_seen`, `list(filter)`, `record_alert`, `set_action`.
- `radar/store/migrate_legacy.py`: imports the 279-row workbook, keeping IDs, First Seen, Actioned?, Notes,
  and enrichment_cache.json. Idempotent (safe to re-run).
- `radar/views/`: regenerate Zero2Sudo_Opportunity_Tracker.xlsx and LATEST.md from the DB using existing writers.
- DB file lives in `data/radar.db`. Backups are T10.
**Accept:** migrate twice -> identical row counts/IDs; regenerated LATEST.md matches current one byte-for-byte on the migrated data.
**Out of scope:** Postgres (T10 notes the path).
