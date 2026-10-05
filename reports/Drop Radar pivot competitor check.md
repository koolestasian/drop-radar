# Drop Radar pivot competitor check

Brainstorm research, 2026-10-05. Web searches only: product pages, articles and forum posts, not
hands-on trials. "Crowded" means public products exist for the same job; it does not mean they
are good. Nothing here was built, and no decision has been made.

## Current product (real-time early-career job radar)

| Competitor | What it does | Source |
|---|---|---|
| Simplify | YC W21; $3M seed led by Craft (2024), about $4.35M total; claims 1-2M job seekers; 7-person team | ycombinator.com/companies/simplify, techcrunch.com (2024-02-07), tracxn.com |
| Handshake | Campus recruiting; 92% of top four-year institutions; employer contracts median about $30k/yr | joinhandshake.com/career-centers, pin.com/blog/handshake-pricing |
| Fantastic.jobs | Solo founder; 200k+ career sites on 58 ATSes polled hourly; 5,000+ subscribers; from $95/month | fantastic.jobs/about |
| TheirStack | Job postings API; 73% of new tech postings same day | theirstack.com/en/job-posting-api |
| JobCopilot, Sonara, AIApply | Auto-apply and outreach agents | repo report: competitor automation review |

## Pivot 1: ghost-job detection

| Competitor | What it does |
|---|---|
| jobghost.io | Paste a LinkedIn URL; scores repost history, listing age, pay transparency |
| Knowitol Ghost Job Detector | Paste a listing; 15+ red flags |
| VantageCV | Free Chrome extension that flags ghost jobs |
| Subspace Ghost Job Scanner | Free Firefox extension |
| ghostjobs.io | Crowd-reported suspicious postings |

Tailwind: New York bill S8877 (a law-firm guide says it passed the legislature), Ontario rules from
2026, Kentucky and Pennsylvania proposals (CRS IF12977, WSJ). Revelio: fewer than half of US postings
lead to a hire.
Gap: these tools judge one listing at a time, mostly from LinkedIn. None found tracks a posting's
history at the employer's own job system. Consumer tools are free, so the money would have to come
from employers (compliance) or a job board. Not checked: compliance vendors for the New York law.
**Verdict: crowded as a consumer tool; a Ghost Job Index as published content is still open.**

## Pivot 2: trust layer for candidates

| Competitor | What it does |
|---|---|
| OpenAI jobs platform | Reported 2026 launch matching on verified skills and certifications (press and LinkedIn posts; not confirmed from OpenAI) |
| HackerRank, CodeSignal, Pymetrics, Eightfold | Skills assessment and inference for employers |
| Recruiting firms (e.g. Insero) | Human verification as a service |

Pain is real: Gartner says 39% of candidates use AI to apply; recruiters report fake candidates.
**Verdict: crowded, and OpenAI is reportedly entering. Keep it as a story, not a wedge.**

## Pivot 3: finance recruiting vertical

| Competitor | What it does |
|---|---|
| Trackr (the-trackr.com) | Founded 2022 (UK); US Finance 2027 tracker with opening and closing dates for banks, PE and VC (KKR, Bain Capital, Bessemer, Citi...); also UK, Europe, Asia and tech trackers |
| Adventis | Internship database; about 200 US and Canadian firms; about 1,000 junior summer applications per class |
| Extern | Bank-by-bank opening guides |
| Wall Street Oasis, Reddit | Community timelines |

**Verdict: crowded. Trackr already covers it. Possible edge: faster automated push alerts.**

## Pivot 4: opportunity radar beyond jobs

| Competitor | What it does |
|---|---|
| simplytk.com/opportunities | 98 curated accelerators, fellowships (Thiel, Z Fellows, Emergent Ventures, KP Fellows), hackathons and events; live feed and email alerts |
| AgenticGHX opportunities | Fellowships, grants, scholarships, hackathons sorted by deadline |
| Fastweb | Large scholarship database with matching |
| Devpost, MLH | Hackathon listings |

**Verdict: crowded with manually curated lists; small and shallow, but present.**

## Pivot 5: recruiting hub for student clubs

Institution-level alumni platforms: Hivebrite, Almabase, PeopleGrove, Graduway, WildApricot.
No club-specific recruiting product found in one search, so this is **inconclusive**. Club budgets are small.

## Pivot 6: scarce-opportunity radar outside hiring

Clinical trial matching: Tempus, Antidote, TrialX. Government contracts: GovSpend (has an MCP
server). Grants: Instrumentl ($1.1B+ in grants managed). **Verdict: crowded, and each needs domain depth.**

## Takeaways

- Every direction has competitors, and most look like single-founder or small-team products.
- The common gap: competitors are hand-curated (Trackr, simplytk), judge one listing at a time
  (ghost-job tools), or poll hourly and serve developers (Fantastic.jobs). Drop Radar's distinct
  asset is minute-level history pulled directly from each employer's job system.
- For the networking goal, the competitor founders are also the best people to contact.
