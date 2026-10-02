# Zero2Sudo Opportunity Monitor

Tracks career opportunities (Instagram @zero2sudo Stories, company career boards,
community lists) and alerts the owner. Currently an hourly GitHub Actions job
(`opportunity_monitor.py`); being rebuilt as "Drop Radar", an always-on service.
Plan and contracts: `docs/specs/`.

## Session handoff (2026-10-02)

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
  enabling both would double-alert), `IG_SESSIONID`, `ANTHROPIC_API_KEY`,
  `HEARTBEAT_URL`. `GH_TOKEN` is set (classic, no scopes, read-only).
- **Committed, NOT deployed (2026-10-02):** `a98b04b` (311 more boards, ETag polls, ntfy priority) and the
  canonical_url fix after it. The box still runs 86 sources. Deploy = the documented rsync, then copy
  `config/watchlist.yaml` to `/opt/radar/config/` only if the live one still matches `912dfb2`'s (else
  merge: it may hold Settings edits), then restart. On restart `Runtime` re-canonicalizes stored URLs.
  Held back for batch 2: ~180 Workday boards with 2-4 active Simplify postings.
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
- 355 backend tests passing on Python 3.14; the preceding 326-test suite was also verified on Python 3.12, which `.github/workflows/ci.yml` now runs on every push/PR (a 3.12+3.14 matrix), split out from the hourly production workflow. Sources live: `radar/sources/` (ats.py + greenhouse/lever/ashby/smartrecruiters/workday, github_repo, instagram; registry.py auto-discovers them). SQLite store in `radar/store/` (DB at `data/radar.db`, gitignored);
  import the tracker with `python -m radar.store.migrate_legacy`; `radar.views.write_views` regenerates xlsx + LATEST.md. `radar/pipeline/` (normalize, dedupe, enrich, filter) is the Scheduler's `sink`: cross-source URL dedupe, LLM enrichment gated by a daily token budget, `matches_profile` against `config/profile.yaml`. `radar/alerts/` (`AlertDispatcher`, `NtfyChannel`) pushes instantly for zero2sudo items and anything matching the profile, claim-before-send idempotent, retried with in-memory backoff on every sink tick; `python -m radar stats` prints drop-latency p50/p95 per source. Multi-user (T8a): `config/users.yaml` lists users (first = owner) and each one's own watchlist/profile; the scheduler polls the union once; `actions` are per `(opportunity_id, user_id)`; `MultiUserAlertDispatcher` alerts a user only on their own sources' items. Profiles match role (track) AND keyword (level), whole words; `is_us_location` handles US locations. Verify any new board with `python -m radar.sources.discover --check` before adding it. ATS polls are conditional (ETag/304, all four ATS verified), so an unchanged board costs no download; kevin's watchlist covers ~380 boards, mined 2026-10-02 from SimplifyJobs' active listings (`discover._slug_from_url` also parses Workday links), because Simplify lists a posting a median ~3h after the board does. `python -m radar serve` (alias `run`) runs scheduler + pipeline + the API (`radar/api/`: per-user feed, status/notes, config edits with hot reload, SSE stream; `docs/openapi.json` from `python -m radar openapi`) in one process. Tracker data lives in `Zero2Sudo_Opportunity_Tracker.xlsx`,
  `monitor_state.json`, `enrichment_cache.json` (committed by the workflow).

- T9 web is committed (`472b172`): `web/` React PWA with feed, board, sources, settings and token login. First-poll ATS/GitHub/Workday items now backfill silently (`raw.seed`), expose per-user `backfill` in the API/UI, and get season/track enrichment from titles without the LLM. Empty feeds refresh every 5s until populated; 6 desktop/phone Playwright checks pass (`cd web && npm run e2e`, builds first). Live scraping/push delivery and Lighthouse performance were not reverified.

- T10 deploy is committed: `deploy/radar.service` (systemd; `--graceful-timeout`, default 10s, bounds `/api/stream`'s
  indefinitely-open SSE connections on shutdown; `TimeoutStopSec` gives systemd margin above that), `deploy/radar-backup.service`+`.timer`
  (nightly `python -m radar backup`, stdlib sqlite3 backup API, keeps the 14 most recent), `deploy/Caddyfile` (HTTPS for
  remote friend access) and `deploy/README.md` (full VPS setup, backup/restore, and the hourly-GitHub-Actions cutover
  checklist). `HEARTBEAT_URL` (env) gets a debounced GET from the scheduler (at most once a minute, not once a loop
  tick) for a dead-man switch (e.g. healthchecks.io). A crashed scheduler task now takes the whole `serve` process down
  with it, so `Restart=always` actually fires. `hourly.yml` only gained an `if:` gate on its push step (`LEGACY_ALERTS_ENABLED`, a no-op until set); its schedule stays live until
  `radar.service` has run a full day -- see `deploy/README.md` for the alert-double-push gate and reseed notes.
