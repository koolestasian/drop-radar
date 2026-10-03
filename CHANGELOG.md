# Changelog

Versions follow the web app (`web/package.json`). Every merge to `main` adds an entry and a `vX.Y.Z` tag.

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
