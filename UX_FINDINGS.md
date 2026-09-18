# Zero2Sudo Opportunity Monitor — user experience findings

Executed from `UX_METAPROMPT.md` against commit `f704e24`, workbook state
**40 rows**, on 2026-09-18.

## Verdict

**The plumbing is solid. The product is not yet trustworthy.**

Correctness is genuinely good and has improved a lot: 23/23 tests pass, the
workbook is byte-verified on `main` after every push, alerts fire only after
persistence, and the notification queue is idempotent. Every P1 in
`QA_TEST_REPORT.md` has been addressed.

But the promise printed in the README is *"no hourly Instagram refreshing
required"*, and the tracker does not yet earn that. Reading all 40 rows as a
student would:

- **6 of 40 rows (15%) are not recognizable as an opportunity at all** — they
  are OCR fragments and sentence fragments.
- **12 of 40 rows (30%) have no application link** and dead-end at
  `instagram.com/stories/zero2sudo/`, which is empty once the Story expires.
- **Deadline is empty in 40 of 40 rows (100%)** — the single most decision-
  relevant field in an opportunity tracker never populates.
- **Priority has no spread**: 32 Medium, 8 Normal, **0 High**. A ranking where
  80% of items share one rank is not a ranking.
- **Titles collide**: three separate rows all read `Visa — Software
  Engineering` while pointing at a Bellevue new-grad role, an Austin APM
  internship, and a Foster City finance internship.

So roughly **half the rows either can't be identified or can't be acted on**.
At that rate a user still opens Instagram to check, which is the exact cost the
tool exists to remove.

---

## Findings, ranked by user attention wasted

### 1. Deadline is 100% empty — the column that should drive every decision

**What the user sees:** every Deadline cell blank, in the workbook, in
`LATEST.md`, and in the alert table.

**Why it costs them:** a tracker without deadlines can't be triaged or sorted.
The user must open all 28 linked rows to find out which close first. That is
the work the tool was supposed to do.

**Cause (verified):** `extract_deadline` only matches a date *immediately
following* one of four trigger words. Real caption phrasing misses constantly:

| Caption text | Extracted |
|---|---|
| `Apply by October 3rd!` | `October 3` ✅ |
| `apply by Oct. 3, 2026` | `Oct. 3, 2026` ✅ |
| `Applications close Friday` | *(empty)* ❌ |
| `Apply before Oct 3` | *(empty)* ❌ |
| `Closes in 2 days` | *(empty)* ❌ |
| `Deadline is this Sunday` | *(empty)* ❌ |

**Smallest fix:** add `close[sd]?`, `closing`, `ends`, `before`, `last day` to
the trigger set; allow a date to appear *before* the trigger; resolve relative
dates (`this Friday`, `in 2 days`, `tonight`) against `Posted At`; and match a
bare date near action language. Store an ISO date in a second column so it
sorts, keeping the raw string for display.

### 2. Identical titles for different jobs

**What the user sees:** rows 1, 11, 12 are all `Visa — Software Engineering`.
Rows 31, 36, 38 are all `Amazon — Software Engineering`.

**Why it costs them:** they look like duplicate-detection failures, so the user
stops trusting dedup — and they must open each link to tell them apart.

**Cause (verified):** `opportunity_title()` returns `f"{org} — {role}"` as soon
as an organization is known, discarding the specific job title even when the
application URL contains it. The Bellevue row's own link reads
`Software-Engineer--New-College-Grad--Bellevue---2027`.

**Smallest fix:** when org+role would collide with an existing row, append a
distinguishing token derived from the URL slug or the season/location already
extracted — e.g. `Visa — Software Engineer, New College Grad (Bellevue 2027)`.
The data is already in the row; it is being thrown away at formatting time.

### 3. OCR fragments reach the tracker and the alert, and are never cleaned

**What the user sees, verbatim from the committed workbook:**

- `you use etc. when you submit`
- `career fair but we are definitely`
- `So many Capi SWE Intern Offers!`
- `User Quant Firm SWE Intern semeliie`

**Why it costs them:** these are the rows that make a person distrust the whole
list. Three of the four also have no link, so there is no way to even recover
what they meant.

**Cause (verified):** `conservative_record_title()` is the cleanup safety net,
but its `low_quality` test only catches titles that are over 100 chars, start
with `-([@|`, end with `?&,|`, or match `NEGATIVE_CONTEXT_RE`. All four strings
above pass through **unchanged**:

