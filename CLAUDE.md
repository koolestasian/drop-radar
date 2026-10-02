# Zero2Sudo Opportunity Monitor

Tracks career opportunities (Instagram @zero2sudo Stories, company career boards,
community lists) and alerts the owner. Currently an hourly GitHub Actions job
(`opportunity_monitor.py`); being rebuilt as "Drop Radar", an always-on service.
Plan and contracts: `docs/specs/`.

## Session handoff (2026-10-01)

- Branch: `claude/trim-drop-radar-plan`. T0-T10 are all `done`; only T11
  (hardening) remains, and it's explicitly `deferred` until the service has
  run live for a few weeks. T9 web shipped in `472b172` (reviewed Codex's
  handoff of it in `4fc6425`); T10 deploy shipped this session (see
  `docs/specs/PROGRESS.md`'s T10 row for the full list).
- T10 highlights: `serve`'s shutdown is now actually graceful even with an
  open `/api/stream` (SSE) connection (`--graceful-timeout`, real-subprocess
  tested); a crashed scheduler task takes the whole process down so
  systemd's `Restart=always` fires instead of uvicorn quietly serving a
  process that stopped polling; `HEARTBEAT_URL` + `python -m radar backup`
  for the dead-man switch and nightly backups; `deploy/` has the systemd
  units, a `Caddyfile` for HTTPS, and a `README.md` covering VPS setup,
  restore-from-backup, and the hourly-GitHub-Actions cutover (double-push
  gating, when a cursor reseed is/isn't needed, the one-time Instagram
  re-push). None of `deploy/README.md` was exercised on a real VPS.
- **Not done yet, if the user wants remote friend access next:** no box has
  actually been provisioned. `deploy/README.md` replaces the earlier ad hoc
  ngrok suggestion with a real plan (systemd + Caddy + the friend's own
  `API_TOKENS` entry), but someone still has to run through it on a real
  host before the friend can use this remotely.
- Do not remove `hourly.yml`'s `schedule:` trigger until `radar.service` has
  actually run live for a day with no restarts -- that's still true and
  still not done (nothing has been deployed yet this session).

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
- 338 backend tests passing on Python 3.14; the preceding 326-test suite was also verified on Python 3.12, which `.github/workflows/ci.yml` now runs on every push/PR (a 3.12+3.14 matrix), split out from the hourly production workflow. Sources live: `radar/sources/` (ats.py + greenhouse/lever/ashby/smartrecruiters/workday, github_repo, instagram; registry.py auto-discovers them). SQLite store in `radar/store/` (DB at `data/radar.db`, gitignored);
  import the tracker with `python -m radar.store.migrate_legacy`; `radar.views.write_views` regenerates xlsx + LATEST.md. `radar/pipeline/` (normalize, dedupe, enrich, filter) is the Scheduler's `sink`: cross-source URL dedupe, LLM enrichment gated by a daily token budget, `matches_profile` against `config/profile.yaml`. `radar/alerts/` (`AlertDispatcher`, `NtfyChannel`) pushes instantly for zero2sudo items and anything matching the profile, claim-before-send idempotent, retried with in-memory backoff on every sink tick; `python -m radar stats` prints drop-latency p50/p95 per source. Multi-user (T8a): `config/users.yaml` lists users (first = owner) and each one's own watchlist/profile; the scheduler polls the union once; `actions` are per `(opportunity_id, user_id)`; `MultiUserAlertDispatcher` alerts a user only on their own sources' items. Profiles match role (track) AND keyword (level), whole words; `is_us_location` handles US locations. Verify any new board with `python -m radar.sources.discover --check` before adding it. `python -m radar serve` (alias `run`) runs scheduler + pipeline + the API (`radar/api/`: per-user feed, status/notes, config edits with hot reload, SSE stream; `docs/openapi.json` from `python -m radar openapi`) in one process. Tracker data lives in `Zero2Sudo_Opportunity_Tracker.xlsx`,
  `monitor_state.json`, `enrichment_cache.json` (committed by the workflow).

- T9 web is committed (`472b172`): `web/` React PWA with feed, board, sources, settings and token login. First-poll ATS/GitHub/Workday items now backfill silently (`raw.seed`), expose per-user `backfill` in the API/UI, and get season/track enrichment from titles without the LLM. Empty feeds refresh every 5s until populated; 6 desktop/phone Playwright checks pass (`cd web && npm run e2e`, builds first). Live scraping/push delivery and Lighthouse performance were not reverified.

- T10 deploy is committed: `deploy/radar.service` (systemd; `--graceful-timeout`, default 10s, bounds `/api/stream`'s
  indefinitely-open SSE connections on shutdown; `TimeoutStopSec` gives systemd margin above that), `deploy/radar-backup.service`+`.timer`
  (nightly `python -m radar backup`, stdlib sqlite3 backup API, keeps the 14 most recent), `deploy/Caddyfile` (HTTPS for
  remote friend access) and `deploy/README.md` (full VPS setup, backup/restore, and the hourly-GitHub-Actions cutover
  checklist). `HEARTBEAT_URL` (env) gets a debounced GET from the scheduler (at most once a minute, not once a loop
  tick) for a dead-man switch (e.g. healthchecks.io). A crashed scheduler task now takes the whole `serve` process down
  with it, so `Restart=always` actually fires. `hourly.yml` itself is untouched; its schedule stays live until
  `radar.service` has run a full day -- see `deploy/README.md` for the alert-double-push gate and reseed notes.
