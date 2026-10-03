# T16: automate the trivial work instead of hardcoding it

Owner's goal (2026-10-03): stop hand-maintaining lists (logo overrides, company names, location
words, watchlist slugs, tiers) and hand routine judgment to a cheap model or a public data source.
The plan was approved as a whole. Build it as small, separately deployed slices.

## The pattern every slice follows
1. **Source fact.** Use what the posting or board already says. It's free and the most trustworthy.
2. **Free lookup.** Wikidata, the YC directory, GeoNames, Clearbit.
3. **Cheap LLM.** Use one only for what is still unknown.
4. **Verify.** A real fetch or data check must agree before anything is stored.
5. **Fallback.** Show a monogram or "unknown", and retry later. Never cache a miss forever.

Store each answer with its provenance: `source`, `verified`, `checked_at`, and a version.
Fixers only **fill**, never overwrite a value a source stated clearly (the same rule as `pagefacts`).

## Constraints
- **The box:** 954 MB RAM, 2 vCPU. No local models, no headless browser, and no large dataset
  held in memory. Batch jobs run off-box: on the Mac, as a scheduled cloud agent, or as a GitHub
  Actions cron.
- **Source rule:** an honest User-Agent, and only documented APIs or paths that robots.txt
  allows. Reuse `pagefacts._get` / `_robots_allows` for every new fetch, since they are
  SSRF-guarded.
- **Owner's yes:** writes to `radar.env`, live-DB repairs and deploys each need the owner's
  explicit yes. Two agents deploy to the same box, so follow `CLAUDE.md`'s pre-deploy checks.
- **Existing guarantees still hold:**
  - row IDs are permanent;
  - `Actioned?`/Notes are never overwritten;
  - alerts go out only after data is persisted.

