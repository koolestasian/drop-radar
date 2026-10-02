# The original hourly monitor (GitHub Actions)

> **Retired 2026-10-02.** This is the setup guide for the first version of the project: one scheduled
> GitHub Actions job that read @zero2sudo's Instagram, kept an Excel tracker and sent an alert. The
> always-on service in the [main README](../README.md) replaced it, and the workflow, the scripts at the
> repository root and the files it generated (`Zero2Sudo_Opportunity_Tracker.xlsx`, `LATEST.md`,
> `monitor_state.json`, `monitor_status.json`) were removed. To see it as it was, check out the tag
> `legacy-hourly-monitor`; the commands below only work there. The parts the service still uses (text extraction, URL cleanup, the Instagram client) live in `radar/legacy/`; the rest was removed afterwards.

## What it watches

Every hour, the workflow checks:

- active Instagram Stories
- recent feed posts / reels

It OCRs Story images and captures things such as:

- internships
- new-grad and early-career roles
- student / part-time jobs
- fellowships
- scholarships and grants
- hackathons and competitions
- conferences and summits
- recruiting events and career fairs
- direct-consideration forms
- referrals and talent programs
- networking events and meetups
- coffee chats and office hours
- workshops, webinars, and info sessions
- mentorships and cohorts
- campus / ambassador / university programs
- research programs
- apprenticeships and externships
- accelerators and incubators
- application openings / reopenings / deadlines
- other unusual opportunities with a concrete apply/register/RSVP action

Generic career advice, motivational content, and duplicate opportunities are filtered out.

## What happens automatically

When the monitor finds something genuinely new:

1. It creates or updates **Zero2Sudo_Opportunity_Tracker.xlsx** in this repository.
2. It updates **LATEST.md**, a permanent browser view that requires no download.
3. It deduplicates previously seen opportunities using stable Instagram/media
   identity, and treats a Story that re-shares an already-tracked job posting
   as a repost rather than a new alert.
4. If configured, it synchronizes the same rows to a permanent Google Sheet.
5. It creates a **GitHub Issue assigned to the repository owner** only after persistence succeeds.
6. GitHub sends the normal issue/assignment notification through your GitHub notification settings.

If nothing new is found, it stays quiet.

Every run also re-derives the extracted columns (organization, title, category,
deadline, status, priority) for **all** stored rows from their saved Raw Text.
Parser improvements therefore apply to the whole tracker without re-scraping,
and an alert always shows the same title the tracker does. Row IDs, First Seen,
Actioned? and Notes are never rewritten.

### Where to see updates

Open **[LATEST.md](../LATEST.md)** for the current tracker in your browser. It
updates at the same URL after each successful run, so there is nothing to
download. The Excel workbook remains a formatted backup.

LATEST.md is organized for triage:

- **⏰ Closing within 14 days**, sorted by deadline, with days remaining
- **🆕 New in the last 7 days**
- **📋 Earlier**
- collapsed **✅ Actioned** and **⌛ Past deadline or closed** sections

🔥 marks a high-priority company and ⭐ a SWE / AI / data role. Story-only rows
say when the Story has expired, so a dead link is not a surprise.

### Optional: use Google Sheets as the live tracker

Google Sheets provides a familiar spreadsheet at one permanent URL and preserves
edits made in the Actioned? and Notes columns.

1. Create a Google Cloud project and enable the Google Sheets API.
2. Create a service account and download its JSON key.
3. Create a Google Sheet and share it with the service-account email as Editor.
4. Add the complete JSON key as a GitHub Actions secret named
   GOOGLE_SERVICE_ACCOUNT_JSON.
5. Copy the Sheet ID from its URL and add it as a secret named GOOGLE_SHEET_ID.
6. Run the workflow once, then set the repository Actions variable
   GOOGLE_SYNC_REQUIRED to true.

Never commit the service-account JSON. Without these secrets, the monitor uses
LATEST.md as the permanent live view and continues maintaining the Excel backup.

Each successful check commits `monitor_status.json` with the check time,
previous/new/total row counts, and workbook checksum. The Actions summary shows
these counts after verifying the uploaded bytes on `main`. If no new opportunities
are found, the workbook is intentionally unchanged and the status still updates.
The hourly schedule is configured for minute 17; actual scheduled execution can
be delayed. A green manual or push run alone does not verify the scheduler.

Runs start from current main, back up the workbook, preserve user fields,
deduplicate new records, verify saved IDs, update the browser/Google views, and
commit before sending alerts. Unexpected scraper response formats fail the run.
A durable notification queue makes alert retries safe.

## Setup: choose how to scrape Instagram

The monitor has two scrapers. Use either or both; with both, the native one
runs first and Apify takes over automatically if it fails.

