# Zero2Sudo Opportunity Monitor

Tracks career opportunities (Instagram @zero2sudo Stories, company career boards,
community lists) and alerts the owner. Currently an hourly GitHub Actions job
(`opportunity_monitor.py`); being rebuilt as "Drop Radar", an always-on service.
Plan and contracts: `docs/specs/`.

## Session handoff (2026-10-02)

- **Codex product review (T12, 2026-10-02):** see `docs/specs/T12-first-to-act.md`.
  Implemented pagination, per-source live events, concurrent user delivery, feed
  reconciliation, private subscription setup, sharing, recipient-only timing stats,
  and a residential Instagram relay. 385 offline tests pass on 3.12/3.14, 12 browser
  checks pass. Core deployed; latest per-Story ingestion/retry/stats changes await final
  redeploy. Another session repeatedly restarted `radar` during the live relay:
  coordinate deployments before retrying. Mac probe got 39 Stories; relay not yet
  verified end to end. LaunchAgent prepared, inactive. `IG_RELAY_ENABLED=1` on the VM
  skips its blocked native polling; owner's topic is staged in `/opt/radar/alert-cutover.env`,
  friend's separate topic is enabled (subscribe in their Settings). No device receipt
  verified. Legacy pushes remain on pending the full-day cutover. T11 stays deferred.

- Branch: `claude/trim-drop-radar-plan`. T0-T10 are all `done`; only T11
  (hardening) remains, explicitly `deferred` until the service has run live
  for a few weeks. `AGENTS.md` is a symlink to this file, so Codex and Claude
  read the same instructions.
- **Live since 2026-10-02 ~05:00 UTC** on an Oracle Cloud Always Free VM.
  Reach it with the `drop-radar` alias in `~/.ssh/config` on Kevin's Mac
  (OCI CLI auth is in `~/.oci/`). The public HTTPS address is the box's
  `<ip-with-dashes>.nip.io` hostname, served by Caddy. Both users log in with
  their own token from `/opt/radar/radar.env`; never commit the tokens or the
  IP. Layout and redeploy steps: `deploy/README.md`, especially "What the
  first live deploy did". Verified live: see the T10 row in
  `docs/specs/PROGRESS.md`.
- Deliberately off on the box: `NTFY_TOPIC` (hourly.yml still pushes, so
  enabling both would double-alert), `ANTHROPIC_API_KEY`,
  `HEARTBEAT_URL`. `GH_TOKEN` is set (classic, no scopes, read-only).
- **Deployed 2026-10-02:** 621 sources (was 86): ~560 boards mined from SimplifyJobs, plus Amazon, Google,
  Microsoft, Apple, Goldman (Oracle), Two Sigma/Koch/ManTech (Avature) and Citadel/Citadel Securities (their
  careers sitemaps -- the job pages 403). DB backup taken first (`/opt/radar/data/backups/`); config swaps keep
  a `.bak` in `/opt/radar/config/`. Rule for every new source: an honest User-Agent, and only a documented public
  API or a path robots.txt allows. So not covered: TikTok/ByteDance and Tesla (refuse non-browser clients
  everywhere, robots.txt included), iCIMS (robots.txt disallows all, no public API), Meta (robots.txt forbids
  automated collection without written permission). Simplify still covers them, ~3h late.
- **For review (2026-10-02):** commits `a98b04b..8fa8be9` on this branch -- conditional ATS polls,
  canonical_url ATS link shapes + startup re-canonicalize (`Runtime.__init__`), new sources (oracle,
  eightfold, amazon, google, apple, avature, sitemap, workable; search-based ones subclass
  `ats.WindowedSource`), Instagram `user_id` (skips `web_profile_info`). All deployed.
- **Instagram:** `IG_SESSIONID` is set on the box (since 06:25 UTC). Its first poll got 429 from the
  profile lookup, now skipped; the first poll with the stored id (~06:55 UTC) was not yet verified.
  If 429s persist, next free step: poll Instagram from the owner's Mac (home IP) and relay to the box.
- **Next, when the user asks: the alert cutover.** It's safe from about
  2026-10-03 (one day live, no unplanned restarts; the one counted restart
  was a deliberate SIGKILL test). Steps:
  1. Get the user's ntfy topic and add `NTFY_TOPIC` (plus `NTFY_TOPIC_FRIEND`
     if the friend wants pushes) to `radar.env`, then restart `radar`.
  2. Set the GitHub repo variable `LEGACY_ALERTS_ENABLED=false`, which gates
     hourly.yml's own push step.
  3. Later, drop hourly.yml's `schedule:`.

  Expect a one-time push burst for any zero2sudo Story still up when
  Instagram is first enabled; see the cutover notes in `deploy/README.md`.

