# T18: newest-posted order from an index, not a sort per request

Owner, 2026-10-04: "find the fastest way to sort" after T17 made Jobs filterable. Design only; build it in a later session.
Status: proposed. Needs the owner's yes before deploy (it migrates the live DB, see Deploy).

## What it costs today (measured on the box, 2026-10-04, read-only, 12,351 postings, 13,364 items, 578 sources)

`/api/opportunities` with the default `sort=posted` runs
`SELECT *, <posted key> AS sort_key FROM opportunities WHERE <owned EXISTS> ORDER BY sort_key DESC, id DESC`.

| Query (first 30 rows, best of 3) | Time |
|---|---|
| The real query: owned filter + posted sort | **394 ms** |
| Posted sort alone, no owned filter | 110 ms |
| Owned filter alone, no sort | 0.7 ms |
| Precomputed key in an indexed column + owned filter | **0.7 ms** |

`EXPLAIN QUERY PLAN`: `SCAN opportunities`, two correlated subqueries per row, then `USE TEMP B-TREE FOR ORDER BY`.

Why: `ORDER BY` an expression has no index, so SQLite must
1. compute the key for all n rows: a CASE with a correlated subquery into `items` (the seed check);
2. run the owned `EXISTS` (a 578-value `IN` list) for all n rows;
3. sort all survivors (O(n log n)) before it can return the first row.

The work is O(n log n), and it is paid per request even though the page needs 30 rows. Since 3b2fbe5 the API reads rows lazily, so this sort is the floor of every list request: 0.2 to 0.4 s of the 0.3 to 0.6 s total.

## The fix: a stored key with a B-tree index

Store the posted key in a column `posted_key` and index it on `(posted_key DESC, id DESC)`.
- **Reads:** SQLite walks the index in order and stops after the page. That is O(log n + r), where r is the number of rows inspected until the page fills (filters and the For you match run on those rows only).
- **Writes:** each write maintains the index in O(log n). That is noise next to a poll.

Measured: 394 ms becomes 0.7 ms for the SQL. A page of For you then costs only the Python per-row work for the r rows it walks. For you is 1,558 of 12,351, so r is about 240 rows for 30 cards, at about 0.25 ms each: roughly 60 ms in total.

### Alternatives considered and rejected
- **Top-k heap (`heapq.nsmallest`) in Python:** still computes the key for every row, so it is O(n), with the same 110+ ms floor.
- **Sorted list in app memory (bisect / skip list):** O(log n) inserts, and no schema change. But fixers (`fix-pages` changes `published_at`) and ad hoc SQL run in other processes, so the cache would go stale until a restart. An index can't go stale.
- **Generated column:** SQLite generated columns can't read another table, and the key reads `items` (the seed flag).
- **Python-maintained column, updated in `save_opportunity` / `upsert_item`:** misses other writers: fixer processes, one-off repair SQL, deletes. Use triggers instead.

## Build

All in `radar/store/__init__.py` unless noted. Reuse `SORT_KEYS["posted"]` verbatim as `<KEY>` below. It is written against
`opportunities.<col>`, so it works unchanged inside `UPDATE opportunities SET posted_key = (<KEY>) WHERE id = ?`. `MIGRATIONS` is defined above `SORT_KEYS`; move the posted expression to a constant above both.

1. **Migration** (append one entry to `MIGRATIONS`, it runs in the existing `BEGIN ... COMMIT`):
   ```sql
   ALTER TABLE opportunities ADD COLUMN posted_key TEXT NOT NULL DEFAULT '';
   UPDATE opportunities SET posted_key = (<KEY>);
   CREATE INDEX opportunities_posted ON opportunities(posted_key DESC, id DESC);
   CREATE TRIGGER opp_posted_ins AFTER INSERT ON opportunities BEGIN
     UPDATE opportunities SET posted_key = (<KEY>) WHERE id = NEW.id; END;
   CREATE TRIGGER opp_posted_upd AFTER UPDATE OF published_at, first_seen ON opportunities BEGIN
     UPDATE opportunities SET posted_key = (<KEY>) WHERE id = NEW.id; END;
   CREATE TRIGGER item_posted_ins AFTER INSERT ON items BEGIN
     UPDATE opportunities SET posted_key = (<KEY>) WHERE id = NEW.opportunity_id; END;
   CREATE TRIGGER item_posted_upd AFTER UPDATE OF raw, opportunity_id ON items BEGIN
     UPDATE opportunities SET posted_key = (<KEY>) WHERE id IN (OLD.opportunity_id, NEW.opportunity_id); END;
   CREATE TRIGGER item_posted_del AFTER DELETE ON items BEGIN
     UPDATE opportunities SET posted_key = (<KEY>) WHERE id = OLD.opportunity_id; END;
   ```
   The triggers' own `UPDATE ... SET posted_key` doesn't touch `published_at`/`first_seen`, so `opp_posted_upd` doesn't fire
   again (and `recursive_triggers` is off by default). Box SQLite is 3.45.1, so DESC indexes and triggers are fine.
2. **`iter_opportunities`:** when `sort == "posted"`, select `posted_key AS sort_key` and `ORDER BY posted_key DESC, id DESC`
   (name the column, not the alias, so the planner picks the index). Leave `found` and `prestige` on today's expressions:
   the UI no longer offers `found`, and `prestige` depends on per-user tiers (see Later).
