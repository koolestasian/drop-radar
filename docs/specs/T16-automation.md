# T16: automate the trivial work instead of hardcoding it

Owner's goal (2026-10-03): stop hand-maintaining lists (logo overrides, company names, location
words, watchlist slugs, tiers) and hand routine judgment to a cheap model or a public data source.
The plan was approved as a whole. Build it as small, separately deployed slices.

## The pattern every slice follows
1. **Source fact.** Use what the posting or board already says. It's free and the most trustworthy.
2. **Free lookup.** Wikidata, the YC directory, GeoNames, Clearbit.
3. **Cheap LLM.** Use one only for what is still unknown.
4. **Verify.** A real fetch or data check must agree before anything is stored.
5. **Fallback.** Show a monogram or "unknown", and retry later. Never cache a miss forever.

Store each answer with its provenance: `source`, `verified`, `checked_at`, and a version.
Fixers only **fill**, never overwrite a value a source stated clearly (the same rule as `pagefacts`).

## Constraints
- **The box:** 954 MB RAM, 2 vCPU. No local models, no headless browser, and no large dataset
  held in memory. Batch jobs run off-box: on the Mac, as a scheduled cloud agent, or as a GitHub
  Actions cron.
- **Source rule:** an honest User-Agent, and only documented APIs or paths that robots.txt
  allows. Reuse `pagefacts._get` / `_robots_allows` for every new fetch, since they are
  SSRF-guarded.
- **Owner's yes:** writes to `radar.env`, live-DB repairs and deploys each need the owner's
  explicit yes. Two agents deploy to the same box, so follow `CLAUDE.md`'s pre-deploy checks.
- **Existing guarantees still hold:**
  - row IDs are permanent;
  - `Actioned?`/Notes are never overwritten;
  - alerts go out only after data is persisted.

