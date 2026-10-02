"""T10 accept: `python -m radar serve` shuts down cleanly on SIGTERM -- including
while a client holds /api/stream (SSE) open, which uvicorn's default graceful
shutdown waits on indefinitely unless timeout_graceful_shutdown is set."""
import os
import signal
import socket
import sys
import tempfile
import time
import unittest
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
TOKEN = "serve-shutdown-test-token-01"


def free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def write_config(config_dir: Path):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "users.yaml").write_text("users:\n  - id: kevin\n    watchlist: watchlist.yaml\n    profile: profile.yaml\n")
    (config_dir / "watchlist.yaml").write_text("companies: []\n")
    (config_dir / "profile.yaml").write_text("roles: []\n")


class ServeShutdownTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        write_config(self.tmp / "config")
        self.port = free_port()
        env = dict(os.environ)
        env.update({
            "RADAR_CONFIG_DIR": str(self.tmp / "config"),
            "RADAR_DB_PATH": str(self.tmp / "radar.db"),
            "API_TOKENS": f"kevin:{TOKEN}",
        })
        for leaky in ("NTFY_TOPIC", "IG_SESSIONID", "APIFY_TOKEN", "ANTHROPIC_API_KEY", "GH_TOKEN"):
            env.pop(leaky, None)
        import subprocess

        self.graceful_timeout = 1.0
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "radar", "serve", "--host", "127.0.0.1", "--port", str(self.port),
             "--graceful-timeout", str(self.graceful_timeout)],
            cwd=REPO_ROOT, env=env,
        )
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        if self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait(timeout=5)

    def _wait_for_healthz(self, timeout=10):
        deadline = time.monotonic() + timeout
        url = f"http://127.0.0.1:{self.port}/healthz"
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                self.fail(f"server exited early with code {self.proc.returncode}")
            try:
                if httpx.get(url, timeout=1).status_code == 200:
                    return
            except httpx.TransportError:
                pass
            time.sleep(0.1)
        self.fail("server never became healthy")

    def test_sigterm_with_an_open_sse_stream_still_exits_cleanly(self):
        self._wait_for_healthz()
        headers = {"Authorization": f"Bearer {TOKEN}"}
        base = f"http://127.0.0.1:{self.port}"

        # Proves RADAR_CONFIG_DIR/RADAR_DB_PATH actually isolated this process from the
        # repo's own config/ (kevin's real ~86 sources) and data/radar.db: without that,
        # this would still pass with the token valid but against live boards and the
        # real database.
        me = httpx.get(f"{base}/api/me", headers=headers, timeout=5)
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json(), {"user": "kevin", "sources": 0})
        self.assertTrue((self.tmp / "radar.db").exists())

        url = f"{base}/api/stream"
        with httpx.stream("GET", url, headers=headers, timeout=10) as response:
            self.assertEqual(response.status_code, 200)
            first = next(response.iter_lines())
            self.assertEqual(first, "retry: 5000")  # connection is open and streaming

            self.proc.send_signal(signal.SIGTERM)
            start = time.monotonic()
            self.proc.wait(timeout=15)
            elapsed = time.monotonic() - start

        # uvicorn finishes its graceful shutdown, then re-delivers SIGTERM to itself with
        # the default disposition restored, so the exit status correctly reports "killed
        # by SIGTERM" to a process supervisor (systemd) rather than looking like a bare exit.
        self.assertEqual(self.proc.returncode, -signal.SIGTERM)
        # The open SSE stream never closes on its own, so without --graceful-timeout
        # uvicorn would wait on it forever; with it, shutdown is bounded by that timeout.
        self.assertLess(elapsed, self.graceful_timeout + 3)


if __name__ == "__main__":
    unittest.main()
