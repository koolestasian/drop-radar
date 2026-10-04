# Deploying Drop Radar (T10)

One always-on process (`python -m radar serve`: scheduler + pipeline + API,
serving the built web app) on one small host, replacing the original hourly GitHub
Actions job. See `../docs/specs/00-overview.md` and `../docs/specs/archive/T10-deploy-scale.md`.

A home server or Raspberry Pi on your home network, not a VPS, is the better
host **if you use the Instagram source**: Instagram is far more likely to
flag a residential IP as a normal browser session than a well-known cloud
datacenter range. Everything below applies the same either way; it's just
where you run it. A ~$5/mo VPS is simpler to keep updated and is fine if you
drop the `instagram:` watchlist entries (ATS/GitHub sources don't care).

## 1. Layout

Keep the git checkout, the live-edited config, and the database in separate
places, so a `git pull` to redeploy new code never touches the other two and
`git status` in the checkout never shows local drift:

    /opt/radar/
      zero2sudo-opportunity-monitor/   # git clone; read-only at runtime
        .venv/                         # created here, not committed
      config/                          # RADAR_CONFIG_DIR: users.yaml + each user's watchlist/profile
      data/                            # RADAR_DB_PATH's directory: radar.db + backups/
      radar.env                        # secrets, mode 600

Why config lives outside the repo: `PUT /api/config/watchlist` and
`/api/config/profile` rewrite those YAML files on disk and call
`runtime.reload()` (see `radar/api/app.py`). If `RADAR_CONFIG_DIR` pointed at
the checkout's own `config/`, every edit made through Settings in the web app
would show up as an uncommitted change in `git status` and silently diverge
from whatever's in version control next time someone runs `git pull`.

```
sudo useradd -r -m -d /opt/radar radar
sudo -u radar git clone <this repo's URL> /opt/radar/zero2sudo-opportunity-monitor
sudo -u radar mkdir -p /opt/radar/config /opt/radar/data
sudo -u radar cp -r /opt/radar/zero2sudo-opportunity-monitor/config/. /opt/radar/config/
```

## 2. Python environment

```
sudo apt update && sudo apt install -y python3-venv tesseract-ocr   # tesseract: Instagram OCR only
cd /opt/radar/zero2sudo-opportunity-monitor
sudo -u radar python3 -m venv .venv
sudo -u radar .venv/bin/pip install -r requirements.txt
```

## 3. Build the web app

`create_app` serves `web/dist` at `/` if it exists; without it `/` 404s and
there's no UI (the API still works). Vite needs a newer Node than Ubuntu's
`apt` package ships (check against `web/package.json`'s `engines`, if any,
or just use current Node) -- install it from
[NodeSource](https://github.com/nodesource/distributions) rather than `apt`:

```
curl -fsSL https://deb.nodesource.com/setup_current.x | sudo -E bash -
sudo apt install -y nodejs
cd /opt/radar/zero2sudo-opportunity-monitor/web
sudo -u radar npm ci
sudo -u radar npm run build
```

Or build `web/dist` elsewhere (anywhere with Node) and `rsync` it over --
either way, re-run after every code change that touches `web/`.

## 4. Secrets: `/opt/radar/radar.env` (mode 600)

```
API_TOKENS=kevin:<32+ char secret>,friend:<a different 32+ char secret>
NTFY_TOPIC=<kevin's ntfy.sh topic>
NTFY_TOPIC_FRIEND=<friend's own ntfy.sh topic>      # see channels_for() in radar/alerts
IG_SESSIONID=...                                     # only if tracking Instagram
APIFY_TOKEN=...                                      # Instagram fallback
GH_TOKEN=...                                         # github_repo sources: 60/hr unauthenticated, 5000/hr with this
ANTHROPIC_API_KEY=...                                # LLM enrichment; optional, degrades to regex-only without it
RADAR_CONFIG_DIR=/opt/radar/config
RADAR_DB_PATH=/opt/radar/data/radar.db
HEARTBEAT_URL=https://hc-ping.com/<your-check-uuid>  # optional; see "Heartbeat" below
```

Make a token with `python -c 'import secrets; print(secrets.token_urlsafe(32))'`
(`parse_api_tokens` in `radar/config.py` rejects anything under 20 characters).

```
sudo chown radar:radar /opt/radar/radar.env
sudo chmod 600 /opt/radar/radar.env
```

## 5. systemd

```
sudo cp radar.service radar-backup.service radar-backup.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now radar.service radar-backup.timer
sudo systemctl status radar.service
curl -s http://127.0.0.1:8000/healthz
```

`radar.service`'s `ExecStart` binds `127.0.0.1` only -- never `0.0.0.0`. The
API trusts a bearer token alone (no HTTPS of its own), so anything public
must sit behind a TLS-terminating proxy; see "Remote access" below. To
redeploy new code: `git pull`, `.venv/bin/pip install -r requirements.txt`
(only if it changed), rebuild `web/dist` if `web/` changed, then
`sudo systemctl restart radar.service`.

**Graceful shutdown:** a client's open `/api/stream` (SSE) connection never
closes on its own, so a bare SIGTERM would otherwise wait on it forever.
`serve`'s `--graceful-timeout` (default 10s) bounds that; `TimeoutStopSec=20`
in the unit gives systemd enough margin above it before escalating to
SIGKILL. A crashed scheduler task takes the whole process down with it
(`radar/api/app.py`'s `_log_crash`) specifically so `Restart=always` notices
and restarts it -- uvicorn would otherwise just log the exception and keep
serving a process that stopped polling.

## 6. Backups

`radar-backup.timer` runs `python -m radar backup` nightly (03:30 + up to 10
minutes' random delay) via `radar-backup.service`, keeping the 14 most recent
copies in `data/backups/`. It uses sqlite3's backup API, which is safe to run
against the live, concurrently-written WAL database (`radar/backup.py`) --
unlike copying `radar.db` as a plain file, which can miss rows still only in
`radar.db-wal`.

**Restore:**
```
sudo systemctl stop radar.service
sudo -u radar cp /opt/radar/data/backups/radar-<timestamp>.db /opt/radar/data/radar.db
# remove any leftover WAL/shm from the db file being replaced, or SQLite
# replays their stale frames onto the restored copy on next open:
sudo -u radar rm -f /opt/radar/data/radar.db-wal /opt/radar/data/radar.db-shm
sudo systemctl start radar.service
```
Each backup file is already a complete, standalone database (the backup API
produces one, with nothing left in a separate WAL) -- it never has `-wal`/
`-shm` siblings of its own; the ones you're deleting belong to the live file
you're replacing.

## 7. Heartbeat (dead-man switch)

Make a check at [healthchecks.io](https://healthchecks.io) (or any URL that
alerts you when it stops being hit), set `HEARTBEAT_URL` to its ping URL, and
pick that check's "expected every" period to comfortably exceed 60 seconds --
the scheduler pings it at most once a minute (`HEARTBEAT_INTERVAL_S` in
`radar/scheduler.py`), not every loop tick, so an alert threshold under a
minute will false-positive. A box that's wedged or offline simply stops
pinging and the check fires on its own schedule.

## 8. Remote access for a friend (HTTPS + their own token)

Each person gets their own entry in `API_TOKENS` and `users.yaml` ("fully
separate profiles" -- T8a); nothing else here is multi-tenant-specific.
What's missing for *remote* access is TLS, since bearer tokens over plain
HTTP are readable by anything between their phone and your box:

1. Point a domain's DNS A record at the box.
2. Install [Caddy](https://caddyserver.com) and use `Caddyfile` in this
   directory (automatic Let's Encrypt, no manual cert handling):
   `sudo apt install caddy`, then follow the comments in `Caddyfile`.
3. Give the friend `https://<your domain>` plus only *their own* API token --
   never the ntfy topic or any other secret from `radar.env`.
4. Verify SSE actually survives the proxy (some default proxy configs buffer
   or time out long-lived responses): `curl -N -H "Authorization: Bearer
   <token>" https://<your domain>/api/stream` should hang open printing
   `retry: 5000` immediately, not buffer or drop after a few seconds.

## 9. The hourly GitHub Actions job (retired)

The original hourly job (`hourly.yml`, which fed an Excel tracker and a Google Sheet) was retired on
2026-10-02, when `radar.service` had taken over: the workflow and its generated files were removed from
the repository (tag `legacy-hourly-monitor` is the last commit that had them). Nothing else pushes alerts
any more, so enabling a user's `NTFY_TOPIC` on the server cannot double up. The tracker's rows were
imported once with `python -m radar.store.migrate_legacy --tracker <xlsx> --user <id>` (it skips links
another opportunity already holds and marks imported rows as already open). The repository still holds
three secrets only the old job used (`APIFY_TOKEN`, `GOOGLE_SERVICE_ACCOUNT_JSON`, `GOOGLE_SHEET_ID`) and
the variable `GOOGLE_SYNC_REQUIRED`; delete them in the repository's Actions settings.

## What the first live deploy did (Oracle Cloud Always Free, 2026-10-02)

Where reality differed from the steps above, on a `VM.Standard.E2.1.Micro`
(1 GB RAM) running Ubuntu 24.04:

- **Drive it from the OCI CLI** (`brew install oci-cli`, API key under
  "My profile → Tokens and keys"), not the console. The console wizard silently
  dropped the public IP and defaulted to the wrong image. Launch with
  `oci compute instance launch ... --assign-public-ip true
  --ssh-authorized-keys-file ~/.ssh/<key>.pub`. Keep the SSH key and the OCI
  API key separate.
- **Two firewalls.** Opening 80/443 needs an ingress rule in the VCN's
  default security list *and* in the image's own iptables, which ends in a
  catch-all `REJECT`: `iptables -I INPUT 5 -p tcp --dport 80 -m state --state
  NEW -j ACCEPT`, the same for 443, then `netfilter-persistent save`.
- **Add a 2 GB swapfile** before `pip install`. At runtime the app uses about
  190 MB, so 1 GB is otherwise fine.
- **The repo is private**, so step 1's `git clone` would need GitHub
  credentials on the box. Instead, rsync the checkout from a dev machine and
  build `web/dist` there (no Node on the server):
  `rsync -az --delete --rsync-path="sudo -u radar rsync" --exclude .venv
  --exclude .git --exclude /data --exclude web/node_modules ./
  <host>:/opt/radar/zero2sudo-opportunity-monitor/`, then
  `sudo systemctl restart radar`. If `deploy/radar.service` changed, copy it
  to `/etc/systemd/system/` and `sudo systemctl daemon-reload` first.
- **`/opt/radar` is the `radar` user's home folder (mode 750)**, so `cd`
  into it as `ubuntu` fails. Run setup as `sudo -u radar bash -c "..."`.
- **HTTPS without a domain:** `<ip-with-dashes>.nip.io` in the `Caddyfile`
  worked. Ubuntu's own `caddy` package (2.6) got a Let's Encrypt cert on the
  first try.
- **Getting `GH_TOKEN` onto the box without it appearing in a terminal or
  log:** use a classic token with no scopes, then
  `pbpaste | ssh <host> "sudo -u radar bash -c '...T=\$(cat)...'"`. Read it
  from stdin and rewrite `radar.env` with `umask 077`.

## Residential Instagram relay (T12)

When the VM's Instagram requests are blocked but the owner's Mac can fetch
Stories, set `IG_RELAY_ENABLED=1` in the server's `radar.env` and restart.
The account remains in the same watchlist; the VM scheduler skips its native
requests. Run `.venv/bin/python deploy/instagram-relay.py` on the Mac, using
the existing `drop-radar` SSH alias. This reads only the session/config it needs
over SSH, polls locally, and posts normalized Stories through SSH to the running
server's owner-authenticated `/api/instagram/relay` endpoint. Friend tokens cannot
ingest. No new network port or API token in a URL is needed.

Install it as a LaunchAgent with `RunAtLoad`, `StartInterval=300`, the absolute
Python/script paths, and logs under `~/Library/Logs/DropRadar/`. Launchd does not
overlap a still-running instance. The Mac must be awake and online; Sources marks
the poll overdue after two intervals plus a minute without a successful relay.
First successful relay backfills existing Stories silently; subsequent new Stories
use the existing pipeline and alert history. The VM OCRs each new Story (4-7s with
the unit's `OMP_THREAD_LIMIT=1`, ~25s without), so a first backfill of ~40 takes
minutes; the relay waits up to 40 min, and SSH keepalives fail a request the Mac
slept through in ~90s. An already-stored Story is skipped before OCR, even after a restart. The feed reconciles every 30s because
seeds emit no SSE event. Removing the LaunchAgent and `IG_RELAY_ENABLED` restores
VM polling. Keep this at the watchlist's 300s interval until real rate-limit data
supports a shorter interval.

T12 exposes each user's own ntfy subscription in Settings; subscribe in the ntfy
phone app and permit notifications. `alerts_enabled` means a channel is configured,
not that a phone has received anything. At this deploy the friend's separate topic
can be enabled independently. The owner's topic is staged in `/opt/radar/alert-cutover.env`, mode 600;
load it into `radar.env` to turn the owner's pushes on (the old hourly job is retired, so nothing doubles up).
Never print either topic or token to logs.

## Daily board maintenance (T16.4, on the Mac)

`deploy/board-maintenance.py` exports the current configured and self-service watchlists
over the existing SSH alias, without reading secrets or changing the live DB. It runs
`radar.sources.repair_boards` locally. A lock prevents overlapping runs. Local state,
observation logs and the review queue live under `data/t16/`.

The Mac LaunchAgent `com.dropradar.board-maintenance` runs at 03:30 local time each day.
Its ProgramArguments use this checkout's absolute `.venv/bin/python` and
`deploy/board-maintenance.py` paths, with WorkingDirectory set to the checkout;
stdout/stderr go to `~/Library/Logs/DropRadar/board-maintenance.log`. The Mac must be
awake/online to fetch boards. A gap over two days resets empty-board observation history.
To run manually: `.venv/bin/python deploy/board-maintenance.py`.

Confirmed 404s trigger bounded slug variants across Greenhouse, Lever, Ashby and
SmartRecruiters. Open candidates are queued with `company_verified=false`; the owner
must check identity before replacing a board. Workday tenant/site names aren't guessed.
Thirty days of successful empty observations queue an archive proposal and log the
evidence. Transient failures, malformed responses and nonempty boards reset that history.
**Review only:** these jobs never apply repairs or remove a live source automatically.
Before applying a queued change, re-probe it and review its timestamp; data repairs still
require an exact description, the owner's approval and a backup.

## Deferred

Docker/compose, Fly.io, S3 uploads, Postgres/Redis, sharding, and anything
multi-box: add when one box or one user is no longer enough
(`docs/specs/archive/T10-deploy-scale.md`).
