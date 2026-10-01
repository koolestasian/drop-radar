import asyncio
import tempfile
import unittest
from pathlib import Path

import httpx

from radar.api.app import create_app
from radar.store import Store


class FakeScheduler:
    def __init__(self):
        self.started, self.stopped = asyncio.Event(), False

    async def run(self, stop):
        self.started.set()
        await stop.wait()
        self.stopped = True


class FakeRuntime:
    def __init__(self):
        self.scheduler = FakeScheduler()


class AppLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(self.store.close)

    async def test_the_scheduler_runs_for_exactly_as_long_as_the_server(self):
        runtime = FakeRuntime()
        app = create_app(self.store, runtime)
        async with app.router.lifespan_context(app):
            await asyncio.wait_for(runtime.scheduler.started.wait(), 1)
            self.assertFalse(runtime.scheduler.stopped)
        self.assertTrue(runtime.scheduler.stopped, "shutdown lets the scheduler drain, not just cancels it")

    async def test_without_a_runtime_nothing_polls(self):
        app = create_app(self.store)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
                self.assertEqual((await client.get("/healthz")).json(), {"ok": True})


if __name__ == "__main__":
    unittest.main()
