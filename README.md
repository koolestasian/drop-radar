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
