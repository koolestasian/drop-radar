# Task progress

Update this file in the same commit that finishes a task. One line per task.
Status: `todo` | `doing` | `done` (with commit hash and date) | `deferred` (not planned; the note says when to add it).

| Task | Status | Notes |
|---|---|---|
| T0 foundations | done (999b3ee, 2026-09-30) | Suite is 87 legacy + 11 new = 98 (spec said 88; baseline was already 87). Root shims alias legacy modules. |
| T1 store | done (4797967, 2026-09-30) | `radar/store/` (schema.sql, Store repo API: upsert_item, save_opportunity, get_opportunity, mark_seen, list_opportunities, record_alert, set_action, enrichment), `radar/store/migrate_legacy.py`, `radar/views.py` (a module, not a package: one file). Real workbook has 282 rows (spec said 279); migrated twice with identical IDs/counts. Committed LATEST.md came from an older writer, so byte-for-byte is checked against the current legacy writer on the same rows and `now`: identical on real data and in tests. enrichment_cache.json is absent on this branch and main; migration skips it. Legacy pipeline still writes the xlsx directly; switching it to the store is T6. Real data gives 279 items for 282 opportunities (3 rows share a dedupe key in this pre-cleanup workbook): re-migrate from a cleaned main workbook at cutover; T5/T6 must not assume every opportunity has an item. T7: record_alert claims the slot before sending, so treat sent_at NULL as pending or a crash loses that alert. |
| T2 scheduler | todo | |
| T3 ats-sources | todo | |
| T4 community-sources | todo | |
| T5 instagram | todo | |
| T6 pipeline | todo | |
| T7 alerts | todo | |
| T8 api | deferred | Add when the Google Sheet + ntfy stop being enough to triage. |
| T9 web | deferred | Needs T8. Add when the Sheet hurts on a phone. |
| T10 deploy | todo | Trimmed to runner + one host; scaling notes deferred. |
| T11 hardening | deferred | Add after it has run live for a few weeks and real failures are known. |

## Decisions (defaults until the user changes them)
- Deploy target: systemd on a ~$5 VPS, no Docker (was: Docker on a VPS; changed 2026-09-30 in the plan trim). Home server is best for Instagram.
- Sources beyond the spec: none yet. Seed watchlist with ~300 companies at T3.
- Run independent tasks (T3, T4, T5) in fresh subagents; run the rest sequentially.
- Plan trimmed 2026-09-30: build only what cuts drop latency for one user. Each spec lists what was deferred and when to add it back.