## When the user says "start" (or "continue", "next")

Do this without asking questions:
1. Read `docs/specs/PROGRESS.md` and pick the first task whose status is `todo`
   (or `doing`: resume it). Dependencies are in `docs/specs/00-overview.md`.
2. Read ONLY `docs/specs/00-overview.md` and that task's spec, plus the files the
   spec lists under "Context". Do not read the rest of the repo up front.
   For a legacy function named in Context, locate it with `graphify explain "<fn>"`
   or `grep -n "def <fn>"` and Read only that range; never read the 2200-line
   `radar/legacy/opportunity_monitor.py` whole.
3. Set the task to `doing` in PROGRESS.md, implement it tests-first, and run
   the test and lint commands below.
4. Commit on the current branch (one commit per task), set the task to `done`
   with the commit hash and date in PROGRESS.md, push with `git push -u origin <branch>`.
5. Report in under 10 lines: what shipped, what was verified, what was not,
   and what the next task is. Then stop and wait for the user to say "start" again.

Exceptions:
- T3, T4 and T5 are independent. If all three are `todo`, offer once to run them
  as parallel subagents (each given only its spec + overview); otherwise do them in order.
- If a task's acceptance criteria cannot be met (for example live Instagram access),
  finish everything else, mark the task `done` with a clear "not verified live"
  note in PROGRESS.md, and say so.
- If every task is `done` or `deferred`, say so and suggest opening the PR. Never start a `deferred` task unless asked.

## Working rules
- Do not Read generated data whole: `LATEST.md`, `*.xlsx`, `monitor_*.json`,
  `enrichment_cache.json`, `QA_TEST_REPORT.md`, `graphify-out/`. When a spec needs
  their format, sample with code (`head -c`, `jq 'keys'`, openpyxl, `cmp`).
- Never push to a branch other than the one the session assigns. Do not open a PR
  unless asked.