## LLM choice (decided, 2026-10-03)
**Claude Haiku 4.5 is the model.** Gemini is used only where it can't hit its free-tier rate
limit; in practice, as the fallback when Haiku fails (owner's call).

The bake-off ran on Drop Radar's own data. The harness is `data/bake/` (gitignored):
`bake.py run|report`.

| Model | Result |
|---|---|
| Haiku 4.5, Sonnet 5.5, Gemini 3.1 Flash-Lite, Gemini 3.5 Flash-Lite | Tied on Stories (company 22-23/23, city and date near perfect) and on page facts (company 36-37/40, pay 16/19). |
| Gemini free tier | Stalled 60-180 s on about 5% of calls. Gemini 2.5 Flash-Lite is closed to new users. |
| Haiku | Never took more than 3.5 s. |
| GPT-5.6 Luna | Untested: the OpenAI account has no credit. |

**Haiku gotchas:**
- Haiku 4.5 **rejects the `effort` parameter** (it returns a 400).
- The legacy extractor (`radar/legacy/llm_extraction.py`) sends `effort` and the
  `server-side-fallback` beta, and its model defaults to **Opus 5.5** (`ANTHROPIC_MODEL`).
- LLM guesses must pass the homepage check. Haiku invented 6 name-shaped domains that don't exist.

**Keys:**
- On the Mac: `~/.config/drop-radar/llm.env` (mode 600).
- On the box: `ANTHROPIC_API_KEY` has been set since 2026-10-03, together with
  **`LLM_EXTRACTION=off`**, so the legacy Story extractor stays off. Backup:
  `radar.env.bak-pre-anthropic`.

## Slices

| # | Slice | Status |
|---|---|---|
| 16.1 | Logos: verified ladder | **done, live**; the live `fix-logos` write is waiting on the owner (see below) |
| 16.2 | Delete `filter.py`'s location lists | todo |
| 16.3 | Turn the LLM on: Stories, junk titles, pay | todo |
| 16.4 | Self-growing watchlist + review queue | todo |
| 16.5 | Adaptive polling + learned priority | todo (feeds T14) |
| 16.6 | Learn from the user | todo |
| 16.7 | Maintenance by agent | todo |
| 16.8 | Company names from source data | todo |

### 16.1 Logos (done: commits 168780a, e713cdd, eee8958; live since 2026-10-03 20:18 UTC)

**How it works now** (`radar/logos.py`):
- **Rungs, in order:** the posting's JSON-LD `hiringOrganization` (`pagefacts.org_site`), then
  Wikidata (SPARQL, with a 10-minute back-off on 429), then Clearbit autocomplete, then Haiku given
  the posting's link and title (with Gemini as fallback).
- **What gets accepted:**
  - a homepage `<title>`/`og:site_name` that names the company in **whole words**; or
  - for non-LLM sources only, a domain that equals the name on a commercial ending
    (`rocketlabusa.com`).
- **What never gets accepted:** job-board or social hosts.
- **Retries:** misses retry after 7 days. A result from an older ladder (`v` != `VERSION`) is
  retried. A lookup where a rung crashed is not cached.
- **Measured** on the 202 live misses (from the Mac, read-only): about 118 recovered, which takes
  logo coverage from 79% to about 91%.

**Still to do:**
- **`fix-logos`:** `python -m radar fix-logos [--dry-run]` checks every company, replaces cached
  domains whose homepage names someone else, and fills misses. The **dry run ran on the box**, and
  its report is in `/opt/radar/data/fix-logos-dryrun.txt`.
  1. Show the owner the replacements first.
  2. Run it without `--dry-run` only after the owner says yes, since it writes to the live DB.
  3. Run it as `sudo -u radar bash -c "cd /opt/radar/zero2sudo-opportunity-monitor && set -a &&
     . /opt/radar/radar.env && set +a && .venv/bin/python -m radar fix-logos"`.
- **Bad company names:** some names came from URL slugs ("Boxinc", "Ashbyhq" which is really
  Quora, "Acuityinc"), so their logos are wrong or missing. See 16.8.
- **Wikidata:** the rung was rate-limited during every test, so it is unproven. If it stays
  blocked, switch it to the Action API (`wbsearchentities` + `wbgetentities` P856, at 1 req/s).
- **Optional:** Brandfetch's CDN with `fallback/lettermark` could replace the 16px-globe hack in
  `web/src/components/common.tsx` `CompanyLogo`. It needs a free client ID.

### 16.2 Delete the duplicate location lists
- **What's duplicated:** `radar/pipeline/filter.py`'s `_US_CITIES`, `_NON_US`, `_US_NAMESAKES`
  and `_COUNTRY_RE` (about 400 hand-typed places) repeat what `radar/pipeline/places.py` (GeoNames)
  already resolves.
- **Change:** the US check uses `places.py`'s country.
- **Gate:** run a script over **every stored row** that prints each row where the old and new
  verdicts differ. The owner reviews the diff. Tests missed every real problem before.
- **Optional follow-up:** send the roughly 7% of places `places.py` can't resolve to Haiku, and
  validate its answer against GeoNames.

### 16.3 Turn the LLM on (needs the owner's yes to flip `LLM_EXTRACTION`)
1. **Fix the legacy extractor for Haiku:** no `effort`, no fallback beta. Set
   `ANTHROPIC_MODEL=claude-haiku-4-5` explicitly. The daily token budget in `enrich.py` stays.
2. **Story images:** Haiku vision, with tesseract as the fallback. Haiku scored 27/28 on
   opportunity vs not and 23/23 on company in the bake-off.
3. **Junk titles** ("Other Opportunity · 2026"): rewrite them only when the title matches a
   generic pattern.
4. **Pay range and blank facts:** extract them from page text pagefacts already fetched, and only
   fill blanks.

### 16.4 Self-growing watchlist (everything goes to a review queue, never straight to live)
- **Feeders:**
  - **Community lists:** run Simplify/community-list apply links through
    `discover._slug_from_url`, probe each board, and queue it.
  - **YC directory:** `yc-oss.github.io/api/companies/all.json` lists 6,269 companies with
    website and `isHiring`. Probe their ATS slugs. Runs off-box.
  - **job-board-aggregator** (`Feashliaa/job-board-aggregator`): its license is CC BY-NC (personal
    use is fine). Pin a commit, since nothing checks its integrity. Runs off-box.
  - **Paste a careers URL in Settings:** detect the ATS and add the board.
- **Self-repair:** a board that 404s gets slug variants tried across ATSes. A board with 0
  postings for 30 days is archived and logged.

### 16.5 Adaptive polling + learned priority (feeds T14's priority push)
- **The problem:** `TIER_INTERVAL_S` (`radar/sources/ats.py:22`) ties poll speed to a hand-set
  S/A/B/C tier.
- **Change:** learn each board's posting hours from its `first_seen` history. Get priority from an
  LLM prestige guess (cached on the company) plus the user's actions, with an override in Settings.

### 16.6 Learn from the user
- **Profile suggestions:** after repeated dismissals with the same pattern, suggest a profile edit
  the user approves ("add 'sales' to exclude?").
- **"Why didn't I see this?":** the user pastes a link, it is dry-run through the pipeline, and the
  app says which gate dropped it. This doubles as a T13 audit tool.

### 16.7 Maintenance by agent
- **Weekly routine:** a scheduled cloud agent runs `discover --check` and opens a PR with dead-slug
  fixes and a health report. **PRs only: it never deploys and never writes the live DB.**
- **Nightly canary:** push "radar is quiet" when nothing has arrived within a set window.

### 16.8 Company names from source data
- **The problem:** some company names were derived from slugs ("Boxinc", "Ashbyhq",
  "Acuityinc", "Voyagertechnologiesinc").
- **Fix:** take the name from JSON-LD `hiringOrganization.name` or the matched record. Change the
  display only; the stored text stays.
- **Then:** merge duplicates that share a company and a job id. The Ashby `jr_id` duplicates from
  before 0.9.0 still exist.

## Context for whoever continues
- **Code:** `radar/logos.py`, `radar/pipeline/pagefacts.py` (`_get`, `_robots_allows`,
  `org_site`), `radar/pipeline/enrich.py`, `radar/legacy/llm_extraction.py`,
  `radar/pipeline/filter.py`, `radar/pipeline/places.py`, `radar/sources/discover.py`,
  `radar/sources/ats.py`.
- **Release:** each slice merged to `main` gets a `CHANGELOG.md` entry, a `web/package.json` bump
  and a `vX.Y.Z` tag (owner's rule). 16.1 isn't merged yet; the branch is
  `claude/trim-drop-radar-plan`.
