# T15 input: what competing products' UIs do

Collected 2026-10-02 by viewing each site's **public landing/list page** once on desktop and phone
(Playwright, no login, `robots.txt` checked first). That shows marketing pages and public lists, not
the logged-in apps, and every number below is the site's own claim, unverified. Screenshots are kept
out of the repo on purpose.

## What each one is, and what to take

| Site | What it is | Worth taking | Skip |
|---|---|---|---|
| **Boardsweep** (closest rival) | Alerts from company job boards; says it reads 3,750 boards hourly and the top 150 every 3 minutes | Live pill "Newest role 1 min ago · 250 found today" and "Next sweep in 4 min"; an email digest ordered *watchlist companies first, then everything else matched*; a **Tracks** picker with counts (Software 3,617, AI/ML/Data 2,711, Hardware, Quant, Product, Security, Design) plus a **Level** toggle (Internships / New grad); a "We can show our working / See the numbers" transparency section; FAQ "Are the roles real, and still open?" | Paid tier and sign-up-first flow (ours is private) |
| **Simplify** | AI job search: daily matches, resume, autofill | A compact match list with logo, company, "5 mins ago" and a **score chip** | A made-up % score. Our `match.reasons` ("role: software engineer; level: intern") says *why*, which is more honest |
| **Jobright** | AI copilot, insider connections | Little for a feed UI; heavy claims ("3,000,000 users") | Marketing-style stats |
| **Intern-List** | One big public table of internships | **Dense table**: title, date, Apply, **work-model badge (On Site / Hybrid / Remote)**, location, company, salary; filter dropdowns (Title, Company, Industry, Work Model, Location, Salary) and **Edit Columns**; category chips with counts; "New openings today / Total" counters | Emoji-heavy chips |
| **Huntr** | Application tracker | Board with Wishlist / Applied / Interview columns; tabs **Board / Activities / Contacts / Documents**; Share | AI resume and autofill features |
| **Levels.fyi Jobs** | Job search with pay data | **Split view**: company-grouped list on the left, full detail on the right; jobs **grouped by company** with a count; pay shown inline; sort by pay / relevance / date; a first-visit modal that explains the filters | Needs pay data we mostly don't have |

## Where Drop Radar stands

Already comparable: live pill with source count and "newest found Xm ago"; New vs All matches; search,
location and US-only filters; logos; Apply / Save / Share / Ignore; a Board; sort by posted, found, prestige.

Missing, ranked by value for the effort:

1. **Group by company.** One company often posts the same role many times (Nokia x16 "AI R&D Engineer
   Co-op"). A grouped row with a count fixes the duplicate look without hiding real openings.
2. **Detail panel / split view** on desktop: the posting's description, why it matched, other sources
   that saw it, deadline, status and notes, without leaving the feed.
3. **Track chips with counts** (Software, AI/ML/Data, Quant, ...) plus the Internships / New grad toggle,
   driven by the `role_track` field we already store.
4. **Work-model badge** (On Site / Hybrid / Remote) parsed from location and title.
5. **Transparency page:** `/api/metrics` already has drop latency p50/p95 per source; add "next sweep in"
   and source health in plain words. This is Boardsweep's "show our working".
6. **Table density toggle** and column picker for the All jobs page.
7. **Digest email shaped like Boardsweep's:** watchlist companies first, one row per role with an Apply
   button (T14 builds the email; this is its layout).
8. **Salary column**, only where a posting states pay (few do; see the salary-sort note in `PROGRESS.md`).
9. **First-run explainer** (Levels.fyi's modal) for a new user's empty feed.

Not worth copying: AI match percentages, autofill, resume builders, social proof counters.