- Tests are offline (no network); live probes are marked `@live` and skipped.
- Never commit secrets. Credentials come from env: `IG_SESSIONID`, `APIFY_TOKEN`,
  `ANTHROPIC_API_KEY`, `NTFY_TOPIC` (the first user's; others `NTFY_TOPIC_<ID>`), `API_TOKENS`
  (`user:secret,...`, >=20-char secrets, for `python -m radar serve`), `GOOGLE_SERVICE_ACCOUNT_JSON`, `GH_TOKEN` (optional for
  the legacy GitHub-issue alert; needed in production for `github_repo` sources — GitHub's
  unauthenticated rate limit is 60 req/hr, a token raises it to 5000; a public-read-only
  fine-grained token or a classic token with no scopes is enough, no write access needed).
- Preserve existing guarantees: row IDs are permanent, `Actioned?`/`Notes` are never
  overwritten, alerts are sent only after data is persisted, retries never duplicate.
- Use Anthropic models `claude-opus-5-5` (default) via the `anthropic` SDK; see
  `llm_extraction.py` for the established request shape (structured output, low effort,
  `fallbacks: "default"`).

## Commands
- Tests: `python -m unittest discover -s tests`
- Lint: `python -m pyflakes ./*.py radar tests`
- Offline demo: `python opportunity_monitor.py --fixture tests/fixtures/sample_items.json`
- If `python` or the deps are missing: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pyflakes`,
  then use `.venv/bin/python` (pyflakes stays out of requirements.txt, which CI installs hourly).
  Tests do not need tesseract; real OCR does.
- Code graph, when present (local only; hooks are per-clone): `graphify-out/`, kept fresh by
  `graphify hook install`; `.graphifyignore` excludes generated data.

## Current state (update when it changes)
- Live pipeline: `radar/legacy/` (`opportunity_monitor.py`, `job_pages.py`, `llm_extraction.py`,
  `instagram_scraper.py`, `google_sheets_sync.py`; root files are import shims), workflow `.github/workflows/hourly.yml`.
- 388 backend tests passing on Python 3.14; the preceding 326-test suite was also verified on Python 3.12, which `.github/workflows/ci.yml` now runs on every push/PR (a 3.12+3.14 matrix), split out from the hourly production workflow. Sources live: `radar/sources/` (ats.py + greenhouse/lever/ashby/smartrecruiters/workday, github_repo, instagram; registry.py auto-discovers them). SQLite store in `radar/store/` (DB at `data/radar.db`, gitignored);
  import the tracker with `python -m radar.store.migrate_legacy`; `radar.views.write_views` regenerates xlsx + LATEST.md. `radar/pipeline/` (normalize, dedupe, enrich, filter) is the Scheduler's `sink`: cross-source URL dedupe, LLM enrichment gated by a daily token budget, `matches_profile` against `config/profile.yaml`. `radar/alerts/` (`AlertDispatcher`, `NtfyChannel`) pushes instantly for zero2sudo items and anything matching the profile, claim-before-send idempotent, retried with in-memory backoff on every sink tick; `python -m radar stats` prints drop-latency p50/p95 per source. Multi-user (T8a): `config/users.yaml` lists users (first = owner) and each one's own watchlist/profile; the scheduler polls the union once; `actions` are per `(opportunity_id, user_id)`; `MultiUserAlertDispatcher` alerts a user only on their own sources' items. Profiles match role (track) AND keyword (level), whole words; `is_us_location` handles US locations; a trailing country name decides first ("Ho Chi Minh, , Vietnam" is not Chicago). SmartRecruiters listings carry location (blank before 2026-10-02, which let every foreign posting match). Verify any new board with `python -m radar.sources.discover --check` before adding it. ATS polls are conditional (ETag/304, all four ATS verified), so an unchanged board costs no download; the watchlists cover ~600 boards and career sites (incl. `oracle`, `eightfold`, `amazon`, `google`, `apple`, `avature`, `sitemap`, `workable` sources; search-based ones subclass `ats.WindowedSource`), mined 2026-10-02 from SimplifyJobs' active listings (`discover._slug_from_url` also parses Workday links), because Simplify lists a posting a median ~3h after the board does. `python -m radar serve` (alias `run`) runs scheduler + pipeline + the API (`radar/api/`: per-user feed, status/notes, config edits with hot reload, SSE stream; `docs/openapi.json` from `python -m radar openapi`) in one process. Tracker data lives in `Zero2Sudo_Opportunity_Tracker.xlsx`,
  `monitor_state.json`, `enrichment_cache.json` (committed by the workflow).

- T9 web is committed (`472b172`): `web/` React PWA with feed, board, sources, settings and token login. First-poll ATS/GitHub/Workday items now backfill silently (`raw.seed`), expose per-user `backfill` in the API/UI, and get season/track enrichment from titles without the LLM. Since 2026-10-02 the feed is digest-style (`web/src/components/FeedRow.tsx`, boardsweep.io as the reference): it defaults to **New** (`/api/opportunities?backfill=false`, filtered in SQL), sorted by newest *posted* (`sort=posted`; `store.SORT_KEYS` compares in UTC, date-only postings count as late that day as their sighting allows, undated backfill sorts last; `sort=found` is the other option); rows show "posted" and "found" separately, with Already open / All jobs tabs and Internships / New grad groups; `OpportunityCard` is Board-only. A `#token=<secret>` link signs a device in. 7 desktop/phone Playwright checks pass (`cd web && npm run e2e`, builds first). Live scraping/push delivery and Lighthouse performance were not reverified.

- T10 deploy is committed: `deploy/radar.service` (systemd; `--graceful-timeout`, default 10s, bounds `/api/stream`'s
  indefinitely-open SSE connections on shutdown; `TimeoutStopSec` gives systemd margin above that), `deploy/radar-backup.service`+`.timer`
  (nightly `python -m radar backup`, stdlib sqlite3 backup API, keeps the 14 most recent), `deploy/Caddyfile` (HTTPS for
  remote friend access) and `deploy/README.md` (full VPS setup, backup/restore, and the hourly-GitHub-Actions cutover
  checklist). `HEARTBEAT_URL` (env) gets a debounced GET from the scheduler (at most once a minute, not once a loop
  tick) for a dead-man switch (e.g. healthchecks.io). A crashed scheduler task now takes the whole `serve` process down
  with it, so `Restart=always` actually fires. `hourly.yml` only gained an `if:` gate on its push step (`LEGACY_ALERTS_ENABLED`, a no-op until set); its schedule stays live until
  `radar.service` has run a full day -- see `deploy/README.md` for the alert-double-push gate and reseed notes.
