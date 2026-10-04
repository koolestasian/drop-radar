# T17: one Jobs screen instead of Feed / New / All matches / All jobs

Owner, 2026-10-03: "redesign the feed, all job, new job, etc thing, i find that very confusing."
Status: proposed. Nothing here is built yet.

## Why it is confusing (measured on the owner's live feed, 2026-10-03)

Three lists show the same cards in nearly the same UI, and four things are called "new":

| What the owner sees | What it actually is | Live rows |
|---|---|---|
| Feed > **New** | matches that were not already open when a source started (`backfill=false`) | 64 (0 found in the last day) |
| Feed > **All matches** | every match, mostly backfill | 1,558 (1,495 backfill) |
| **All jobs** tab | everything every source found, match or not | 11,396 |
| Filters > **Ignored** switch | a fourth list, hidden in a filter sheet | 0 |
| Board | Saved / Applied / ... | 5 saved |

The word "new" means four different things:
1. The **New** toggle: not backfill, at any age.
2. The yellow **New** card colour: not backfill and found within the last 3 hours (`stock.ts`).
3. The **"N new drops"** pill: arrived over SSE since the page loaded.
4. A posting's **status** column, `New`.

On top of that, the 64 New rows and the 49 phone alerts the owner got are different sets:
- 41 are in both.
- 23 New rows never buzzed. All 23 were found before alerts started (2026-10-02 18:03 UTC), and every drop found since
  then has buzzed.
- 4 alerts went to rows now counted as backfill.

Other things that add to the confusion:
- Every card shows two dates, "posted" and "found".
- There are two "newest" sorts, posted and found.
- Three grouping layers stack: the view toggle, the track chips, and the Internships / New grad / Other sections.
- The track chip counts and the level sections are computed in the browser over only the 30 rows loaded so far
  (`Feed.tsx` `group()`, `track()`), so they change on every "Load more".

## What other job sites do (viewed 2026-10-03, public pages, logged out)

| Site | Pattern worth taking |
|---|---|
| Simplify `/jobs` | Top nav **Matches / Jobs / Job Tracker**. One list on the left and the posting on the right. Filters are one row of dropdown pills: Location, Job Type, Experience Level, Category. One age per row ("17 days ago"). A "Confirmed live in the last 24 hours" chip. |
| LinkedIn jobs (public search) | Recency is a **filter pill** ("Past 24 hours"), not a tab. One green age per row. "Set alert" saves the current search as an alert. |
| Intern-List | One table. "New" is a **counter**, not a list: "5042 New Openings Today / 75663 Total". The level (internships vs new grad) is the top nav. |
| SimplifyJobs GitHub list | One list sorted by **Age** (1d, 2d). Same-company rows are collapsed with an arrow. Closed roles live on a separate page. Category counts sit at the top. |
| Boardsweep | Shows the funnel as a sentence: "We read 300 jobs last night. You should apply to 6." |
| hiring.cafe | Not viewed: it showed a Cloudflare bot check. |

The common rules across these sites:
- There is **one list**.
- Scope and recency are **filters**.
- "New" is a **count**, or a marker on rows, not a separate place.
- Personal states (saved, applied, hidden) live in the **tracker**.

## The design

### Vocabulary (one meaning per word, used the same way in the UI, alerts and T14's digest)
- **For you**: matches your profile. Same rule that decides alerts (`visible_to`).
- **Everything**: every posting your sources found.
- **Drop**: a posting that appeared after its source was already being watched (not backfill). It is what alerts fire on.
- **New**: a drop you have not seen yet. It is new from your last visit on this device until you leave the page.
  This replaces the "found in the last 3 hours" rule for the yellow card.
- **Posted**: the date the posting gives (`published_at`). It is the only date on a card. "Found" moves to the detail panel.

### Screens
The nav goes from 5 items to 4: **Jobs, Tracker, Sources, Settings**. A guest sees only Jobs.

```
Desktop
+--------------------------------------------------------------------------------------+
| Drop Radar  * Live                          Jobs   Tracker   Sources   Settings   (o) |
+--------------------------------------------------------------------------------------+
| Jobs                                                                                  |
| 1,558 for you  .  11,396 found  .  12 new since Tue 3:10 pm                           |
|                                                                                       |
| [ For you | Everything ]   [ Search role or company                    ]  [=] rows    |
| (New 12) (Level: Intern v) (Track v) (Posted: Any time v) (Location v) (More v)       |
|                                                                                       |
| +-- list ---------------------------------+  +-- detail -------------------------+    |
| | [S] Stripe                    [Apply ->] |  | Stripe                            |    |
| |     Software Engineer, Intern (Summer 27)|  | Software Engineer, Intern ...     |    |
| |     San Francisco, CA . Intern . 1d ago  |  | [Apply on the company site ->]    |    |
| |     $50/hr          [save] [hide]        |  | Your status  Notes  Why it matched|    |
| | [N] NVIDIA  ...                          |  | Posted 1d ago . Found 1h later    |    |
| |   +3 more postings of this role          |  | Sources ...                       |    |
| +------------------------------------------+  +-----------------------------------+    |
+---------------------------------------------------------------------------------------+

Phone
+----------------------------+
| Jobs                       |
| 1,558 for you . 12 new     |
| [ For you | Everything ]   |
| [ Search ]   [Filters 2]   |
| (New 12)                   |  <- other pills live in the Filters drawer
| card                       |
| card                       |
|  Jobs  Tracker  Sources  Me|
+----------------------------+
```

