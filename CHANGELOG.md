# Changelog

Versions follow the web app (`web/package.json`). Every merge to `main` adds an entry and a `vX.Y.Z` tag.

## 0.20.1 (2026-10-04)

Board-health probes reject malformed posting lists instead of counting them as empty
boards. Pay extraction retains its token reservation when provider usage is unknown
after a transport failure. Diagnostic tests mock both public-host guards to stay offline.

## 0.20.0 (2026-10-04)

Career adds a private library of career facts and reusable answers. Records begin
as drafts; approval requires a source or personal confirmation note. Every revision
is preserved, conflicting edits cannot overwrite newer work, and answers referencing
changed or retired facts require review. Answer context is explicit; approval does
not authorize applications, messages or spending. This is the first T20 foundation;
ranking, packets and external execution are still pending.

## 0.19.1 (2026-10-04)

Profile suggestion previews now count displayed jobs with the same duplicate-requisition
collapse as Jobs and its summary. A hidden newest copy also suppresses its older twins.

## 0.19.0 (2026-10-04)

T16.6 adds optional title-phrase feedback after hiding a job. Three distinct hides
within 30 days suggest a profile exclusion in Settings, with supporting jobs and
an affected-job preview. Suggestions change the profile only when approved;
dismissed terms stay muted until restored. Unhiding clears feedback and notes stay intact.

Settings also explains a pasted job link using current filters and recorded evidence.
Unknown links use guarded public posting previews without importing jobs, changing
model budgets or sending alerts. Missing facts and historical decisions stay inconclusive.

## 0.18.1 (2026-10-04)

Trading/trader alone now classifies as Finance rather than Quant. Quant requires explicit
quant or quantitative/algorithmic/systematic/high-frequency trading language. Titles take
precedence over stored role tags; spelled-out artificial intelligence remains AI / ML / Data.
This applies consistently to feed filters, summaries and the bitmap index.

## 0.18.0 (2026-10-04)

T16.5 replaces manual company tiers with automatic CS-student ratings. Confident Jev and
Haiku agreement sets the tier; other names use Haiku web search with cited evidence.
Ratings refresh every 30 days within the shared Haiku daily budget. Failed ratings preserve
the previous tier and retry after a day. Quant firms, frontier AI labs and big tech are S
candidates. User actions still personalize prestige sorting. Settings no longer asks for a
tier. Cached ratings set polling intervals, adjusted by each board's observed posting hours.

## 0.17.0 (2026-10-04)

T16.3 pay extraction now uses Haiku when the fetched posting has no structured/regex pay.
Amounts, currency, period and an exact source quote must pass validation before filling a
blank. Gemini is tried only after Haiku fails, with a ten-minute pause on quota errors.
Calls share the Story daily token budget; content caching avoids repeat spend. Unknowns
retry after a week, API failures retry next time, and dry runs use cached model evidence
only. Model calls run in the background so alerts still go out promptly. Existing pay,
row IDs and notes are preserved, including changes made while a request is running.

## 0.16.0 (2026-10-04)

T16.4 is complete: Settings can check a careers URL, detect its supported ATS board and
fill a form for review before adding it. Checks use public ATS APIs and the existing
SSRF/robots guards, run off the API event loop and never save a watchlist by themselves.
The add/save controls now sit above the company's list so large watchlists stay usable.

Daily Mac maintenance queues verified slug repair candidates after confirmed 404s and
archive proposals after 30 days of successful empty observations. It logs its evidence,
resets empty history after errors/gaps, and never changes a live source without review.
Guessed repair candidates explicitly leave company identity unverified.

T16.4: `python -m radar.sources.yc_boards` discovers company-linked career boards from the YC
hiring directory off-box and writes verified nonempty boards to a review queue with provenance.
It supports bounded batches and a live-watchlist export; nothing is added automatically.

The off-box `python -m radar.sources.aggregator_boards` also feeds the review queue from
commit-pinned Greenhouse, Lever, Ashby and Workday lists in Feashliaa/job-board-aggregator. It records
CC BY-NC dataset attribution and verifies open postings without guessing company names.