| | Native scraper (`IG_SESSIONID`) | Apify (`APIFY_TOKEN`) |
|---|---|---|
| Cost | Free | Pay per actor run |
| Speed | 2 HTTP requests | Queued actor run, often minutes |
| Story link stickers and CTA links | Read directly | Depends on the actor |
| Needs | An Instagram login cookie | An Apify account |
| Weak spot | Instagram can expire the session or block cloud IPs | Actor changes and cost |

**Recommended:** set both. Every check then tries the free native scraper
first and never misses a Story when Instagram pushes back. The run summary,
`monitor_status.json` (`scrapers`, `scrape_warnings`), and a workflow warning
say whenever Apify had to step in; that usually means the session expired.

### Native scraper: add IG_SESSIONID

Stories are only served to logged-in viewers, so the native scraper uses the
session cookie of an Instagram account.

1. Use a **secondary Instagram account**, not your personal one. Automated
   access is against Instagram's terms, and Instagram may challenge or limit
   an account it thinks is automated.
2. Log in to instagram.com in a desktop browser with that account.
3. Open developer tools → **Application** (Chrome) or **Storage** (Firefox) →
   **Cookies** → `https://www.instagram.com`, and copy the value of `sessionid`.
4. Add it as a repository secret named `IG_SESSIONID`.

The cookie is equivalent to that account's password; keep it in secrets only.
It lasts for months unless you log out, change the password, or Instagram
asks for a security check. If the run summary shows a fallback warning, log
in on the web again, clear any checkpoint, and replace the secret.

To force one scraper, set the repository variable `SCRAPER` to `native` or
`apify` (default `auto`).

**ToS risk is ongoing, not one-time.** Automated Instagram access stays against
Instagram's terms for as long as the scraper runs, not just at setup; an
account can be challenged or limited at any time, which is why Drop Radar caps
`instagram:` in `config/watchlist.yaml` at 5 accounts (`load_watchlist` raises
if you add a 6th) instead of scaling it like the ATS and feed sources.

### Apify: add APIFY_TOKEN

1. Create/sign into an Apify account.
2. In Apify Console, open **Settings → API & Integrations** and copy your API token.
3. In this GitHub repository open **Settings → Secrets and variables → Actions → New repository secret**.
4. Name it `APIFY_TOKEN`, paste the token and save it.

**Never commit either credential to this repository.**

### Optional: better extraction with Claude

Set the secret `ANTHROPIC_API_KEY` (from console.anthropic.com) and every new
post is read by Claude, together with the job page when it can be fetched. It
returns the employer, the exact role title, category, season, location and
deadline, and flags posts that are not really opportunities (memes, advice,
offer celebrations). Those posts are skipped instead of alerting, and older
rows it flags move to a collapsed "Probably not an opportunity" section.

- Model: `claude-opus-5-5` at low effort; set the variable `ANTHROPIC_MODEL`
  to use another model.
- Cost: roughly $0.02 per post. Existing rows are backfilled 25 per run
  (`LLM_BACKFILL_PER_RUN`), about $5 once for the current tracker, then
  roughly $5 a month at ten posts a day.
- Results are cached in `enrichment_cache.json` by post text, so a post is
  never sent twice and re-deriving the tracker makes no API calls.
- If the API is unavailable, the run continues with the built-in parsers.

### Automatic: job page checks

No setup needed. For every application link the monitor reads the real
posting: Greenhouse, Lever, Ashby and SmartRecruiters through their public
APIs, other sites through the schema.org JobPosting data most career pages
embed. That supplies the exact job title, location and (when the page states
one) the deadline, and each open link is re-checked once a day (up to 80 per
run). When a posting is taken down, its row is marked **Closed** and moves to
the collapsed section of LATEST.md, so you stop spending time on dead links.
Only a definitive answer (HTTP 404/410, "inactive", missing from the job
board) closes a row; timeouts and blocked requests never do. Set the variable
`JOB_PAGES=off` to disable it.

## Start it

After adding the secret:

1. Open **Actions**.
2. Click **Zero2Sudo Opportunity Monitor**.
3. Click **Run workflow**.
4. Open the run and verify all steps are green.

The first successful run creates `Zero2Sudo_Opportunity_Tracker.xlsx` automatically.

After that, GitHub runs the workflow every hour at minute 17. GitHub schedules can occasionally start a few minutes late.

## Run it locally

Everything also works from your own machine, without GitHub Actions.

```bash
pip install -r requirements.txt
# OCR engine: macOS `brew install tesseract`, Ubuntu `sudo apt-get install tesseract-ocr`

# 1. Offline demo: no token, no network, no cost, writes nothing.
python opportunity_monitor.py --fixture tests/fixtures/sample_items.json

# 2. Real check that only prints what it would add.
export IG_SESSIONID=...        # and/or APIFY_TOKEN=...; optional ANTHROPIC_API_KEY=...
python opportunity_monitor.py --dry-run

# 3. Real check that updates the workbook and LATEST.md in this folder.
python opportunity_monitor.py
```

