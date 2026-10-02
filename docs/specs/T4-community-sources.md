# T4: Community list source (GitHub repos)
**Context:** 00-overview.md; T2 (Source, FetchContext).
**Goal:** catch drops that land on the big curated lists, often hours before a company's own PR.
**Deliver:**
- `github_repo`: poll commits/contents of curated lists (SimplifyJobs/Summer2027-Internships, SimplifyJobs/New-Grad-Positions, etc.)
  with ETag (conditional requests are free and do not count against the GitHub rate limit); diff the README/JSON listing -> new rows become Items. 60s interval.
- Repos come from `repos:` in `config/watchlist.yaml`.
**Accept:** fixtures for the README/JSON listing; diff logic tested (new vs seen); 304 emits nothing; `published_at` set when the listing has a date.
**Deferred (add one when a real miss shows it is worth it):** reddit, hn_hiring (Algolia), generic rss, sitemap/page-hash watcher, telegram_public.
**Out of scope:** LinkedIn, Handshake, X/Twitter, Discord (ToS/login walls).
