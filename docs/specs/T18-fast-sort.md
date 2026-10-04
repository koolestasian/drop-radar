# T18: answer the Jobs list from a bitmap index, not a sort and a scan per request

Owner, 2026-10-04: "find the fastest way to sort" after T17 made Jobs filterable. Design only; build it in a later session.
Status: **built as Option A, live 2026-10-04** (see "As built" below; the rest of this file is the design it was built from).
Original status: proposed. **Build Option A** (no DB change, so no owner's yes needed for data). Option B, the SQL index, is the
fallback if A is rejected. Step 0 (compression) applies either way.

## As built (2026-10-04)

`radar/api/bitindex.py` (about 260 lines, stdlib), wired into `list_opportunities` and `summary` in `radar/api/app.py`, tests in `tests/test_bitindex.py`.
Where it differs from the design below:

- **Refresh policy.** `PRAGMA data_version` never rests (the poller commits all day) and a refresh costs about 0.6 s on the box (every scan piece is 100-200 ms of Python row iteration), so refreshing on each change would eat the CPU. A refresh runs on `EventBus` "opportunity" events (`index.nudge()`, at most every 5 s; only live drops publish one, seeds do not) and every 60 s; the per-row signature diff means an unchanged posting is never recomputed. A nudge bumps `wanted`; a finished refresh records the `wanted` it started under (`snap_gen`) and each view records the `snap_gen` it was built at (`gen`). A view with `gen < wanted` is not served: the request reads SQL, so a list opened right after a drop's push can never miss it (before this, the 60 s tolerance applied to drops too; found by review, covered by a production-shaped test). A nudge also catches up every view that exists. A scan takes 2-6 s on a busy box (logged per refresh). First build after a restart: 6 s for the snapshot, then 15-40 s per user for the matches (12k `get_opportunity` + `visible_to`, with naps), about 75 s in all for the configured users and the guest. Self-service accounts build on their first request (at the 300-account cap, prebuilding all would be an hour of CPU and, at about 2 MB each, a large share of 954 MB). SQL answers meanwhile.
- **Twins are per user and per backfill filter.** The SQL path dedupes after the owned and `backfill` filters, so a user who owns only the older copy still sees it, and `backfill=false` picks the newest copy among drops. `UserView.shown` holds one mask for each of None, False, True.
- **`posted_within` is not a prefix of the order.** The list tests the posting's own date in its own UTC offset (and a live drop's first-seen date), which can disagree with the UTC sort key near midnight. The index builds that mask per cutoff date and per user, and caches it.
- **Prestige is supported** (tier masks, cursor `"<tier>|<key>"`); the ranking is cached per user object because canonicalising 800 watchlist names costs 40-80 ms on the box.
- **Hides are read per request** from `actions`, not kept in the index. `sort=found`, `since`, `source`, `status`, `action` and `closing_within` stay on SQL.
- **Measured on the box** (best/median/max over 15 requests, 30 rows, steady state): For you 11/12/66 ms, intern + Software 11/13/76, Quant 4/5/29, Everything posted 7 days + new grad 12/13/58, prestige 10/12/102, location 14/17/241, `q=analyst` 17/20/172, summary 2-34/9-135/280-590 ms. Before: 0.4-1.4 s per list, 6-30 s per summary. The tails are the poller's bursts, not the index: the scheduler parses on the same event loop, and during a burst (170-215 log lines per 10 s against 70-130 between) `/api/me` itself had a 163 ms median and the lists 150-250 ms; as the burst faded (71 lines) `/api/me` was 2 ms and the lists 5-24 ms again. No index scan or build overlapped those windows (checked in the per-refresh log). So the 20 ms target holds only between bursts; moving the poller's parsing off the loop is a separate task. Page serialization (30 rows of `get_opportunity` + `serialize`) is now the floor, about 10 ms.
- **Not done:** step 2 (For you filtered on the device, no request): the server side is now fast enough that it is optional.

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

## Option A (recommended): an in-memory bitmap index

Measured with `docs/specs/t18-bitmap-bench.py`, run against the live dump of 11,396 jobs. Python 3.12 stdlib only, Mac.

| Question | Today on the box | Option B (SQL index) | Option A (bitmaps) |
|---|---|---|---|
| For you, first 30 | 0.44 s | ~60 ms (est.) | **9 us** |
| For you + Intern + Software, first 30 | 0.38 s | ~60 ms | **9 us** |
| For you + Quant (7 hits in 12k) | 1.2 s | ~0.6 s | **2 us** |
| Everything + posted 7 days + New grad | 0.36 s | ~10 ms | **10 us** |
| Header and all 24 pill counts (`/summary`) | 6-30 s scan | same scan | **11 us** (popcounts) |

Cost: the build from rows already in memory is 100 ms (pure Python, regex classify included). From the DB, with the per-user
match, it is ~3 s, measured as 12k x (`get_opportunity` 0.18 ms + `visible_to` 0.05 ms). Each bitset is 1,424 bytes.

### The data structure
Number the postings by sort order, **oldest first**: position `i` is the i-th oldest by `(posted key, id)`, so the newest has the
highest position. Each attribute is one Python `int` used as a bitset, with bit `i` set when posting `i` has it.
(Python ints do bitwise AND/OR/XOR and `bit_count()` in C over 64-bit words; at 12k bits that is ~190 words per op.)

- `keys`: the sorted list of `(posted_key, id)`. `ids[i]`, `title[i]`, `company[i]` and `location[i]` are plain parallel lists.
- Global bitsets: `level:intern`, `level:new_grad`, `track:<name>` x10, `drops` (not backfill), `us` (confirmed US),
  `dead` (Closed/Expired...), `twin` (every copy of a company+title+location except the one the list shows: the newest).
