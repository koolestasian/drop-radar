# T13: full audit before new features

The user still sees bugs (2026-10-02) but didn't list them. **Start by asking once
which bugs they've seen**, then run the audit alongside fixing them. Output: a ranked
list in PROGRESS.md (what's broken, why, the fix, its size). Fix only what the user
agrees to. T14 comes next and may absorb items from this list.

## Check, on live data (read-only on the box)
Tests missed every real problem so far; look at the user's actual feed
(see memory "check real data"):
- **Both users' feeds** through the API (tokens read on the box, never printed):
  counts per tab (New / All matches / All jobs), New that is really old,
  non-US or blank locations, wrong company names, junk titles, duplicates of the
  same job from several sources, closed postings still shown.
- **The web app on phone and desktop** with that real JSON (Playwright screenshots of
  the built app): read it like a user. Logos, sorting, search, the location and US-only filters,
  Settings, sharing, board statuses/notes.
- **Sources:** failing/stale sources in `/api/sources`, error kinds, how many boards
  never returned a posting, Workday request load, the relay's staleness when the Mac sleeps.
- **Alerts:** what each user would have been pushed today and whether it was right
  (the friend's 2 sends; the owner has no channel yet).
- **Box health:** memory/swap, disk, restarts, backup timer, Caddy cert expiry.

## Known items to fold into the list
- The hourly GitHub job has failed every hour since 2026-10-01 (Apify 403: the token lost
  access to `data-slayer/instagram-stories-scraper`). So the xlsx tracker and Google Sheet
  haven't updated since 2026-09-30, and the legacy job sends no pushes.
- The owner has no working push path (T14 fixes it).
- Stories arrive only while the Mac is awake (LaunchAgent relay).
- Offered earlier, not started: salary sort (pay is rarely listed), a prestige list in
  `profile.company_tiers`, Citadel sitemap jobs with no location, the owner once seeing
  the friend's feed (likely installed-app storage; `#token=` link fixes it).
- T11 hardening stays deferred.

## Rules
Writes to the box (`radar.env`, DB repairs, restarts) need the user's explicit yes in
the conversation: the permission classifier blocks them otherwise. Back up the DB first.