Running from home also sidesteps the main weakness of the native scraper:
Instagram trusts a residential IP far more than a cloud runner's.

A local run skips GitHub Issues unless `GH_TOKEN` and `GITHUB_REPOSITORY` are
set, but still sends ntfy pushes when `NTFY_TOPIC` is set. To run it hourly
without GitHub, add a cron entry (`crontab -e`):

```
17 * * * * cd /path/to/zero2sudo-opportunity-monitor && IG_SESSIONID=... NTFY_TOPIC=... python3 opportunity_monitor.py >> monitor.log 2>&1
```

Run the tests with `python -m unittest discover -s tests`.

## Spreadsheet columns

The workbook tracks:

- Organization
- Opportunity
- Category
- Role / Track
- Season / Year
- Location
- Deadline (an ISO date such as `2026-10-15` when the post names one, so it sorts)
- Application / Registration Link
- Instagram Source
- Source Type
- Raw Text
- Status (New, Open, Reopened, Closed when the posting is taken down, Expired
  once the deadline passes, or Not actionable when Claude is confident the post
  is not an opportunity)
- Priority
- Actioned?
- Notes

There is also a Dashboard sheet with counts. It holds plain values rather than
formulas, so it also reads correctly in GitHub's preview and Google Drive.

Actioned? accepts `Yes`, `y`, `x`, `✓`, `done` or `applied`; they are all
normalized to `Yes`.

## Files

- `opportunity_monitor.py` — scraping, OCR, extraction, deduplication, Excel updates, GitHub alerts
- `instagram_scraper.py` — native Instagram Stories/posts scraper
- `job_pages.py` — reads job postings (ATS APIs, JSON-LD) and detects takedowns
- `llm_extraction.py` — optional Claude extraction
- `enrichment_cache.json` — cached job-page facts and Claude extractions
- `google_sheets_sync.py` — optional Google Sheets mirror
- `requirements.txt` — Python dependencies
- `tests/` — unit tests; `tests/fixtures/sample_items.json` is a sample Apify payload for offline runs
- `.github/workflows/hourly.yml` — hourly cloud schedule
- `Zero2Sudo_Opportunity_Tracker.xlsx` — generated after the first successful run

## Notes

- Only public Instagram content is read; the native scraper views it through the account whose session you provide.
- Stories are ephemeral, so hourly monitoring substantially reduces the chance of missing a short-lived opportunity.
- The Story scraper is a third-party Apify actor. Instagram changes can occasionally require changing the actor or parsing logic.
- Apify charges can depend on actor/result usage, so check your Apify usage dashboard after the first few days.
- The filter intentionally favors **recall over perfect precision**: missing a useful opportunity is worse than occasionally surfacing a borderline one.

## Workflow philosophy

**Zero2Sudo posts something actionable → GitHub checks it → Excel updates → you get one GitHub alert → you decide whether to act.**

No hourly Instagram refreshing required.


## Cleaner alerts

The monitor now ranks new opportunities and makes GitHub alerts much easier to scan:

- **HIGH** — a company on the high-priority list (default: Palantir, Anduril,
  Scale AI, Primer, Vannevar Labs, Shield AI, OpenAI, Anthropic, Databricks)
- **MEDIUM** — a software engineering, AI / ML, data science or data engineering role
- **NORMAL** — everything else actionable

To change the high-priority list, add a repository **variable** (Settings →
Secrets and variables → Actions → Variables) named `HIGH_PRIORITY_ORGS` with a
comma-separated list, for example `Palantir, Jane Street, Ramp`.

GitHub Issue titles now look like:

`🚨 [HIGH] Palantir — Software Engineering — APPLY / OPEN`

The direct application link is placed prominently in the alert.

### Optional: instant phone push with ntfy

GitHub notifications still work without this. If you want an immediate dedicated phone push:

1. Install the **ntfy** app on your phone.
2. Pick a long, random topic name, for example:
   `khanh-zero2sudo-7f3c9b2a91`
3. Subscribe to that exact topic in the ntfy app.
4. In this GitHub repository go to:
   **Settings → Secrets and variables → Actions → New repository secret**
5. Name the secret:
   `NTFY_TOPIC`
6. Set the value to only your topic name, not the full URL.

Once that secret exists, the hourly workflow automatically sends a push when something new is found.

HIGH-priority alerts use ntfy's urgent notification priority and include an **Apply / Open** action that jumps directly to the opportunity link.

If `NTFY_TOPIC` is not configured, the workflow does not fail; it simply uses GitHub Issue/email notifications only.

Using a self-hosted ntfy server or a protected topic? Set the repository
variable `NTFY_SERVER` (for example `https://ntfy.example.com`) and/or the
secret `NTFY_TOKEN` (an ntfy access token).