3. **No change to the API handler.** It already iterates lazily and stops after `limit + 1` hits. Keep the cursor skip and the
   twin de-duplication from the top of the list as they are. They make every page agree on which copy of a twin is shown,
   and with the index, walking to page p costs O(30 p / selectivity) rows, which is fine. Don't switch to a SQL keyset
   (`WHERE (posted_key, id) < (?, ?)`): it would show the second copy of a twin whose first copy was on an earlier page.

## Tests (offline, `tests/test_store.py`)
- **The key stays right through every write path:** after an insert, a `save_opportunity` that sets `published_at`, a date-only
  `published_at`, a NULL date with only seed items, then a live item added, and an item deleted, assert for every row:
  `posted_key == (SELECT <KEY>)`.
- **Same order as before:** `list_opportunities(sort="posted")` returns the same ids in the same order as the old expression
  on a seeded store with ties, date-only rows and undated backfill rows.
- **The index is used:** `EXPLAIN QUERY PLAN` for the posted query contains `opportunities_posted` and no `TEMP B-TREE FOR ORDER BY`.
- **Migration:** opening a pre-migration DB (user_version before this entry) backfills `posted_key` for existing rows.

## Deploy (the owner's yes is needed: this writes the live DB)
1. Ask the owner, describing the change: one migration adds a column, an index and five triggers, and backfills 12k rows.
   It takes about a second, at the next `radar` start.
2. On the box: `python -m radar backup`, then the usual two-agent checks, rsync, and `sudo systemctl restart radar`.
3. Verify on the box:
   - `sqlite3 ... "PRAGMA user_version"` went up by one.
   - A read-only check that `posted_key` equals the expression for all rows prints 0 mismatches.
   - The scratchpad probe (`time3.py` style, 12 filter combinations) shows plain For you under 100 ms.
   - The ids of the first 200 For you and Everything rows are identical to the pre-deploy dump.

Rollback: the column, index and triggers are additive; the old code ignores them. Revert the code and restart.

## Beyond the index: where the rest of the time goes (measured 2026-10-04)

With the index, sorting is solved. The order is maintained at write time (O(log n) per insert), and a read is an index walk,
O(log n + k / selectivity). Every request has to read the k rows it shows, so no sort can do better. What is left on a filter change:

| Cost | Size |
|---|---|
| Network round trip, Mac to box (TLS reused) | 85-150 ms; more on a phone |
| Response body: **Caddy sends it uncompressed** | 39,122 bytes for 50 rows; 7,196 gzipped (5.4x smaller) |
| Python per row walked (fetch + match) | ~0.25 ms x r |
| Typing debounce (search, location only) | 250 ms |

So, in order of payoff per line of code:

0. **Compress responses (one line, do first).** Add `encode zstd gzip` to the site block in `/etc/caddy/Caddyfile`, then
   `sudo systemctl reload caddy`. Check: `curl -sI -H 'Accept-Encoding: gzip' .../api/opportunities` shows `content-encoding`.
   This is box config, not `radar.env` or the DB.
1. **The index above:** it removes the 394 ms server floor.
2. **For you filters on the device, no request (optional, after 0 and 1 are measured).** For you is 1,558 rows. The
   background recount behind `/api/opportunities/summary` already visits every row and decides match, level and track. Let
   it also keep the ordered list of For you ids, and serve `GET /api/opportunities/snapshot` with the full rows, about 220 KB
   gzipped. The web filters that array in place:
   - **Filtering:** a filter keeps a subsequence of an already sorted array, so it stays in order with no sort. Finding a
     page is O(k / selectivity), well under a millisecond for 1,558 rows. A filter change then costs one React render
     (~15 ms) instead of a round trip (~400 ms).
   - **Prestige:** the tier has 4 values, so it is a stable counting sort in O(n), with posted order kept within each tier.
   - **New drops from SSE:** insert by binary search on the posted key (`bisect`, O(log n) to find the spot).
   - **Everything stays server-side** (12k rows: ~1.7 MB gzipped full, ~330 KB with id, title and dates only). It is too heavy
     to ship to a phone on every visit.
   - **Ceiling:** the snapshot costs one full scan per active user every 5 minutes. That is fine for the owner, a friend and
     the guest. At hundreds of active accounts, store the match per user at write time (the pipeline already decides it per
     user when it alerts) instead of rescanning.

## Later (not in this task)
- **Rare filters still walk everything:** For you + Track: Quant has 7 hits in 12k rows, so r = n (about 1 s today, about 0.6 s after
  this change). Fix: store `level` and `track` columns, written by `Store` at write time (the rules are Python regexes, so no
  trigger), backfilled once, plus a partial index per value. Only worth it if rare filters stay slow.
- **Prestige** with an index: tiers are per user but only 4 values (0-3). Walk the posted index once per tier, highest first
  (`lower(company) IN (tier list)`, or `NOT IN (all listed)` for the default tier 1), and concatenate. No merge is needed, because
  tier order is primary.
- **`/api/opportunities/summary`** is a full scan by definition. It is now cached and recounted in the background, so the index
  doesn't help it.
