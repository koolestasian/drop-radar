# T10: Deploy and scale
**Context:** 00-overview.md; Dockerfile-relevant files only (requirements.txt, radar/__main__.py).
**Goal:** one command to an always-on server; clear path beyond one box.
**Deliver:**
- `radar/__main__.py`: `python -m radar run` starts scheduler + API in one process; graceful shutdown; `--sources` filter for sharding.
- Dockerfile (multi-stage: build web, slim Python + tesseract), `docker-compose.yml` with volume for `data/`, healthcheck on `/api/health`.
- Deploy guides (pick one): Fly.io (`fly.toml`, volume), any $5 VPS (compose + Caddy for HTTPS), or home server/Raspberry Pi (home IP helps Instagram).
- Backups: nightly SQLite `.backup` to `data/backups` + optional S3/Backblaze upload.
- GitHub Actions demoted to: CI (tests, lint, build web), plus a cron heartbeat that opens an issue if `/api/health` is stale > 15 min.
- Scale notes (`docs/scaling.md`): 1 box handles ~1000 boards at 5 min (~3 req/s); beyond that shard by `--sources`, move SQLite -> Postgres (repository API isolates SQL), add Redis only when running >1 worker; per-user watchlists = multi-tenant (user_id on opportunities' actions/alerts).
**Accept:** `docker compose up` on a clean machine serves the app and polls fixture sources; health endpoint red when scheduler stalls; restore-from-backup test.
