# T10: Deploy (always-on runner)
**Context:** 00-overview.md; requirements.txt, radar/__main__.py.
**Goal:** one command to an always-on server, replacing the hourly GitHub Actions job.
**Deliver:**
- `radar/__main__.py`: `python -m radar run` starts the scheduler; graceful shutdown on SIGTERM.
- `deploy/radar.service` (systemd) + `deploy/README.md`: a ~$5 VPS with a venv and `apt install tesseract-ocr`, secrets in an env file (mode 600).
  Note in the README that a home server/Raspberry Pi with the same unit is better for Instagram (home IP).
- Backups: nightly SQLite backup (stdlib `sqlite3` backup API) to `data/backups/`, keep 14.
- Heartbeat: if `HEARTBEAT_URL` is set, GET it after each scheduler loop (dead-man switch such as healthchecks.io), so a dead box alerts you.
- GitHub Actions demoted to CI (tests, pyflakes): remove the hourly schedule only once the runner has been live for a day.
**Accept:** `python -m radar run` against fixture sources polls, persists and shuts down cleanly; restore-from-backup test.
**Deferred:** Docker/compose, Fly.io, S3 uploads, Postgres/Redis, sharding, multi-tenant notes. Add when one box or one user is not enough.