```
'you use etc. when you submit'        -> 'you use etc. when you submit'
'career fair but we are definitely'   -> 'career fair but we are definitely'
'So many Capi SWE Intern Offers!'     -> 'So many Capi SWE Intern Offers!'
```

**Smallest fix:** add positive gating rather than negative filtering — a title
kept verbatim must contain a role, an org, or an opportunity noun *and* must
not end mid-clause (trailing conjunction/preposition/pronoun: `and`, `but`,
`we`, `you`, `when`, `etc.`). Otherwise fall back to `role or category`.

### 4. Related: the alert always shows the *uncleaned* title

**What the user sees:** the push and the Issue can name an opportunity
differently from what the tracker settles on.

**Cause (verified by data flow):** in `main()`, cleanup runs at the *start* of
a run over already-stored records. New rows are appended with the raw
`opportunity_title()` output, then `queue_batch(new_rows)` alerts on that raw
text. `conservative_record_title()` only touches them on the *next* run.

This is not hypothetical — commit history shows it happening at scale:

| Run | New rows | Total | Cleanup on next run |
|---|---|---|---|
| `5957dc6` 03:57 | **10** | 50 | — |
| `76cae41` 04:26 | 0 | **40** | **10 duplicates removed, 22 invalid links cleared** |

The user was alerted about 10 opportunities, then all 10 were silently deleted
as duplicates 29 minutes later. The tracker self-corrected; **the notification
never did.**

**Smallest fix:** run new rows through `cleanup_records()` *before* `append_rows`
and `queue_batch`, so the alert and the tracker agree at the moment of sending.

### 5. Priority is dead weight — the HIGH tier is unreachable for most of its list

**What the user sees:** 0 of 40 rows are High. Everything is Medium.

**Cause (verified):** `priority_for()` matches `high_org_re` against the
`Organization` field only, but `Organization` is populated exclusively from
`KNOWN_ORGS` / `DOMAIN_ORGS`. Six of the nine HIGH-priority organizations
appear in neither list, so they can never be assigned as an organization and
therefore **can never be scored HIGH**:

```
palantir   in KNOWN_ORGS=True   in DOMAIN_ORGS=True
anduril    in KNOWN_ORGS=True   in DOMAIN_ORGS=True
databricks in KNOWN_ORGS=True   in DOMAIN_ORGS=True
scale ai   in KNOWN_ORGS=False  in DOMAIN_ORGS=False   <-- unreachable
primer     in KNOWN_ORGS=False  in DOMAIN_ORGS=False   <-- unreachable
vannevar   in KNOWN_ORGS=False  in DOMAIN_ORGS=False   <-- unreachable
shield ai  in KNOWN_ORGS=False  in DOMAIN_ORGS=False   <-- unreachable
openai     in KNOWN_ORGS=False  in DOMAIN_ORGS=False   <-- unreachable
anthropic  in KNOWN_ORGS=False  in DOMAIN_ORGS=False   <-- unreachable
```

Confirmed directly: `organization_from_links(["https://openai.com/careers/x"])`
returns `''`.

The MEDIUM tier has the opposite problem — `\binternship\b` matches `Category`,
and 27 of 40 rows are internships, so nearly everything is Medium.

**Smallest fix:** keep the three lists in sync (a single `ORGS` table mapping
domain → display name → tier), match priority against the full row text rather
than only `Organization`, and make the user's own interests configurable rather
than hardcoded in a regex.

### 6. 30% of rows dead-end at an expired Story

12 of 40 rows have no application link and fall back to
`instagram.com/stories/zero2sudo/`. Stories expire in 24 hours, so for anything
older than a day that link shows nothing. The row is a permanent record that an
opportunity existed and is now unrecoverable.

This is *better* than the old behavior of linking to expiring CDN media —
`external_links()` correctly refuses media URLs now. But the user-facing result
is still a dead end.

**Smallest fix:** archive the Story image to the repo (or as a workflow
artifact) and link *that*, so the user can at least read the original slide.
Then label the row honestly: `No link — original slide` rather than
`View Instagram source`.

### 7. Location is 30% filled because it is a 17-city hardcoded list

Verified misses: `Atlanta, GA`, `San Jose, CA`, `London office`,
`Denver, Colorado`, `Toronto` all return empty. Only `Remote` matched.