- Per user: `owned` (seen by one of the user's sources), `you` (`visible_to(...).ok`), `hidden` (the user's `ignored` actions).
  The guest is a user with the guest profile.

### The algorithms
- **Filter:** AND the bitsets. `mask = owned & ~dead & ~twin & ~hidden [& you] [& level:x] [& track:y] [& drops] [& us]`.
- **Sort:** none at read time. The order is the bit numbering.
- **Page:** take set bits from the top: `i = mask.bit_length() - 1; mask ^= 1 << i`, 30 times. That is O(k x n/64) word ops.
- **Cursor (next page):** the cursor stays `(sort_key, id)`. Find its position with `bisect` on `keys` (O(log n)), then
  `mask &= (1 << p) - 1`. Deep pages cost the same as page 1, and twins stay consistent because `twin` is global.
- **Posted within N days:** postings are numbered by posted key, so "posted since D" is a contiguous top range. Find it with
  `p = bisect_left(keys, (D,))` and AND with `~((1 << p) - 1)`. O(log n), with no per-row date parsing.
- **`since` (the New pill):** that is `first_seen`, which is a different order. Keep a `first_seen` per position and test the
  few candidates the other filters leave, or, simpler, keep the New pill on today's SQL path (it is already 0.1 s).
- **Text search (`q`, `location`):** after the bit filters, walk the remaining set bits newest-first and test the strings
  until 30 match. That is O(r) string checks at ~1 us each, so it needs no inverted index at this size.
- **Counts for `/summary`:** `(scope & bitset).bit_count()` per pill. 24 popcounts take 11 us, which replaces the background scan.
- **Prestige sort:** tiers are 4 values. Walk the mask once per tier, highest tier first (`mask & tier_bits[t]`). This is a
  bucket sort over the existing order, O(n/64) per tier.

### Keeping it current (the hard part)
- **Startup:** build in a worker thread with its own read connection (like the summary scan today), ~3 s. Until it is ready,
  the API uses the current SQL path, so the service is never down.
- **New posting from the pipeline** (the common case: newer than everything) gets position n, a new highest bit, set in
  O(1) per bitset with no shifting.
- **Out-of-order posting** (backfill, or a date filled later): insert at position p and shift the bits above it,
  `x = ((x >> p) << (p + 1)) | (x & ((1 << p) - 1))`, for each bitset. That is O(n/64) words each, microseconds for ~30 bitsets.
  `bisect.insort` the key.
- **Status change** (PATCH status) sets or clears the user's `hidden` bit. **Profile change** (Settings) rebuilds that user's `you`
  in the background, ~3 s.
- **Writes by other processes** (`fix-pages`, `fix-pay`, repair SQL): poll `PRAGMA data_version` once per request (it costs
  microseconds). It changes only when *another* connection commits, so the app's own writes don't trigger it. On a
  change, rebuild in the background and keep serving the old index until the new one is swapped in. See
  https://www.sqlite.org/pragma.html#pragma_data_version
- **Twins:** on insert, look up a `twin_key -> positions` dict, and recompute `twin` bits for that group only, so the newest copy is the one shown.
- **Hook point:** Store writes are in `save_opportunity` and `upsert_item`. Call `index.touch(opportunity_id)` after commit;
  it re-reads that one row and moves or sets its bits.

### Code shape (ponytail: one module, stdlib only)
- `radar/api/bitindex.py`, ~150-200 lines. Build, `touch(id)`, `page(user, filters, cursor, k)`, `counts(user)`.
- `list_opportunities` uses it when it is ready and the request has no `since`, `company`, `source` or `status`; otherwise it
  falls back to the SQL path. `summary` uses `counts()`. It then fetches only the 30 page rows (`get_opportunity` x 30 is ~5 ms).
- **Don't add pyroaring/Roaring.** Compressed bitmaps pay off at millions of ids. At 12k, a plain int is 1.4 KB and
  already microseconds. Reconsider only past ~1M postings. See https://roaringbitmap.org/about/ and Lemire et al.,
  "Better bitmap performance with Roaring bitmaps", https://arxiv.org/abs/1402.6407

### Tests (offline)
- **Same results as today, whole list:** for a seeded store with twins, hidden rows, dead rows, date-only rows and undated
  backfill, `page()` across all pages yields exactly the ids and order the SQL path yields, for every combination of
  scope x level x track x drops x posted_within.
- **Counts:** `counts()` equals the paged totals per scope, level and track.
- **Inserts:** an out-of-order insert, a new twin, an unhide and a write from another connection (data_version) all show up correctly.

### Scripts (in `docs/specs/`, run from the repo root)
- `t18-dump.py <matches|all>`: pages the live API on the box and prints one JSON line per row. It reads the token from
  `radar.env` and never prints it. Run it through ssh:
  `ssh drop-radar "sudo -u radar bash -c 'set -a && . /opt/radar/radar.env && set +a && python3 - all'" < docs/specs/t18-dump.py > DIR/all.jsonl`.
  Do the same for `matches`. Keep the dumps out of git (scratchpad).
- `t18-bitmap-bench.py DIR`: the benchmark above, run on those two dumps.
- `t18-timing-probe.py`: times 12 filter combinations through the live API (same ssh pattern, no argument). Run it before
  and after the change.

### Verify on the box
- Dump For you and Everything (all pages) through the API before and after the change: identical ids and order.
- Timing probe: every filter combination under 20 ms end to end on the server; `/summary` under 20 ms after startup.
- RSS of `radar` before and after: expect only a few MB more (per-row strings plus about 1.4 KB per bitset).

## Option B (fallback): a stored key with a B-tree index

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
