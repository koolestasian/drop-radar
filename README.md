# Zero2Sudo Opportunity Monitor

An hourly GitHub Actions monitor for public **@zero2sudo** Instagram content.

It is deliberately broader than an internship tracker. The goal is to catch **actionable opportunities** without making you repeatedly open Instagram.

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

Open **[LATEST.md](LATEST.md)** for the current tracker in your browser. It
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

## One setup step left: add APIFY_TOKEN

The monitor uses Apify to retrieve public Instagram Stories and posts.

1. Create/sign into an Apify account.
2. In Apify Console, open **Settings → API & Integrations** and copy your API token.
3. In this GitHub repository open:

   **Settings → Secrets and variables → Actions → New repository secret**

4. Name it exactly:

   `APIFY_TOKEN`

5. Paste the token and save it.

**Never commit the token to this repository.**

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

# 2. Real check that only prints what it would add (uses Apify credits).
export APIFY_TOKEN=...
python opportunity_monitor.py --dry-run

# 3. Real check that updates the workbook and LATEST.md in this folder.
python opportunity_monitor.py
```

A local run skips GitHub Issues unless `GH_TOKEN` and `GITHUB_REPOSITORY` are
set, but still sends ntfy pushes when `NTFY_TOPIC` is set. To run it hourly
without GitHub, add a cron entry (`crontab -e`):

```
17 * * * * cd /path/to/zero2sudo-opportunity-monitor && APIFY_TOKEN=... NTFY_TOPIC=... python3 opportunity_monitor.py >> monitor.log 2>&1
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
- Status (New, Open, Reopened, Closed, or Expired once the deadline passes)
- Priority
- Actioned?
- Notes

There is also a Dashboard sheet with counts. It holds plain values rather than
formulas, so it also reads correctly in GitHub's preview and Google Drive.

Actioned? accepts `Yes`, `y`, `x`, `✓`, `done` or `applied`; they are all
normalized to `Yes`.

## Files

- `opportunity_monitor.py` — scraping, OCR, extraction, deduplication, Excel updates, GitHub alerts
- `google_sheets_sync.py` — optional Google Sheets mirror
- `requirements.txt` — Python dependencies
- `tests/` — unit tests; `tests/fixtures/sample_items.json` is a sample Apify payload for offline runs
- `.github/workflows/hourly.yml` — hourly cloud schedule
- `Zero2Sudo_Opportunity_Tracker.xlsx` — generated after the first successful run

## Notes

- Only public Instagram content is queried.
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