**Smallest fix:** match a `City, ST` / `City, State` pattern generically plus a
`Remote`/`Hybrid`/`Onsite` modifier, instead of enumerating cities.

### 8. Organization names are raw domain slugs

`Withwaymo`, `Q2ebanking`, `Genevatrading`, `Scaleai` — derived by title-casing
a hostname. It reads like a bug even though the row is otherwise correct.

**Smallest fix:** a display-name override table, and strip leading `careers`/
`with`/`jobs` and ATS hosts before prettifying.

### 9. Setup is a three-service, unverifiable cliff

A fresh clone **cannot run**: `python -m unittest discover -s tests` fails
immediately with `ModuleNotFoundError: No module named 'openpyxl'`. The README
never says `pip install -r requirements.txt`, never mentions the `tesseract-ocr`
system package that OCR requires, and offers no local/dry-run path at all —
GitHub Actions is the only way to see output.

Before one row appears the user must: create an Apify account, get a token,
create a repo secret, and run a workflow. To get the "permanent live view" they
are actually steered toward, add a Google Cloud project, the Sheets API, a
service account, a JSON key, a shared sheet, two more secrets, and an Actions
variable. That is **13+ steps across 3 services**, with no `--dry-run` to
confirm any of it before spending Apify credits.

There is also no `.gitignore`, so `__pycache__/` shows up as untracked noise on
a first local run.

**Smallest fix:** a `--dry-run --fixture sample.json` mode that produces a
workbook and a `LATEST.md` from a checked-in sample payload with no token, no
network, and no cost. It makes the tool demonstrable in 30 seconds and doubles
as a regression fixture.

### 10. Only Stories are producing rows

All 40 rows are `Source Type: Story`. Zero posts/reels have ever produced a row,
despite `fetch_posts()` running every time and being billed by Apify. Either
`onlyPostsNewerThan: "2 days"` plus the actionability filter rejects everything,
or the post actor's field names don't match what `item_text()` reads. Worth
confirming before paying for it hourly — but note posts are *permanent*, so
they're the more reliable source, and getting zero from them is suspicious.

---

## What's missing

Things a person tracking opportunities would reasonably expect:

- **Nothing closes the loop.** `Actioned?` is `No` on 40/40 rows and `Notes` is
  empty on 40/40. There is no way to mark "applied," "rejected," or
  "interviewing" from the phone where the alert arrives. The tracker records
  what was *posted*, never what the user *did*.
- **No expiry or archive.** Deadlines pass and rows stay `New` forever.
  `Status` is `New` on 34/40 and never changes on its own.
- **No digest option.** Alerts are per-run only. There is no "one summary at
  8am" mode, which is what most people actually want from an hourly monitor.
- **No search or filter.** `LATEST.md` is one flat table with no grouping by
  category, deadline, or priority.
- **No dedup across near-identical postings** from different sources.
- **Dashboard formulas have no cached values**, so GitHub's xlsx preview and
  most non-Excel viewers show blanks (carried over from `QA_TEST_REPORT.md` P3).
- **No cost visibility.** Nothing reports Apify usage, so the first surprise is
  the bill.
- **No scheduler proof.** Cron is set to `17 * * * *`, but every run in history
  is push- or manually-triggered (03:41, 03:57, 04:26, 04:41). A completed
  `schedule` event still has not been observed.

---

## How to scale this

Four different axes, each blocked by something different:

**More rows.** `LATEST.md` is a flat markdown table of every row ever seen. At
40 rows it's fine; at 500 it's unusable, and every run rewrites the whole file.
`workbook_records()` also loads the entire workbook into memory each run.
*Constraint:* no pagination, no archive, no per-row page.
*Fix:* split into `LATEST.md` (last 14 days, grouped by deadline) plus a
generated `ARCHIVE/` directory, or publish a small static site from the data.

**More sources.** Adding LinkedIn, Discord, RSS, or a second Instagram account
means touching `fetch_stories`/`fetch_posts`/`normalize_item` directly — they're
hardwired to two Apify actors and one `USERNAME`.
*Constraint:* the 1,193-line monolith has no source abstraction.
*Fix:* a `Source` protocol returning normalized items, with the extraction
pipeline source-agnostic. This is the single highest-leverage refactor, and it
should come before adding any source.