- **Scope** is a two-part switch: For you (default) or Everything. It replaces the New / All matches toggle and the
  All jobs tab.
- **Filter pills**:
  - `New N`: drops since your last visit. It is highlighted when N > 0.
  - `Level`: Intern / New grad / Any.
  - `Track`.
  - `Posted`: 24 h / 7 days / 30 days / any.
  - `Location`: a text box plus "US only".
  - `More`: Closing soon, Drops only, and Sort (Newest posted / Most prestigious).
  - On a phone, every pill except `New` folds into the existing Filters drawer.
- **Filters live in the URL hash** (`#/jobs?scope=all&level=intern&posted=7`), so the back button, reloads and shared links keep them.
- **The list is flat**, sorted by newest posted. Level becomes a small badge on the card instead of a section. Same-role twins
  stay collapsed.
- **Quiet day**: if nothing is new, the `New` pill shows `New 0` greyed out, and the list shows the scope's normal results.
  There is no empty "New" screen to land on.
- **Tracker** (the old Board) gets a collapsed **Hidden** list at the bottom. That is where ignored roles go, so the Ignored
  switch leaves Filters.

### Old view to new filters (acceptance: reproduce each on the box)

| Old | New | Expected (2026-10-03) |
|---|---|---|
| Feed > New | For you + More > Drops only | 64 |
| Feed > All matches | For you | 1,558 |
| All jobs | Everything | 11,396 |
| Filters > Ignored | Tracker > Hidden | 0 |
| Track chip "Software" | For you + Track: Software | 1,016 (computed over all rows, not the loaded page) |
| "Internships" section | For you + Level: Intern | 1,112 (before the regex fixes in 17.1) |
| Sort > Newest found | removed from the UI (the API keeps `sort=found`) | n/a |

## Slices and dependencies

```
17.1 API: level/track/posted filters ──┬─> 17.3 filter pill row ──┐
                                       └─> 17.6 counts header     │
17.2 one Jobs screen ──────────────────┬─> 17.3                   ├─> done; T14 digest uses 17.4's words
                                       ├─> 17.4 one "new"         │
                                       └─> 17.5 Tracker > Hidden ─┘
```

17.1 and 17.2 can run in parallel. 17.3 needs both. 17.4 and 17.5 need 17.2 only. 17.6 is optional and comes last.

### 17.1 API: level, track and posted-within as server filters
**Context:** `radar/api/app.py` (the `/api/opportunities` handler), `web/src/screens/Feed.tsx` (`group`, `track`, `TRACKS`).
- Move the level and track regexes to Python, in one module, as the single source of truth. Add query params
  `level=intern|new_grad`, `track=<name>` and `posted_within=<days>` (on `published_at`), and return `level` and `track` on
  each item, so the web stops classifying.
- While porting, fix the misses seen live:
  - "2027 Grads" falls to Other: `grad` only matches after "new".
  - "Early Careers ..." falls to Other: `\bearly career\b` fails on the plural.
  - Diff the old JS classifier against the new one over all 1,558 matches and list every row that changes.
- Cost is already measured. A full scan with a filter that matches nothing takes 0.81 s on Everything and 1.36 s on For you,
  on the box. That is fine for one page. Do not add an index or precompute.
- Done when there are unit tests for both classifiers and the three params, the diff is listed in PROGRESS, and the API
  counts on the box match the table above.

### 17.2 One Jobs screen
**Context:** `web/src/App.tsx` (`ROUTES`, `GUEST_ROUTES`, the incoming badge), `web/src/screens/Feed.tsx`, `web/e2e/smoke.spec.ts`.
- Merge the Feed and All jobs routes into `#/jobs` with the For you / Everything switch, and keep the filters in the hash.
  `currentRoute()` in `App.tsx` matches the whole string after `#/` today, so it must strip `?...` before matching.
  Add an e2e test that reloads a filtered URL.
