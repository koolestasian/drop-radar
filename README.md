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
2. It deduplicates previously seen opportunities.
3. It creates a **GitHub Issue assigned to the repository owner** with the new opportunity links.
4. GitHub sends the normal issue/assignment notification through your GitHub notification settings.

If nothing new is found, it stays quiet.

### Where to see updates

The live copy is the workbook **in this GitHub repository**. An Excel file
previously downloaded to your computer, or attached to a chat, is a separate
snapshot and does not automatically refresh. Download the repository copy again
to see later rows, or download the workbook artifact from a successful Actions run.

Each successful check commits `monitor_status.json` with the check time,
previous/new/total row counts, and workbook checksum. The Actions summary shows
these counts after verifying the uploaded bytes on `main`. If no new opportunities
are found, the workbook is intentionally unchanged and the status still updates.
The hourly schedule is configured for minute 17; actual scheduled execution can
be delayed. A green manual or push run alone does not verify the scheduler.

Runs start from current `main`, preserve existing rows, deduplicate new records,
verify the saved IDs, and commit before sending alerts. Scrape failures fail the
run instead of masquerading as an empty successful check. Notification failures
are warnings and cannot prevent tracker persistence. A downloadable snapshot is
saved before pushing, so it remains available if the push fails.

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

## Spreadsheet columns

The workbook tracks:

- Organization
- Opportunity
- Category
- Role / Track
- Season / Year
- Location
- Deadline
- Application / Registration Link
- Instagram Source
- Source Type
- Raw Text
- Status
- Priority
- Actioned?
- Notes

There is also a Dashboard sheet.

## Files

- `opportunity_monitor.py` — scraping, OCR, extraction, deduplication, Excel updates, GitHub alerts
- `requirements.txt` — Python dependencies
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

- **HIGH** — especially relevant organizations / opportunities
- **MEDIUM** — strong SWE / AI / data / internship / new-grad matches
- **NORMAL** — everything else actionable

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
