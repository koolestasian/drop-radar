# Zero2Sudo Opportunity Monitor

Tracks career opportunities (Instagram @zero2sudo Stories, company career boards,
community lists) and alerts the owner. Currently an hourly GitHub Actions job
(`opportunity_monitor.py`); being rebuilt as "Drop Radar", an always-on service.
Plan and contracts: `docs/specs/`.

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
  `ANTHROPIC_API_KEY`, `NTFY_TOPIC`, `GOOGLE_SERVICE_ACCOUNT_JSON`.
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
- 110 tests passing (88 legacy + 22 radar). SQLite store in `radar/store/` (DB at `data/radar.db`, gitignored);
  import the tracker with `python -m radar.store.migrate_legacy`; `radar.views.write_views` regenerates xlsx + LATEST.md. Tracker data lives in `Zero2Sudo_Opportunity_Tracker.xlsx`,
  `monitor_state.json`, `enrichment_cache.json` (committed by the workflow).