- `#/feed` redirects to `#/jobs`. A bare `#/jobs` with no query string is an old All jobs link, so it opens
  `scope=all`. The nav links to `#/jobs?scope=you`.
- Remove the New / All matches toggle and the Internships / New grad / Other sections. A level badge goes on the card
  (from 17.1, or the existing JS until 17.1 lands).
- Move the incoming-drops badge to the Jobs nav item. The "N new drops" pill shows whenever no search or filter is set.
- Rename Board to **Tracker** in the nav. The route `#/board` stays as an alias.
- Rewrite the e2e tests that use the old tabs: lines ~256-267 ("All matches" and "New" radios), ~284 (the screen list),
  ~310 (empty New feed), ~386-410 (All jobs), ~414 (track chips).
- Done when `npm run build` and `npm run e2e` pass, guest view still works, and the box shows 1,558 and 11,396 for the two scopes.

### 17.3 Filter pill row
**Needs:** 17.1, 17.2. **Context:** `Feed.tsx` (the filter sheet), `web/src/components/ui/` (dropdown-menu, toggle-group).
- Add the pills described above.
- The track and level chips take their counts from 17.6 when it exists. Until then they show no counts: a count over
  30 rows is wrong.
- Done when every pill changes the request (e2e asserts the query string), and on the box each Level and Posted option
  returns the count the API probe gives.

### 17.4 One meaning of "new"
**Needs:** 17.2. **Context:** `web/src/stock.ts`, `web/src/components/RoleCard.tsx`, `web/src/format.ts`, `Feed.tsx`.
- Last visit is stored per device in `localStorage`, read once on load and written when the page is hidden. If it is
  missing, it defaults to 24 h ago.
- The `New N` pill requests `backfill=false&since=<last visit>&include=matches`.
- The yellow stock means a drop found after the last visit, replacing the 3-hour rule. The header line reads
  "N new since <day time>".
- Show one date per card: Posted, falling back to "found" with the word spelled out when the posting has no date (5 of 1,558
  live). "Found" and the posted-to-found lag move to the detail panel only.
- Do not build "new" on `since` alone. The board-add flood put 11,267 of the 11,396 jobs inside the last 7 days, so a
  `since`-only "new" would show thousands after the next board add. The `backfill=false` part is what keeps it honest.
- Done when an e2e covers the last-visit cutoff and the quiet-day state, and on the box the New count equals the
  `backfill=false&since=` API count.

### 17.5 Tracker owns your statuses
**Needs:** 17.2. **Context:** `web/src/screens/Board.tsx`, `web/src/format.ts` (`BOARD_COLUMNS`), `Feed.tsx` (the filter sheet).
- Add a collapsed "Hidden (N)" section under the columns, using query key `["opportunities","board","ignored"]` so the
  existing invalidation covers it. Remove the Ignored switch from Filters.
- Done when the e2e test hides a role, finds it under Tracker > Hidden, and unhides it.

### 17.6 Counts header (optional)
**Needs:** 17.1.
- Add `GET /api/opportunities/summary`, which returns counts for: for you, everything, and per level and per track. It is
  cached 60 s per user, and is about one 1.4 s scan.
- The New count is not in the summary. Last visit is per device, so it would break the per-user cache. The `New N` pill
  keeps its own request.
- It feeds the header line ("1,558 for you . 11,396 found", plus the New count from 17.4) and the pill counts.
- The route stays on `current_user`; guests get the cached guest numbers.
- Done when the numbers on the box match the probe script.

## Open decisions (recommended default first; build with the default unless the owner says otherwise)
1. **Scope names:** "For you / Everything" [default], or "Matches / All jobs" (Simplify's words).
2. **Tracker or Board:** "Tracker" [default]. It says what the screen is for.
3. **Last visit:** per device in `localStorage` [default]. If the phone and the Mac disagree too often, move it to the
   server. That needs care: the owner is a `users.yaml` user with no `accounts` row.
4. **Remove "Newest found" from the sort menu** [default: yes]. "Drops only" covers what it was used for.
5. **New vs phone alerts mismatch:** out of scope here. The 23 rows that never buzzed all predate alerts. The 4 alerts on
   rows now counted as backfill go to the T13 audit.
6. **Landing view:** today the owner lands on New (64 drops). After this change they land on For you (1,558, mostly
   backfill), with `New N` highlighted.
   - [default] **Land on For you, and pre-select `New` when N > 0.** That puts the drops first on a busy day, and avoids an
     empty screen on a quiet one.
   - Or always land on For you.

## Not doing
- An AI match percentage (as in the archived T15 research: `match.reasons` already says why a role matched).
- Saved searches and per-search alerts (LinkedIn's "Set alert"): T14 territory.
- A table view with a column picker: compact rows already cover density.
