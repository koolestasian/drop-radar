# T4: Community and feed sources
**Context:** 00-overview.md; T2 (Source, FetchContext).
**Goal:** catch drops that appear on lists and communities, often hours before a company's own PR.
**Deliver:**
- `github_repo`: poll commits/contents of curated lists (SimplifyJobs/Summer2027-Internships, SimplifyJobs/New-Grad-Positions, etc.)
  with ETag; diff the README/JSON listing -> new rows become Items. 60s interval (conditional requests are free).
- `reddit`: `r/csMajors`, `r/internships`, `r/cscareerquestions` via `.json`/RSS; keep only posts that match opportunity regex or contain an apply link; 120s.
- `hn_hiring`: monthly "Who is hiring" thread (Algolia API) -> comments as Items.
- `rss`: generic feed source (company blogs, newsletters, university career centers).
- `sitemap`: watch a career-site sitemap/landing page hash and emit when it changes (for companies with no ATS API).
- `telegram_public`: `https://t.me/s/<channel>` public preview scrape for opportunity channels.
**Accept:** fixtures per source; diff logic tested (new vs seen); every source sets `published_at` when the feed has it; robots.txt respected for sitemap/HTML fetches.
**Out of scope:** LinkedIn, Handshake, X/Twitter, Discord (ToS/login walls).
