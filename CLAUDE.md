# Zero2Sudo Opportunity Monitor

Tracks career opportunities (Instagram @zero2sudo Stories, company career boards,
community lists) and alerts the owner. Currently an hourly GitHub Actions job
(`opportunity_monitor.py`); being rebuilt as "Drop Radar", an always-on service.
Plan and contracts: `docs/specs/`.

## Session handoff (2026-10-01)

- Branch: `claude/trim-drop-radar-plan`. T9 web shipped in `472b172`; Codex finished
  the inherited first-day feed changes in `287bf51`, committed and pushed.
- Verified at `287bf51`: 326 offline backend tests on Python 3.14, pyflakes,
  exact generated OpenAPI match, frontend production build, and 6 Playwright
  checks across desktop/phone. The delayed-backfill browser test reproduced the
  empty-feed bug before the fix. Live scraping, push delivery and Lighthouse
  performance were not reverified; the updated suite was not rerun on 3.12.
- User asked how to test locally and how their friend could test remotely,
  then asked to wrap up for Claude. Remote testing was discussed, not set up:
  Codex started no app server or public tunnel, and no hosted URL or real login
  tokens were created. `ngrok` is not currently on PATH. User testing is unconfirmed.
- Suggested temporary route: run `python -m radar serve` on localhost:8000 with
  a separate test DB, fresh random `API_TOKENS` assigned to `friend`, and phone
  pushes/LLM calls disabled; expose it with `ngrok http 8000`. Share the HTTPS
  URL and only the friend's app token, not the ngrok account token. Mac and
  both processes must remain running. Settings saves edit the configured YAML
  files; copy config and set `RADAR_CONFIG_DIR` for an isolated preview.
- Next implementation task is T10 (`docs/specs/T10-deploy-scale.md`): always-on
  deployment, backups and heartbeat. Remote friend access needs HTTPS and
  separate user tokens. T11 remains deferred. Do not remove the legacy hourly
  schedule until the new runner has been live for a day; review PROGRESS.md's
  migration/alert-history/cursor-reseed notes before cutover.

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
- 326 backend tests passing on Python 3.14; the preceding 322-test suite was also verified on Python 3.12, which hourly CI uses. Sources live: `radar/sources/` (ats.py + greenhouse/lever/ashby/smartrecruiters/workday, github_repo, instagram; registry.py auto-discovers them). SQLite store in `radar/store/` (DB at `data/radar.db`, gitignored);
  import the tracker with `python -m radar.store.migrate_legacy`; `radar.views.write_views` regenerates xlsx + LATEST.md. `radar/pipeline/` (normalize, dedupe, enrich, filter) is the Scheduler's `sink`: cross-source URL dedupe, LLM enrichment gated by a daily token budget, `matches_profile` against `config/profile.yaml`. `radar/alerts/` (`AlertDispatcher`, `NtfyChannel`) pushes instantly for zero2sudo items and anything matching the profile, claim-before-send idempotent, retried with in-memory backoff on every sink tick; `python -m radar stats` prints drop-latency p50/p95 per source. Multi-user (T8a): `config/users.yaml` lists users (first = owner) and each one's own watchlist/profile; the scheduler polls the union once; `actions` are per `(opportunity_id, user_id)`; `MultiUserAlertDispatcher` alerts a user only on their own sources' items. Profiles match role (track) AND keyword (level), whole words; `is_us_location` handles US locations. Verify any new board with `python -m radar.sources.discover --check` before adding it. `python -m radar serve` runs scheduler + pipeline + the API (`radar/api/`: per-user feed, status/notes, config edits with hot reload, SSE stream; `docs/openapi.json` from `python -m radar openapi`) in one process; systemd/backups/hosting are T10. Tracker data lives in `Zero2Sudo_Opportunity_Tracker.xlsx`,
  `monitor_state.json`, `enrichment_cache.json` (committed by the workflow).

- T9 web is committed (`472b172`): `web/` React PWA with feed, board, sources, settings and token login. First-poll ATS/GitHub/Workday items now backfill silently (`raw.seed`), expose per-user `backfill` in the API/UI, and get season/track enrichment from titles without the LLM. Empty feeds refresh every 5s until populated; 6 desktop/phone Playwright checks pass (`cd web && npm run e2e`, builds first). T10 deploy is next; reseed old ATS/GitHub cursors and GitHub ETags at cutover to populate their backlog without alerts. Live scraping/push delivery and Lighthouse performance were not reverified.
