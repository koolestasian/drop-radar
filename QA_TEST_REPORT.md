# Zero2Sudo Opportunity Monitor QA Report

Tested: 2026-09-17 Pacific time  
Repository: `koolestasian/zero2sudo-opportunity-monitor`  
Production workbook state: 50 rows at commit `5957dc6e`  
Live smoke run: [Actions run 35304995603](https://github.com/koolestasian/zero2sudo-opportunity-monitor/actions/runs/35304995603)

## Verdict

**FAIL — persistence works, but extraction quality and semantic deduplication do
not meet the app's purpose.**

The latest live run saved and byte-verified the workbook before creating the
alert. The workbook is structurally valid and all five persistence tests pass.
However, 9 of the 10 rows added by that run repeat earlier opportunity titles,
and all 10 point their application field at Instagram CDN media rather than an
application destination.

## Test matrix

| Area | Result | Evidence |
|---|---|---|
| Python compile/import | PASS | Monitor and test files compile |
| Existing automated tests | PASS | 5/5 persistence tests |
| Workbook commit | PASS | Run 35304995603 pushed commit `5957dc6e` |
| Post-push byte verification | PASS | Workflow `cmp` checks completed |
| Alert ordering | PASS | Push completed 03:58:00Z; issue created 03:58:02Z |
| Workbook structure | PASS | 50 rows, 50 unique IDs, expected headers, filter `A1:R51`, freeze pane `A2` |
| Workbook formulas | PASS WITH LIMITATION | No formula errors; cached dashboard results are blank until Excel recalculates |
| Semantic deduplication | FAIL | 9 duplicated title groups account for 18 rows; 9/10 latest rows repeat earlier titles |
| Application links | FAIL | 22/50 links are Instagram media; 10/10 latest links are media |
| Title/actionability quality | FAIL | At least 15/50 titles are obvious fragments or anecdotes |
| URL extraction | FAIL | `https://example.com/jobs/123` is truncated to `https://example.com/job` |
| Malformed scraper payload | FAIL | HTTP-200 object payload returns an empty list and can produce a green run |
| Priority classification | FAIL | “Career fair” becomes MEDIUM via substring `ai`; “at scale” becomes HIGH via substring `scale` |
| Hourly scheduler | UNVERIFIED | Four runs exist: three push and one manual; zero scheduled runs |
| ntfy delivery | UNTESTED | `NTFY_TOPIC` is not configured |

## Findings

### P1 — Semantic deduplication fails when Instagram CDN URLs rotate

Expected: the same Story is stored once across hourly runs.

Actual: nine of the ten newest rows have titles already present earlier in the
workbook. Their CDN host/query changed between runs, producing new IDs even
though the underlying Story content did not.

Impact: the tracker and alerts grow with repeat entries on each check.

Recommended fix: derive Story identity from a stable actor Story/media ID. When
that field is absent, fingerprint normalized OCR text plus a stable media cache
key while excluding CDN hostnames, signatures, query strings, and OCR-only
punctuation variation. Add a regression fixture containing the same Story with
two CDN URLs.

### P1 — Media files are presented as application links

Expected: the application field contains a direct external destination or stays
blank and falls back to the Instagram source in the alert.

Actual: 22 of 50 application fields point to `cdninstagram.com`; all ten newest
rows do. The alert labels these links “Open.”

Impact: users click an expiring image rather than an application page.

Recommended fix: never use media URLs as application destinations. Store only
validated external links in the application field. Use the Instagram source as a
clearly labeled fallback when no external link exists.

### P1 — HTTP-200 schema changes can silently become successful empty checks

Expected: an unexpected Apify response shape fails the run.

Actual: `run_actor` returns `[]` for any non-list JSON payload.

Impact: an actor error object or schema change can make the workflow green while
opportunities are missed.

Recommended fix: validate the response schema and raise an error for non-list
payloads, including a safe summary of the unexpected response.

### P2 — URL regex truncates URLs at the letter “s”

Expected: caption URL `https://example.com/jobs/123` is preserved.

Actual: the parser returns `https://example.com/job`.

Cause: the regex uses `[^\\s...]`, which excludes the literal character
`s` instead of whitespace.

Recommended fix: use `r"https?://[^\s<>\\\"']+"` and add URL fixtures with
`jobs`, query strings, punctuation, and multiple links.

### P2 — Priority uses unrestricted substring matching

Expected: only explicit AI and Scale AI matches affect priority.

Actual: “career fair” contains `ai` and becomes MEDIUM; “learn at scale” becomes
HIGH.

Impact: noisy alerts are incorrectly elevated.

Recommended fix: use token/phrase regexes with word boundaries and treat
`Scale AI` as the organization phrase rather than the bare word `scale`.

### P2 — Actionability and titles are too permissive

Expected: each row describes an opportunity the user can act on.

Actual: examples include “Microsoft SWE Intern Offer + Process!”, “Hiring
happens 1–6 months,” “also no sign up form,” and “This is why I care so much
about making opportunity.”

Impact: advice, anecdotes, and discussion fragments create tracker rows and
alerts.

Recommended fix: require either a validated external action link or a stronger
combination of opportunity and action/deadline language. Add negative fixtures
for offers, process discussions, advice, recaps, and questions.

### P3 — Dashboard values have no saved calculation cache

The formulas are valid and the workbook requests a full recalculation on open,
but cached values are blank. Excel should calculate them after opening; tools
that only read cached values may show blanks.

Recommended fix: if repository previews must show metrics, calculate and save
the summary values explicitly or recalculate with a supported spreadsheet
engine before committing.

## Verified state

- Workbook rows: 50
- Unique technical IDs: 50
- Semantic duplicate title groups: 9
- Media/Instagram application links: 22
- Likely fragment titles: at least 15
- Status counts: 43 New, 5 Open, 2 Closed
- Category counts: 33 Internship, 6 New Grad/Early Career, 4 Other, 3
  Job/Hiring, 2 Recruiting/Career Event, 1 Workshop/Info Session, 1
  Referral/Talent Network
- Schedule configuration: minute 17 every hour
- Observed scheduled runs: 0

## Release recommendation

Do not rely on the current alerts as a clean list of new opportunities. The
system is safe to continue running as a data-gathering prototype because it now
persists reliably, but semantic deduplication, link selection, schema validation,
and actionability filtering should be fixed before treating it as a dependable
hourly monitor.