**More users.** Everything is one repo, one workbook, one owner's GitHub Issues,
one ntfy topic, one interest regex hardcoded in `priority_for`.
*Constraint:* git-as-database and repo-scoped identity.
*Fix:* if this ever serves more than you, the state has to leave git — SQLite
committed as a file is the cheap intermediate step; a real datastore is the
real answer. Move the interest list to a `config.yml` first; that alone makes
the repo forkable by a friend.

**More runs.** `monitor_status.json` changes on every run, so the workflow
commits **24 times a day, ~8,760 commits a year**, and the `.xlsx` is a binary
zip that git cannot delta-compress (45–58 KB per stored version).
*Constraint:* using the git history as a log.
*Fix:* write status to the Actions job summary and a workflow artifact rather
than committing it; commit the workbook only when rows actually change; keep a
plain-CSV mirror alongside the xlsx so git can diff and compress it.

---

## Ideas

### Cheap wins — highest value per hour of work

1. **Fix the deadline extractor** and add an ISO `Deadline (sorted)` column.
   Turns the tracker from a list into a queue. *Biggest single win.*
2. **Run new rows through `cleanup_records()` before alerting**, so the
   notification and the tracker never disagree. Fixes finding #4 with a
   ~3-line reorder in `main()`.
3. **Add `--dry-run` with a checked-in fixture.** Removes the setup cliff, makes
   it demoable with zero cost, and becomes a permanent regression test.
4. **Unify `KNOWN_ORGS`, `DOMAIN_ORGS`, and `high_org_re` into one table** with
   a `tier` field. Fixes the dead HIGH tier and the ugly org names at once.
5. **Disambiguate colliding titles** using the URL slug already in the row.
6. **Add `.gitignore` and a `pip install -r requirements.txt` line to the
   README.** Two minutes; removes the first-impression failure.
7. **Stop committing `monitor_status.json` every run** — job summary instead.

### Larger bets

8. **Replace regex extraction with a single LLM call per new item.** Send OCR
   text plus the caption, get back structured JSON: org, exact role title,
   deadline, season, location, and an is-this-actionable boolean with a
   confidence score. This collapses findings #1, #2, #3, #7, and #8 into one
   component. At ~10 new items/day the cost is negligible, and Haiku is fast
   enough for the hourly budget. Keep the regex path as the offline fallback
   and as the `--dry-run` engine. **This is the change that would move the
   verdict from "prototype" to "dependable."**
9. **Fetch the application link and read the real job page.** The user's link
   already points at Workday/Greenhouse/Lever; one fetch yields the canonical
   title, location, and deadline far more reliably than OCR ever will. It also
   gives you free link-rot detection — auto-set `Status: Closed` when a posting
   404s, which fixes the "everything is New forever" problem.
10. **Close the loop from the notification.** Issue labels (`applied`,
    `rejected`, `interviewing`) synced back into `Actioned?`/`Notes`, so the
    user triages from their phone and the tracker reflects reality.
11. **Daily digest mode** (`DIGEST_HOUR`) — batch the day's finds into one 8am
    alert, with the hourly run still capturing ephemeral Stories.
12. **Confidence tiers instead of a single stream.** Split high-confidence rows
    (external link + org + role) from low-confidence ones into a `Review` sheet.
    Preserves the README's stated recall-over-precision bias without paying for
    it in the main view.
13. **Static site instead of `LATEST.md`** — GitHub Pages, grouped by deadline,
    with filters. Solves the row-scaling problem and is nicer on a phone.

---

## What was verified vs. inferred

**Verified by execution:** all 23 tests pass; `openpyxl` missing on a fresh
clone; every column fill rate and count above; deadline/location/org/priority
behavior probed directly against the real functions; `conservative_record_title`
leaving the four junk titles unchanged; the six unreachable HIGH orgs; the
50→40 cleanup in commit history; xlsx blob sizes; no `.gitignore`.

**Inferred, not executed:** alert rendering (no live GitHub/ntfy call was made —
reconstructed from `github_issue()` and `ntfy_alert()`); the cause of zero
post/reel rows; Apify cost behavior.

**Untestable here:** live scraping (no `APIFY_TOKEN`), OCR quality
(`tesseract` is not installed in this environment), Google Sheets round-trip,
and whether the hourly `schedule` event ever fires.