## LLM choice (decided, 2026-10-03)
**Claude Haiku 4.5 is the model.** Gemini is used only where it can't hit its free-tier rate
limit; in practice, as the fallback when Haiku fails (owner's call).

The bake-off ran on Drop Radar's own data. The harness is `data/bake/` (gitignored):
`bake.py run|report`.

| Model | Result |
|---|---|
| Haiku 4.5, Sonnet 5.5, Gemini 3.1 Flash-Lite, Gemini 3.5 Flash-Lite | Tied on Stories (company 22-23/23, city and date near perfect) and on page facts (company 36-37/40, pay 16/19). |
| Gemini free tier | Stalled 60-180 s on about 5% of calls. Gemini 2.5 Flash-Lite is closed to new users. |
| Haiku | Never took more than 3.5 s. |
| GPT-5.6 Luna | Untested: the OpenAI account has no credit. |

**Jev (TypeSafe), added 2026-10-04 (owner's go):** used only for typed decisions (pick a tier,
answer yes/no), never for extraction, because it can't quote text back. Haiku stays the
extraction model. First use is 16.5 priority, calibrated against Haiku before it goes on.

**Haiku gotchas:**
- Haiku 4.5 **rejects the `effort` parameter** (it returns a 400).
- The legacy extractor (`radar/legacy/llm_extraction.py`) sends `effort` and the
  `server-side-fallback` beta, and its model defaults to **Opus 5.5** (`ANTHROPIC_MODEL`).
- LLM guesses must pass the homepage check. Haiku invented 6 name-shaped domains that don't exist.

**Keys:**
- On the Mac: `~/.config/drop-radar/llm.env` (mode 600).
- On the box: `ANTHROPIC_API_KEY` has been set since 2026-10-03, together with
  **`LLM_EXTRACTION=off`**, so the legacy Story extractor stays off. Backup:
  `radar.env.bak-pre-anthropic`.

## Slices

| # | Slice | Status |
|---|---|---|
| 16.1 | Logos: verified ladder | **done, live**; `fix-logos` ran for real 2026-10-03 21:35 UTC (owner's yes): 110 changed, report `/opt/radar/data/fix-logos-run.txt`, backup `backups/radar-20261003T212612Z-pre-fix-logos.db` |
| 16.2 | Delete `filter.py`'s location lists | **done, live** (5761717, deployed 2026-10-03 20:43 UTC) |
| 16.3 | Turn the LLM on: Stories, junk titles, pay | **Stories + junk titles done, live** (ca347fe, 2026-10-04 02:04 UTC; `LLM_EXTRACTION=on`, model Haiku 4.5, images read, memes hidden when the Story has no apply link). `fix-stories` ran live 2026-10-04 02:12 UTC: 22 rows fixed (backup `backups/radar-20261004T021118Z-pre-fix-stories.db`). Pay range from fetched page text via Haiku done (6006a83, 2026-10-04, v0.17.0): verified quote/amount/currency/period, shared daily budget, content cache, background calls, Gemini on API failure. Off-box sample: 4 model + 1 regex fills/20 blanks. Approved live backfill added 33/2,403 (31 Haiku + 2 structured/regex); owner stated pay 349 → 360. Owner-approved Codex cached-text completion added another 164 globally; owner feed now 412 stated. Separate BLS/WageDex US-wide estimates show only where employer pay is blank; 851/1,209 blanks covered on owner's live feed (deployed 2026-10-04 03:26 UTC). |
| 16.4 | Self-growing watchlist + review queue | **done** (2026-10-04, this commit, v0.16.0): stored-link, YC and pinned aggregator queues; Settings careers URL detection; daily off-box repair/archive review queue |
| 16.5 | Adaptive polling + learned priority | **done, live** (2026-10-04, this commit); automatic CS-student tiers, budgeted refresh and posting-hour polling (feeds T14) |
| 16.6 | Learn from the user | **done, live** (`b47049c`, `46afaae`, 2026-10-04), v0.19.1; schema 5 and live feed verified |
| 16.7 | Maintenance by agent | todo |
| 16.8 | Company names from source data | todo |

### 16.1 Logos (done: commits 168780a, e713cdd, eee8958; live since 2026-10-03 20:18 UTC)

**How it works now** (`radar/logos.py`):
- **Rungs, in order:** the posting's JSON-LD `hiringOrganization` (`pagefacts.org_site`), then
  Wikidata (SPARQL, with a 10-minute back-off on 429), then Clearbit autocomplete, then Haiku given
  the posting's link and title (with Gemini as fallback).
- **What gets accepted:**
  - a homepage `<title>`/`og:site_name` that names the company in **whole words**; or
  - for non-LLM sources only, a domain that equals the name on a commercial ending
    (`rocketlabusa.com`).
- **What never gets accepted:** job-board or social hosts.
- **Retries:** misses retry after 7 days. A result from an older ladder (`v` != `VERSION`) is
  retried. A lookup where a rung crashed is not cached.
- **Measured** on the 202 live misses (from the Mac, read-only): about 118 recovered, which takes
  logo coverage from 79% to about 91%.

**Still to do:**
- **`fix-logos` (ran 2026-10-03 21:35 UTC; 15 replaced, 95 filled).** Doubtful fills the owner accepted, fix by hand if wrong:
  Rollout -> rolloutpolice.com, Icon -> icon.me, Arch -> arch.com, Zip -> zip.co, Cogna -> cogna.com.br, POET -> poet.com,
  Realm -> realmalliance.com, Mill -> mill.com, PMG -> pmg.com, Jobsbridge -> jobsbridge.com. Known wrong and kept: Hatch IT -> deallink.io.
  `python -m radar fix-logos [--dry-run]` checks every company, replaces cached
  domains whose homepage names someone else, and fills misses. The **dry run ran on the box**, and
  its report is in `/opt/radar/data/fix-logos-dryrun.txt`.
  **That report came from the old code: do not run the real write from it.** The old code would
  drop 19 domains, nearly all correct (rbc.com, principal.com, simon.com, kodiak.ai), to monograms
  because their titles don't spell the full name. Since 23c3da2 a cached domain is replaced only
  by a better one (so Hatch IT keeps the wrong deallink.io). Deploy 23c3da2, run a fresh dry run
  (the LLM rows can change), and show the owner the risky fills: Zip -> zip.co,
  Rollout -> rolloutpolice.com, Icon -> icon.me, Arch -> arch.com, Mill, POET, Realm, Jobsbridge,
  Cogna -> cogna.com.br, Fox -> foxcareers.com.
  1. Show the owner the replacements first.
  2. Run it without `--dry-run` only after the owner says yes, since it writes to the live DB.
  3. Run it as `sudo -u radar bash -c "cd /opt/radar/zero2sudo-opportunity-monitor && set -a &&
     . /opt/radar/radar.env && set +a && .venv/bin/python -m radar fix-logos"`.
- **Bad company names:** some names came from URL slugs ("Boxinc", "Ashbyhq" which is really
  Quora, "Acuityinc"), so their logos are wrong or missing. See 16.8.
- **Wikidata:** the rung was rate-limited during every test, so it is unproven. If it stays
  blocked, switch it to the Action API (`wbsearchentities` + `wbgetentities` P856, at 1 req/s).
- **Optional:** Brandfetch's CDN with `fallback/lettermark` could replace the 16px-globe hack in
  `web/src/components/common.tsx` `CompanyLogo`. It needs a free client ID.

### 16.2 Delete the duplicate location lists (done: 5761717, live since 2026-10-03 20:43 UTC)
**Done:** `is_us_location` reads `places.parse_places` (and `scan_countries` for free text the
parser can't structure). A bare city whose biggest namesake is abroad but which is also a US city
over 40k (Cambridge, Dublin) is unknown. So is a list with an unplaceable place next to a guessed
one ("Poughkeepsie; Kingston"). A free-text scan rules a place out only on a country or state name,
never on a lone city ("George Bush International Airport"). Puerto Rico counts as US.
**Gate report:** `data/t16/16.2-location-diff.txt` (gitignored, on the Mac). Over 3,610 stored
locations: 161 unknown -> US, 83 unknown -> abroad (the direction that can miss a drop; check
"Kingston" x2, likely Kingston NY, and "Moscow", maybe Idaho), 32 abroad -> unknown, 3 US -> abroad
(all really Vietnam/Mexico). Display changes: 72 locations, mostly fixes. Accepted regressions:
"Remote-LA" x4 now shows "Remote, United States" instead of "Los Angeles, CA".

**Original plan:**
- **What's duplicated:** `radar/pipeline/filter.py`'s `_US_CITIES`, `_NON_US`, `_US_NAMESAKES`
  and `_COUNTRY_RE` (about 400 hand-typed places) repeat what `radar/pipeline/places.py` (GeoNames)
  already resolves.
- **Change:** the US check uses `places.py`'s country.
- **Gate:** run a script over **every stored row** that prints each row where the old and new
  verdicts differ. The owner reviews the diff. Tests missed every real problem before.
- **Optional follow-up:** send the roughly 7% of places `places.py` can't resolve to Haiku, and
  validate its answer against GeoNames.

### 16.3 Turn the LLM on (needs the owner's yes to flip `LLM_EXTRACTION`)
1. **Fix the legacy extractor for Haiku:** no `effort`, no fallback beta. Set
   `ANTHROPIC_MODEL=claude-haiku-4-5` explicitly. The daily token budget in `enrich.py` stays.
2. **Story images:** Haiku vision, with tesseract as the fallback. Haiku scored 27/28 on
   opportunity vs not and 23/23 on company in the bake-off.
3. **Junk titles** ("Other Opportunity · 2026"): rewrite them only when the title matches a
   generic pattern.
4. **Pay range and blank facts:** extract them from page text pagefacts already fetched, and only
   fill blanks. **Pay built:** source/API descriptions retained in the existing page cache;
   Haiku runs only after structured/regex pay misses. Exact quoted evidence, amounts,
   explicit currency and period, base-pay context and plausibility are checked. Rejects
   estimates, bonuses, equity and total compensation. Calls reserve against the existing
   daily Story token budget before yielding; cache is keyed by text/version with model,
   evidence and check time. Unknowns retry after seven days, failed calls next time.
   Gemini runs only on Haiku failure and pauses ten minutes after 429. Alerts never wait
   for the model. `fix-pay --dry-run` reads cached model evidence only and writes nothing;
   an uncached model backfill is a real run requiring owner approval and a backup.
   Live sample: `data/t16/16.3-pay-live-sample.json` (20 owner blanks, 4 Haiku + 1 regex,
   15 still blank). Approved live backfill on 2026-10-04 filled 33/2,403 eligible rows
   (31 Haiku, 2 structured/regex), plus two blank source deadlines. Backup:
   `backups/radar-20261004T073856Z-pre-haiku-pay.db`. All 685 pre-existing pay values,
   IDs, first_seen and user notes/actions unchanged. Owner feed: 360 stated/1,198 blank,
   was 349 stated on the same 1,558 IDs. Budget stayed intact (193,287 tokens today);
   remaining blanks were not all model-read in that first pass.
   **Codex completion, owner-approved 2026-10-04:** background Sol-low batches reviewed
   compact pay excerpts from retained pages and filled 164 more rows (152 unique texts).
   Source quote/amount/currency/period and current source hash checked before each atomic
   blank-only Pay write. Thirty invalid proposals rejected. Backup:
   `backups/radar-20261004T154908Z-pre-codex-pay.db`; all 746 existing paid rows, other
   fields/columns, IDs and notes/actions preserved. Owner feed now 412 stated/1,166 blank
   across 1,578 rows (360 stated before on the same IDs). No extra Haiku spend or cap change;
   automatic enrichment stays Haiku. Artifacts: `data/t16/codex-pay/`. Cached-text review
   is finished; missing pages and unverified/ambiguous pay remain blank.

### 16.4 Self-growing watchlist (everything goes to a review queue, never straight to live)
**Settings (built):** a signed-in user pastes a public careers/job-board URL and clicks
"Check careers URL". The server detects Greenhouse, Lever, Ashby, SmartRecruiters or
Workday, follows one source-linked careers page when needed, and verifies open postings.
It fills the existing board form; the user supplies a company name and explicitly adds
and saves it. Discovery is rate-limited, does not write the database/config, and never
blocks the API event loop. Ambiguous/missing/blocked/empty boards return a useful error.
Owner/account limits and existing save validation still apply.

**Self-repair (built):** the daily Mac job `deploy/board-maintenance.py` exports current
live watchlists read-only, then runs `radar.sources.repair_boards`. Confirmed 404s trigger
bounded simple-slug variants across ATSes; verified open candidates go to
`data/t16/16.4-repair-queue.jsonl` with company identity explicitly unverified. Empty
boards observed successfully for 30 days get logged archive proposals in the same queue.
Errors/nonempty boards/gaps over two days reset empty history. State is saved atomically
after each board, and queues deduplicate across retries. **As required by this slice's
review rule, repair and archive proposals never edit the live watchlist automatically.**
The owner reviews identity and re-probes before applying changes. See `deploy/README.md`
for the daily LaunchAgent, local state/log paths and manual command.
Maintenance supports the five safe host-controlled ATSes above; custom career-site
adapters are logged as unsupported rather than guessed or archived. Workday site/tenant
names can't be guessed reliably, but a 404 can still suggest a verified board on another ATS.

**YC feeder (built):** `.venv/bin/python -m radar.sources.yc_boards --limit 50 --offset 0`
reads the [documented hiring directory](https://github.com/yc-oss/api), checks company homepages
and one linked careers page, then probes source-linked Greenhouse, Lever, Ashby and
SmartRecruiters boards through their existing parsers. Every page/redirect uses the pagefacts
SSRF and robots guards; API requests use the same safe fetcher. No guessed slugs are accepted.
The directory alone has a 32 MB cap (it currently exceeds the default 2 MB page cap); run off-box.
Results append to `data/t16/16.4-yc-queue.jsonl` with company website, board link, posting count,
source, verified flag, checked_at and version. Existing queued/watched boards are skipped;
misses retry on a later run. `--watched FILE` accepts a JSON array of `[ats, slug]` pairs from
the live watchlists, including self-service accounts; otherwise only local configured users
are excluded. Increase `--offset` for the next batch; offsets can shift when the directory updates.
Live sample: 20 of 1,489 hiring companies, compared with 618 distinct watched boards,
found Rescale (Ashby, 19 open postings) and Amplitude (Ashby, 36). Review results are on the Mac
in `data/t16/16.4-yc-live-sample.jsonl`. Nothing was added to live watchlists or changed in the feed.
Coverage limit: sites needing JavaScript, hiding their ATS links or using other ATSes are skipped.

**Aggregator feeder (built):** `.venv/bin/python -m radar.sources.aggregator_boards --ats ashby --limit 50`
reads the Greenhouse, Lever, Ashby or Workday company lists at pinned commit
`4bee912c68ca7549ce202db19c61dacded0baaf6` of
[Feashliaa/job-board-aggregator](https://github.com/Feashliaa/job-board-aggregator).
Dataset attribution: Riley Dorrington / Feashliaa; [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/).
Dataset fetches honour robots and use pagefacts' SSRF guard; candidates have validated simple
slugs and are checked through the existing ATS parsers using public APIs. Only nonempty,
parseable boards enter `data/t16/16.4-aggregator-queue.jsonl`, with source URL, pinned commit,
license, attribution and verification time. The dataset has no company names, so `company`
stays blank and `company_verified` is false; `verified` refers to the board's open postings.
Use `--watched FILE` for live watchlists (including self-service accounts), `--offset` for
the next source batch, and `--out` for another queue. Batch offsets remain stable against
the pinned lists even as watched/queued boards are skipped. Nothing is added to live watchlists.
Workday's `tenant|wdN|site` entries are validated before constructing guarded POST probes.
Other upstream ATSes without radar adapters remain unsupported.
Live validation (2026-10-03 Pacific): first 10 source entries per ATS, compared with the
owner's current watchlists, queued 12 distinct unwatched boards (Ashby 7, Greenhouse 3,
Lever 2). All 12 have blank company names as intended. Report:
`data/t16/16.4-aggregator-live-sample.jsonl` on the Mac. One unreadable Lever response was
skipped without interrupting the batch; empty/error boards were not queued.
The final Workday sample queued 2 of 3 candidates through guarded POST probes.

Final validation: 458 backend tests, clean pyflakes, build and all 60 desktop/phone e2e
checks. A Chrome pass with the owner's real Settings snapshot checked light/dark contrast,
keyboard focus and 44px controls without changing live data. Direct live probes verified
Rescale (19), Stripe (716) and NVIDIA Workday (2,000), and distinguished a confirmed 404.
The first maintenance sample checked four supported boards, logged one unsupported adapter
and queued no unnecessary repairs. Actual 30-day production history is not yet available;
archive timing, error resets and review-only behavior are covered by offline tests.

- **Feeders:**
  - **Community lists:** run Simplify/community-list apply links through
    `discover._slug_from_url`, probe each board, and queue it.
  - **YC directory:** `yc-oss.github.io/api/companies/all.json` lists 6,269 companies with
    website and `isHiring`. Probe their ATS slugs. Runs off-box.
  - **job-board-aggregator** (`Feashliaa/job-board-aggregator`): its license is CC BY-NC (personal
    use is fine). Pin a commit, since nothing checks its integrity. Runs off-box.
  - **Paste a careers URL in Settings:** detect the ATS and add the board.
- **Self-repair:** a board that 404s gets slug variants tried across ATSes. A board with 0
  postings for 30 days is archived and logged.

### 16.5 Adaptive polling + automatic company tiers (feeds T14's priority push)

The owner changed the tier definition on 2026-10-04: remove hand-set tiers and rate
companies for a US CS student seeking software, ML or quant internships/new-grad roles.
S includes quant trading firms, frontier AI labs, big tech and top-paying unicorns;
A includes strong tech employers and growing AI companies; B is an ordinary engineering
employer; C is staffing/outsourcing or little relevant engineering. Unknowns default to B.

- Jev (`jev-latest`, TypeSafe SystemOne) and Haiku (`claude-haiku-4-5`) each rate the
  company name. Use Jev's most likely level from valid probabilities, not its weighted score.
  Agreement is accepted when Jev confidence is at least 0.6. Otherwise Haiku searches the
  web once; accept only an exact final tier and cited HTTPS sources. No private user data
  leaves the machine.
- Cache in `enrichment` under `company_tier:<canonical name>`, with rubric version,
  providers, confidence when applicable, web citations when applicable and UTC checked_at.
  Refresh after 30 days; old-rubric entries are stale. Failed companies retry after a day,
  keeping their last tier. Canonical aliases share one cache entry.
- Rate at most 10 stale companies per hourly pass. Haiku shares the existing 200,000-token
  daily budget with Stories/pay; reserve before yielding and refund unused tokens afterward.
  Web search is capped at one use per request. Transport failures retain their reservation.
  Jev sends at most one ten-company batch per background pass. SQLite stays on its owning
  thread while network requests run in a worker. Shutdown stops between companies.
- `python -m radar rate-tiers [--limit N] [--dry-run] [--out FILE]` writes a TSV review.
  Dry runs make model requests within the remaining allowance but do not update SQLite.
- Manual watchlist/profile/API/Settings tiers are removed. Old live YAML still loads and
  loses these ignored fields on its next normal save. User actions personalize sorting to
  at least A without changing a company's cached rating.
- Cached tiers set baseline polling: S 120 s, A/B 300 s, C 900 s. Posting-hour history from
  non-seed `items.seen_at` halves the interval during active UTC hours and triples it outside
  those hours (60–1,800 s bounds); insufficient history keeps the baseline. History refreshes
  at startup/config reload. Newly rated companies immediately invalidate API ranking caches.

**Off-box verification, 2026-10-04:** Google, Microsoft, OpenAI, Jane Street and Five Rings
Capital rated S; Capital One B; Perplexity A, all by confident Jev/Haiku agreement. A fictitious
company stayed unrated. Forced web fallback rated Perplexity A with public citations; a
Five Rings search did not produce a valid cited result and preserved its previous S.
Artifacts: `data/t16/16.5-auto-tier-{sample,web-sample}.json` (local-only).

**Activated 2026-10-04 with the owner's approval:** installed only TYPESAFE_API_KEY,
backed up env/database (`data/backups/radar-env-20261004T165857Z-pre-tiers.env` and
`data/backups/radar-20261004T165857Z-pre-tiers.db`), deployed v0.18.0 and seeded seven
verified company ratings. The first background pass added four more: 11 cached ratings
(6 S, 3 A, 2 B). Remaining companies use B until the hourly, budgeted refresh rates them.
Daily shared usage is 196,492/200,000; no budget reset or extra provider allowance.

Owner feed before/after: identical 1,578 IDs, 412 stated pay, 53 blank companies and 107
blank locations. Top counts unchanged: TikTok 93, Palantir 57, RTX 39, ByteDance 31.
Compared all 852 distinct company names; all 36 S/A changes are listed in
`data/t16/16.5-live-tier-diff.json` (local-only), including temporary defaults after removing
manual tiers. IDs, first_seen, actions, notes and existing pay stayed unchanged; quick_check
and healthz passed. All 614 successful post-deploy board schedules matched their expected
interval within jitter; 11 boards have enough non-seed posting history to adapt. Chrome
checked the deployed Settings with live owner data through a read-only local proxy:
602 companies, no tier control/overflow, mobile 44px targets and visible keyboard focus.

A one-hour before/after poll-count window, future alerts, the owner's own browser/phone,
and complete company-cache coverage remain unverified. Cache filling continues automatically;
failed/expired ratings go behind companies never attempted, avoiding retry starvation.
Artifacts: `data/t16/16.5-live-{before.log,after.log,audit.json,tier-diff.json,poll-intervals.json}`.

### 16.6 Learn from the user
- **Profile suggestions:** after repeated dismissals with the same pattern, suggest a profile edit
  the user approves ("add 'sales' to exclude?").
- **"Why didn't I see this?":** the user pastes a link, it is dry-run through the pipeline, and the
  app says which gate dropped it. This doubles as a T13 audit tool.

#### As built (2026-10-04, v0.19.0 + v0.19.1; done/live `46afaae`)

- A successful hide opens an optional shared feedback sheet, including Tracker and
  the Jobs keyboard shortcut. Feedback accepts a title-matching phrase of at most
  80 characters, lowercased with collapsed whitespace. Failure never reverses the hide.
- Three distinct currently hidden jobs with explicit feedback in the last 30 days
  suggest adding the phrase to `profile.exclude`. Settings shows three supporting
  titles, the affected For you count and up to three examples. Existing exclusions
  are omitted; curated Stories retain their bypass. Apply uses the current validated
  profile writer. Mute lasts until manually restored. Notes edits preserve feedback;
  unhiding clears it. Old hides without feedback do not count.
- Schema migration 5 adds nullable `actions.hide_term`/`hide_term_at` and the empty
  per-user `muted_profile_terms(user_id, term)` table. Existing IDs, actions, notes,
  opportunities and profile values are preserved. No backfill of inferred reasons.
- Authenticated `GET/POST /api/profile/suggestions` lists suggestions/muted terms
  and accepts `apply`, `mute`, or `restore`. Action PATCH/response includes optional
  feedback. OpenAPI and generated frontend types are updated.
- Authenticated `POST /api/diagnostics/link` canonicalizes a public URL, checks the
  user's collected posting/sighting aliases first, then previews unknown links with
  guarded ATS/JSON-LD readers in a worker. Checks cover source coverage, applicable
  ATS titles, profile matching, hidden/dead state, recorded backfill and own-channel
  alert evidence. Current gates are not presented as historical rejection decisions.
  Unavailable facts/history stay inconclusive; active Jobs filters are called out.
- Diagnostics consume no model tokens, import no jobs, persist no preview cache,
  send no alerts and make no source repairs. Ten requests per user per hour, including
  invalid URLs; two concurrent fetches. Timed-out requests retain their slot until the
  guarded worker finishes. Existing SSRF/redirect/robots/size/time guards are reused.
- Read-only production snapshot copied off-box: migration 4→5 preserved checksums
  of all existing table values; old/new matching agreed on 11,519 distinct posting
  values. Snapshot raw matching rows before requisition deduplication: 1,727, 441 stated pay, 1,286 blank pay,
  65 blank company/130 blank location; top companies TikTok 105, RTX 58,
  Palantir 58, ByteDance 31, Microsoft 29. No automatic suggestions without feedback.
  Empty-suggestion query took 1.4 ms locally. Artifacts:
  `data/t16/16.6-local-{live-audit,diagnostics}.json`.
- Chrome desktop/phone inspected against real owner snapshot data: Settings,
  known-link results and keyboard hide feedback; mute/restore/apply exercised on
  local-only feedback. No overflow; new controls at least 44px. Phone focus restoration
  after Escape has a regression check. No production tokens were used.
- Validation: 503 backend tests, pyflakes, web build and all 68 desktop/phone e2e
  tests pass. The API privacy regression includes the new nullable feedback fields.
  Initial local approval matched 1,092 raw-row removals (1,723→631). Live deployment
  verification exposed that preview counts also needed Jobs requisition deduplication;
  v0.19.1 now uses the same newest-twin selection before visibility/profile gates.
  A regression compares preview counts with actual API lists, including hidden twins.
  All other profile fields are preserved. Settings text contrast measured
  6.6:1 or better; keyboard/phone focus and all new 44px controls checked in Chrome.
  Existing Ponytail markers reviewed; no new deliberate shortcuts added.
- Schema 4→5 approved and applied on production after backup
  `backups/t16.6/radar-20261004T191900Z.db`. All existing table values unchanged,
  quick_check OK; new feedback is NULL and the mute table empty. First live API
  comparison: same 1,578 IDs/card values/profile, 413 stated pay, 1,165 blank pay,
  53 blank company/107 blank location. No deployment errors.
- v0.19.1 checks: 504 backend tests, pyflakes, build and 68 e2e pass.
- Final live verification (restart 2026-10-04 19:27:54 UTC): 1,578 owner IDs and
  every existing card value unchanged; profile unchanged, summary equals paged totals.
  413 stated pay/1,165 blank pay; company/location blanks 53/107. Top named companies
  unchanged: TikTok 93, Palantir 57, RTX 39, ByteDance 31, Microsoft 25.
  New feedback remains NULL and mute table empty; known-link diagnostic passes.
  Chrome read-only proxy to the real production API checked Settings and diagnostic
  results on desktop/phone: no overflow, visible keyboard focus, 44px controls.
  Deployed code/version/HTML hashes match the committed build; no post-start errors.
  Corrected real-data local preview predicts exactly 1,011 displayed removals
  (1,575→564 after three local-only test hides), matching API filtering.
  Artifacts: `data/t16/16.6-{deploy-migration-audit,live-feed-audit,displayed-preview-check}.json`.
- Outstanding: a real future dismissal pattern and the owner's own phone.
  Historical rejection logging and company/location exclusion learning are deferred.

### 16.7 Maintenance by agent
- **Weekly routine:** a scheduled cloud agent runs `discover --check` and opens a PR with dead-slug
  fixes and a health report. **PRs only: it never deploys and never writes the live DB.**
- **Nightly canary:** push "radar is quiet" when nothing has arrived within a set window.

### 16.8 Company names from source data
- **The problem:** some company names were derived from slugs ("Boxinc", "Ashbyhq",
  "Acuityinc", "Voyagertechnologiesinc").
- **Fix:** take the name from JSON-LD `hiringOrganization.name` or the matched record. Change the
  display only; the stored text stays.
- **Then:** merge duplicates that share a company and a job id. The Ashby `jr_id` duplicates from
  before 0.9.0 still exist.

## Context for whoever continues
- **Code:** `radar/logos.py`, `radar/pipeline/pagefacts.py` (`_get`, `_robots_allows`,
  `org_site`), `radar/pipeline/enrich.py`, `radar/legacy/llm_extraction.py`,
  `radar/pipeline/filter.py`, `radar/pipeline/places.py`, `radar/sources/discover.py`,
  `radar/sources/ats.py`, `radar/config.py` (`tier`, `company_tiers`).
- **Jev docs:** <https://docs.typesafe.ai/introduction/quickstart> and <https://docs.typesafe.ai/api>.
- **Release:** each slice merged to `main` gets a `CHANGELOG.md` entry, a `web/package.json` bump
  and a `vX.Y.Z` tag (owner's rule). 16.1 isn't merged yet; the branch is
  `claude/trim-drop-radar-plan`.
