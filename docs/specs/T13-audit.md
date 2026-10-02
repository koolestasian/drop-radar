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
  (the friend's 20 sends by 15:40 UTC on 2026-10-02; the owner has no channel yet).
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

Found by the read-only walkthrough (2026-10-02 ~15:45 UTC); first three fixed in code (cc7de18), not yet deployed:
- **Old postings in New** (352 sightings): 296 of the 398 non-seed Oracle ones came from one event,
  the 06:12 UTC deploy that widened Oracle's searches from 2 keywords to 4 -- each board found
  postings its baseline had never searched for and called them drops. The other ~55 are title
  edits that newly match the early-career filter (Greenhouse "2027 Start"), Simplify rows added
  late, Eightfold/Google. Fix: `radar/pipeline` stores a posting dated >7 days before it was seen
  as backfill (`STALE_AFTER`). Live repair (needs the owner's yes, backup first): the same rule
  as one UPDATE over `items`; simulated on a copy, New goes 37->22 (owner) and 61->28 (friend).
  Widening a source's queries later will repeat the burst unless the new postings are old.
- `is_us_location("Zaragoza, Aragon, ESP")` was unknown, so it passed "United States": a trailing
  ISO alpha-3 code now names the country. Fixed.
- Not bugs: the GM financial "duplicate" is three real requisitions (260818, 260795, 260943);
  the Point72 Story is today's (15:08 UTC) and merged into a 2025-10-31 Greenhouse posting, so the
  feed shows that older date. 568 extra rows share company+title+location (Nokia x16): real
  separate openings; grouping them in the feed row is a T15 UI idea, not a data fix.
- The friend's profile has no `locations` (Seoul, Paris, Colombo, Bogota pushed); `risk`
  matches security-engineer roles; Citi "Summer Associate" is MBA-level. Their call, not a bug.
- The 282-row legacy tracker was never imported on the box (oldest `first_seen` is the
  deploy; 0 migrated rows): its history lives only in the xlsx/Sheet.
- `radar-backup.timer` has not fired yet (first run 2026-10-03 03:30 UTC); the 7 backups are manual.

## Rules
Writes to the box (`radar.env`, DB repairs, restarts) need the user's explicit yes in
the conversation: the permission classifier blocks them otherwise. Back up the DB first.