## 0.15.0 (2026-10-04)

**Jobs lists and counts come from an in-memory bitmap index** (T18, `docs/specs/T18-fast-sort.md`). Filtering and paging no longer sort and scan 12,000 postings per request.

- **Compression.** Caddy now sends gzip or zstd: a 50-row page went from 39,122 to 7,721 bytes. This is box config (`encode zstd gzip` in the site block of `/etc/caddy/Caddyfile`), not part of the repo.
- **Index.** `radar/api/bitindex.py` numbers postings by posted order and keeps one bitset per attribute (level, track, US, per user: yours, new drop, closed, For you), so a filter is an AND, a page is the 30 highest set bits and a count is a popcount. Pages match the SQL path exactly: same twin copy shown, same order, same cursor (checked on the owner's live feed: all 1,558 For you and all 11,398 Everything rows in identical order, and `/summary` totals, levels and tracks equal the counts from those dumps). `tests/test_bitindex.py` pages 250 random filter combinations through both paths and compares every page and cursor.
- **Timing on the box** (30 rows, end to end): For you 0.78 s to about 15 ms, intern + Software 0.4 s to 13 ms, Quant (7 hits in 12,000) 1.4 s to 5 ms, posted in 7 days 0.6 s to 15 ms, prestige 0.5 s to 11 ms. Those are the numbers between poller bursts. During a burst the scheduler's parsing keeps the shared event loop busy and everything slows, including `/api/me` (2 ms to a 160 ms median): lists then take 150 to 250 ms, so the 20 ms target holds only between bursts.
- **Counts.** `/api/opportunities/summary` is popcounts, so it answers at once with no 5-minute recount and no first-request 503 once the index is built.
- **Staying current.** A read-only connection watches `PRAGMA data_version`. The poller commits all day, so a refresh (diff a per-row signature, recompute only changed rows, about 0.6 s on the box) runs when a new posting is stored (at most every 5 s) and every 60 s as the net for other processes such as `fix-pages`. Hides are read per request, so they show at once. A posting stored as a live drop is a promise: until a refresh that started after it has finished and the user's view has caught up, lists read SQL, so a list opened right after the push always shows it (`tests/test_bitindex.py` runs this the way production does, with worker threads). After a restart the index builds for about 75 s for the configured users and the guest (SQL answers meanwhile); an account's view builds on its first request, and a profile or sources change rebuilds only that user.
- **Still on SQL:** `sort=found`, `since` (the New pill), `source`, `status`, `action` (Hidden) and `closing_within`.
- 441 backend tests.

## 0.14.0 (2026-10-04)

**One Jobs screen** replaces Feed, New, All matches and All jobs (T17, `docs/specs/T17-feed-redesign.md`). The nav is Jobs, Tracker, Sources, Settings; a guest sees only Jobs.

- **Scope and filters.** A For you / Everything switch, a search box, and pills for New, Level, Track and Posted; Location, US only, Closing soon, Drops only and Sort sit under More (Filters on a phone, where every pill moves into that drawer). The list is flat, newest posted first; level is a badge on the card, not a section. Filters live in the address (`#/jobs?scope=all&level=intern&track=Software`), so reloads, the back button and shared links keep them. `#/feed` opens For you, a bare `#/jobs` (the old All jobs) opens Everything, `#/board` opens the Tracker.
- **One meaning of "new".** New is a drop (found after its source was already watched) that arrived after your last visit on this device. The yellow card, the New pill and the "N new since Fri 9:46 PM" header line all mean that; it replaces the old 3-hour rule. On a busy day Jobs opens with New selected; on a quiet day the New pill is greyed out and the normal list shows. The "N new drops" pill moved to the Jobs nav item.
- **One date per card:** when the employer posted it, or "found" when the posting gives none. Found and the lag stay in the detail pane. "Newest found" is gone from Sort (the API keeps `sort=found`).
- **Tracker** (the old Board) has a collapsed Hidden list; "Ignored" is now "Hidden" everywhere, and the Ignored switch left Filters.
- **Server-side level, track, posted_within.** `/api/opportunities` takes `level=intern|new_grad`, `track=<name>` and `posted_within=<days>`, and every item carries `level` and `track`; the web no longer classifies the 30 rows it has loaded. Rules live in `radar/pipeline/roles.py`. Fixed two misses: "2027 Grads" and "Early Careers" now count as new grad (13 of the owner's 1,558 matches, 77 of 11,396 jobs); no track changed.
- **`GET /api/opportunities/summary`** returns counts for For you and Everything, per level and per track (a count reads every posting and takes 6 to 30 s on the box, so a request gets the last count at once and a recount runs in the background; the very first request is a 503 with Retry-After). It feeds the header line and the pill counts, which are exact because they are not computed over a page.
- **Fast filters.** Level, Track and Posted are decided from the row before any per-posting fetch (picking Intern in For you went from 15 s to 0.7 s on the box), and the old list stays on screen, dimmed, while a new filter loads. The list reads rows as it needs them instead of all 12,000 per request (a plain page: 0.7 s to 0.4 s).
- 435 backend tests, 58 e2e tests (29 checks on desktop and phone).

## 0.13.1 (2026-10-04)

The top bar has an appearance menu with Light, Dark, and System options. System follows the device; an explicit choice is remembered in this browser and shared across tabs. The selected theme applies before the first paint and sets the browser chrome and native controls to match.

`python -m radar find-boards [--limit N] [--out FILE]` lists career boards the stored apply links point at that no watchlist has, probes each once, and writes the ones with open postings to a review file. It is read-only: nothing is added to a watchlist or the database until the owner picks boards from the file. The owner picked all of them: 213 boards (Workday 98, Greenhouse 43, Ashby 43, SmartRecruiters 11, Lever 9, Oracle 8, Eightfold 1) joined the watchlist at tier C (polled every 15 minutes), taking it from 602 to 815 companies. Each new board is seeded silently on its first poll, so nothing alerts for postings that were already open.

## 0.13.0 (2026-10-04)

When a posting gives no pay, US roles with a recognizable occupation now show a clearly labeled national wage benchmark. The detail pane names the occupation, 2025 BLS OEWS source, 10th–25th percentiles, and links to WageDex's CC BY 4.0 compilation. Employer-stated pay always takes priority. The benchmark covers all workers in an occupation, so it is not a company offer or an internship-specific wage. On the owner's live feed it would cover 851 of 1,209 blank-pay cards; 358 remain blank for uncertain roles or locations outside the US.

Store-level postings no longer enter the feed: the shared ATS title gate rejects titles with a store number, a street address, or franchise job names (Domino's "Customer Service Rep(05261) - 107 E University Ave", "Entry Level Manager (05443)"). Checked over 12,546 live titles: it rejects exactly the 199 Domino's store rows and nothing else.

## 0.12.0 (2026-10-04)

**A pay column.** Where a posting states its pay, the card shows it ("$62-$72/hr", "$120,000-$165,000/yr"), the compact row has it as a column, and the detail pane lists it. Nothing is shown when the posting states none.

- **Where pay comes from:** the posting's own page, never a guess. Structured data first (Lever's salary range, SmartRecruiters' compensation, Greenhouse pay ranges, schema.org `baseSalary` on Ashby and company pages), then a conservative read of the description text for a range with a currency mark and a stated or obvious period. Bonuses, stipends, relocation money, company funding and benefit amounts are never read as pay; a posting listing several regional ranges shows the widest.
- **New drops** get their pay in the background, so a push never waits for it. `python -m radar fix-pay [--dry-run]` fills it for stored postings that match someone's profile. On 80 live postings 19 (24%) state a range.
- API: `pay` on every opportunity. 425 backend tests, 38 e2e tests.
- The account button's accessible name is the username (as the visible label already was).

Released together with 0.11.0 below, which was deployed on 2026-10-04 before the merge.

## 0.11.0 (2026-10-04)

Fixes from the owner's full audit of the live app.

- **A city in your profile now takes in its metro area.** "Seattle" matches Redmond, Bellevue, Kirkland; "New York" matches NYC, Jersey City, Brooklyn (within 50 km, GeoNames coordinates). Microsoft's Redmond new-grad role had been dropped by a Seattle/New York profile; over the stored postings, 410 more now match.
- **The US check reads GeoNames instead of hand-typed city lists** (T16.2): "Atlanta, Georgia" is the state, "New Brunswick, NJ" is New Jersey, "SGP - Woodlands" is Singapore.
- **Instagram Stories are read by Claude Haiku 4.5**, picture included (T16.3). A junk title ("Other Opportunity · 2026", "= 3 hackathon teams") is replaced by the real one; a Story with no application link that Claude is sure is a meme or a tweet screenshot becomes "Not actionable" (out of the feed, never pushed). `python -m radar fix-stories [--dry-run]` repairs stored rows.
- The same job posted as several requisitions shows as one card.
- The top bar shows your username, not the internal id; the feed says "nothing new for 23h" instead of "30+ new roles" when quiet; opening `/settings` directly works.
- `radar/data/` (places.json, build_places.py) is now tracked; `.gitignore`'s `data/` rule had hidden it.

## 0.10.1 (2026-10-03)

Location format changed from "City - Country" to what the owner asked for: **US places as "City, ST"** ("Seattle, WA"), **everywhere else as "City, Country"** ("Barcelona, Spain").

- A US city's state comes from the text ("Houston, TX", "San Francisco, California" becomes "San Francisco, CA"), else from the biggest US city of that exact name (Redmond is WA, Boston is MA; 1,572 cities of 30,000+ people). A small town with no state anywhere shows "Holmdel, United States" rather than a guessed state.
- Several places are listed in the order the source gave them: "Reston, VA; Plano, TX; Toronto, Canada". Remote shows as "Remote, United States". A bare state shows as "Iowa, United States"; a bare country as the country.
- Street addresses in a place ("152 Endicott Street, Danvers MA") are dropped, and "Danvers MA" without a comma is understood.
- On all 12,262 distinct live places, 91% become a clean "City, ST" or "City, Country"; most of the rest are country-only or a small place with nothing to place it.
- 390 backend tests; 36 e2e tests.

## 0.10.0 (2026-10-03)

One location format: **City - Country**.

- Every place is shown as "Houston - United States", whatever the source wrote ("Houston, TX", "Poland - Wroclaw", "US-TN-Tullahoma", "United States, Wisconsin, Milwaukee", a bare "Redmond", "KUALA LUMPUR GENERAL OFFICE"). Several places are grouped by country: "Reston, Plano - United States; Toronto - Canada". The country comes from the text, from a US state or Canadian province, or from the biggest city of that name (Redmond is Washington, Boston is Massachusetts). A city that cannot be placed keeps just its name.
- On all 12,262 distinct places in the live data, 93% become a full "City - Country"; the rest are honestly country-only or state-only ("United States", "Iowa") or a small place with no country to be found. Nothing is guessed.
- It applies in the feed, detail panel, Board and phone pushes. The stored text is untouched, so search and the US-only filter work as before, and the API now returns both `location` (display) and `location_raw`. Remote / Hybrid / On site badges still read the original text.
- City data: `radar/data/places.json`, generated from GeoNames (CC BY 4.0) by `radar/data/build_places.py`; only that 0.9 MB file loads at runtime.
- 4 new tests (390 backend); 36 e2e tests.

## 0.9.0 (2026-10-03)

Missing facts are read from the posting's own link.

- **Why:** a posting could arrive with no location ("4 locations" from a board search, or nothing at all from an @zero2sudo Story), no company or no posted date. Live counts before this release: 903 "N locations", 250 blank locations, 82 blank companies, 1,011 undated.
- **What it reads:** the job-board detail APIs we already rely on (Workday, Greenhouse, Lever, SmartRecruiters) and the schema.org job data most company pages embed (Ashby, many company sites). On 90 real broken postings the Workday detail gave a location for 60 of 63; pages that refuse automated clients (403) or have no job data are left alone, never forced.
- **It only fills:** blanks and bare counts. A location, company, date or deadline a source stated clearly is never changed, and "4 locations | Des Moines, IA | ..." is kept.
- **When:** a new drop waits up to 15 seconds for its link, so the feed and the push show the real place; a first-poll backfill is filled in the background. Results are cached and a miss is retried after a week.
- **Safe by construction:** http(s) only, public addresses only (checked on every redirect hop, so a link can't aim the box at an internal address), four redirects, a 2 MB cap, an honest User-Agent, one request a second per host, robots.txt honoured for plain pages.
- **Repair command:** `python -m radar fix-pages [--dry-run] [--limit N]` fills the postings already stored.
- **First live repair (2026-10-03):** of 1,734 postings looked at, 1,495 were fixed: 781 locations, 955 posted dates, 8 companies, 8 deadlines. Counts before then after: undated 1,011 to 56; bare "N locations" 903 to 14; blank locations 250 to 215; blank companies 82 to 74. What is left are pages that refuse automated clients or carry no job data.
- Ashby links with a `jr_id` referral tag now match the board's own link, so a Story's link no longer makes a second row for the same posting (found on Bedrock Robotics).
- 16 new tests (386 backend). No frontend change.

## 0.8.0 (2026-10-03)

Extra companies for accounts.

- An account sees every company the radar already watches and can add up to **10 more job boards** in Settings. Those boards are polled for everyone's benefit once, but only shown to the account that added them (the first poll is stored as already-open backfill, so adding a board never floods anyone).
- **What strangers may add is tightly limited:** companies only (no feeds, Instagram or lists); only Greenhouse, Lever, Ashby, SmartRecruiters and Workday, where the board name goes into a fixed website address; strict name patterns, so nothing can point the box at another address. At most 200 extra companies across all accounts.
- **Every new board is checked once before it is saved** (it must answer with open postings), so a typo or an empty board is refused with a plain explanation instead of being polled forever. A board that someone already watches is accepted without a check. Edits are rate limited.
- Settings: "Extra companies" for accounts with a counter and only the allowed boards in the picker. The configured users keep the full watchlist editor.
- Fixed: after saving the profile or watchlist the "Saved" message no longer vanishes (the form used to rebuild itself).
- 6 new tests (370 backend); 36 e2e tests.

## 0.7.0 (2026-10-03)

Phone alerts for accounts, and a way to prove they work.

- **Turn on phone alerts** in Settings for an account: it gets its own private, unguessable ntfy topic (never chosen by the user, never from the environment), with a three-step setup and a link. Turn off removes it.
- **Send a test push** (everyone with alerts, including the two configured users; three an hour): the way to confirm a phone really receives them.
- **Nothing old is pushed:** alerts only fire for newly arriving postings, and the retry sweep only touches pushes already owed, so enabling alerts never sends what matched before (a test proves it).
- **Daily caps** protect the box's single sending address: 40 pushes a day per account and 150 across all accounts. The configured users' own pushes are never counted. A skipped push is not claimed, and the posting is still in the feed. ntfy's published defaults (60-request burst, then one every 5 seconds) are far above this; the free tier's daily total could not be confirmed from its pages, so the caps are deliberately low.
- Settings form fields now have names and autocomplete settings (DevTools flagged them).
- 4 new tests (364 backend); 34 e2e tests.

## 0.6.0 (2026-10-03)

Accounts people create themselves: a username and password instead of a long token.

- **Create account / Sign in** with a username and password on the sign-in screen (password managers work). Access tokens still work behind "Use an access token instead", and personal `#token=` links still sign you in.
- **Everyone can add a username and password** in Settings, including the two configured users, so there is no need for a second account and saved roles stay put.
- **A new account** gets the default early-career profile (tech and business) that it can reshape in Settings with one-tap presets (Software and data, Quant and trading, Finance, Business and consulting), its own private saved roles, Board and notes, and the same shared set of sources as everyone.
- **Safety:** passwords are hashed with scrypt in a worker thread (nothing in the database can be replayed); sessions are random tokens stored only as hashes and last 90 days; "wrong username" and "wrong password" answer identically; login, sign-up and credential changes are rate limited; at most 300 accounts; changing a password signs out other devices; signing out ends the session on the server too. Account ids are generated and never reused.
- **Forgotten password:** the owner runs `python -m radar reset-password <username>` on the box (prints a new password once and signs the user out everywhere).
- Not yet for accounts (next releases): their own phone alerts and extra companies; the Watchlist section is hidden for accounts until then.
- 14 new account tests (360 backend tests); 32 e2e tests.

## 0.5.0 (2026-10-03)

Browse without signing in; sign in for more.

- **Guest view (no token):** the Feed (a default early-career profile across tech and business) and All jobs (everything any watched source found), read-only, with Apply links and filters. No Save, Ignore, notes, Board, Sources, Settings, alerts or live stream. Guests see a banner and a Sign in button; the gated screens show the sign-in page with "Keep browsing as a guest".
- **Signed in:** your own profile feed, Save and Board with notes, phone alerts, live drops, Settings and the account menu, as before.
- **Server:** `viewer` dependency serves only `GET /api/me`, `GET /api/opportunities` and `GET /api/opportunities/{id}` to guests; every write and every account route stays token-only (a wrong token is still a 401). Guests never receive anyone's status, notes or notification URL. Guest requests are rate limited (60 a minute per address, 429 after) and pages are capped at 50 rows and cached for 60 seconds. `guest` is a reserved user id. The default profile ships with the code (`radar/guest_profile.yaml`).
- Track chips gained Finance and Business, and Security no longer swallows "risk" roles. Calibrated on 1,500 live titles read-only on the box.
- 5 new API tests and 2 config tests (346 total); 28 e2e tests.

## 0.4.0 (2026-10-03)

- Compact rows: a toggle beside Filters on Feed and All jobs swaps the roomy cards for one-line rows (about 50px against about 160px) that keep Save and Apply. Remembered per browser. The column picker from the plan was skipped: rows are cards, not a table.
- Frontend only. 26 e2e tests; Lighthouse accessibility and best practices 100.

## 0.3.1 (2026-10-03)

- Account menu in the top right (profile icon): Settings and Sign out, one tap from any screen. Sign out is no longer at the bottom of Settings.

## 0.3.0 (2026-10-03)

- Work-model badge (Remote, Hybrid, On site) on cards and in the detail panel, read from the location and from tags in the title. "Hybrid Cloud Engineer" is not mislabelled. Most postings do not say, so most cards show none.
- First-run welcome sheet for a new user (drawer on phone, side sheet on desktop): what the radar watches, how to read a card, where to set roles and alerts. Shown once per user per browser.
- Sources screen opens with four plain-words numbers (next check, healthy, checked in the last hour, typical alert speed); rate-limited sources read "rate limited, retrying".
- Frontend only; no backend change. 22 e2e tests; Lighthouse accessibility and best practices 100.

## 0.2.1 (2026-10-03)

- No emoji anywhere live: push notifications no longer carry the briefcase tag (ntfy turned it into an emoji); text arrows in Settings and Sources are now drawn icons or plain words.

## 0.2.0 (2026-10-03)

Web redesign, deployed to the live box 2026-10-02 20:43 UTC.

- Index-card board on shadcn (Radix) and Tailwind v4: card colour is the state, always with a text label; dark mode follows the device.
- Feed groups repeated roles into one row and has track chips with counts.
- Role detail: pane on desktop, drawer on phone. Filters sheet, labelled phone tab bar, 44px touch targets.
- Board, Settings and Sources restyled; those screens load lazily.
- Fixes from a DevTools pass: drawer focus, input name, mobile-web-app-capable. Lighthouse mobile: accessibility 100, best practices 100.
- No backend changes.

## 0.1.0 (2026-10-02)

Drop Radar service: pipeline, scheduler, API, PWA, live on Oracle Cloud. The hourly GitHub Actions job is retired (tag `legacy-hourly-monitor`).
