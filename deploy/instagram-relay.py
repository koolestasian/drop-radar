"""Poll Stories from the owner's Mac; authenticated SSH transports them to the VM.

Run with this repo's .venv/bin/python. Secrets are read over SSH into memory,
never written to a local file or included in command arguments/logs.
"""
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from radar.legacy.instagram_scraper import InstagramClient  # noqa: E402

REMOTE_REPO = "/opt/radar/zero2sudo-opportunity-monitor"
REMOTE_ENV = "/opt/radar/radar.env"


def remote(code, payload=None):
    command = (f"set -a; source {shlex.quote(REMOTE_ENV)}; cd {shlex.quote(REMOTE_REPO)}; "
               f".venv/bin/python -c {shlex.quote(code)}")
    return subprocess.check_output(
        ["/usr/bin/ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "drop-radar",
         "sudo -u radar bash -c " + shlex.quote(command)], input=payload, text=True, timeout=300)


def main():
    info = json.loads(remote("""
import json
from dataclasses import asdict
from radar.config import load_settings, load_users
accounts = {a.username: a for u in load_users() for a in u.watchlist.instagram}
print(json.dumps({'session': load_settings().ig_sessionid, 'accounts': [asdict(a) for a in accounts.values()]}))
"""))
    client = InstagramClient(info["session"])
    for account in info["accounts"]:
        stories = client.stories(account["username"], account["user_id"] or None)
        code = """
import json, sys, urllib.request
from radar.config import load_settings, load_users
owner = load_users()[0].id
token = next(secret for secret, uid in load_settings().api_tokens.items() if uid == owner)
req = urllib.request.Request('http://127.0.0.1:8000/api/instagram/relay', data=sys.stdin.buffer.read(),
    headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
with urllib.request.urlopen(req, timeout=240) as response:
    print(response.read().decode())
"""
        payload = json.dumps({"username": account["username"], "stories": stories})
        for attempt in range(3):
            try:
                result = remote(code, payload)
                break
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                if attempt == 2:
                    raise
                time.sleep(5 * (attempt + 1))  # retry the same batch, never re-poll Instagram
        print(f"instagram.{account['username']}: {result.strip()}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        detail = f"SSH request exited {exc.returncode}" if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        print(f"Instagram relay failed: {type(exc).__name__}: {detail}", file=sys.stderr)
        sys.exit(1)
