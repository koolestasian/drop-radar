"""Daily Mac job: export live board config read-only, queue repairs locally."""
import fcntl
import json
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPORT = """
import dataclasses, json
from radar.config import load_users, account_user
from radar.store import Store
with Store('/opt/radar/data/radar.db') as store:
    users = (*load_users(), *(account_user(row) for row in store.list_accounts()))
    companies = {(c.ats, c.slug.lower()): dataclasses.asdict(c) for u in users for c in u.watchlist.companies}
    print(json.dumps(list(companies.values())))
"""


def main():
    directory = ROOT / "data/t16"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "16.4-maintenance.lock").open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        command = ("cd /opt/radar/zero2sudo-opportunity-monitor && "
                   "RADAR_CONFIG_DIR=/opt/radar/config .venv/bin/python -c " + shlex.quote(EXPORT))
        result = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "drop-radar",
                                 "sudo -u radar bash -c " + shlex.quote(command)], check=True,
                                capture_output=True, text=True, timeout=60)
        records = json.loads(result.stdout)  # a failed/invalid export leaves previous observations alone
        snapshot = directory / "16.4-live-companies.json"
        snapshot.write_text(json.dumps(records))
        subprocess.run([sys.executable, "-m", "radar.sources.repair_boards", "--companies", str(snapshot)], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
