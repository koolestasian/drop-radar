import importlib.util
import json
import subprocess
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from radar.alerts import AlertDispatcher, MultiUserAlertDispatcher
from radar.api.app import create_app
from radar.config import InstagramAccount, Profile, Settings, User, Watchlist
from radar.models import utcnow
from radar.pipeline import Pipeline
from radar.pipeline.enrich import Enricher
from radar.scheduler import Scheduler
from radar.sources.instagram import InstagramSource
from radar.store import Store


class RelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(self.store.close)
        self.source = InstagramSource(InstagramAccount("zero2sudo"), Settings())
        self.source.external = True
        sent = self.sent = []

        class Channel:
            name = "ntfy"

            def send(self, opp, *_):
                sent.append(opp["id"])

        owned = {"owner": {self.source.name}, "friend": set()}
        alerter = MultiUserAlertDispatcher({"owner": AlertDispatcher(self.store, channels=[Channel()])}, owned)
        pipeline = Pipeline(self.store, enricher=Enricher(self.store, daily_token_budget=0), alerter=alerter)
        self.announced = []
        pipeline.on_new = self.announced.append
        self.scheduler = Scheduler([self.source], self.store, sink=pipeline)
        users = {uid: User(id=uid, profile=Profile(), watchlist=Watchlist()) for uid in owned}
        runtime = SimpleNamespace(users=users, owned=owned, scheduler=self.scheduler, pipeline=pipeline)
        app = create_app(self.store, runtime, tokens={"o" * 24: "owner", "f" * 24: "friend"})
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def post(self, stories, token="o" * 24, username="zero2sudo"):
        return await self.client.post("/api/instagram/relay", json={"username": username, "stories": stories},
                                      headers={"Authorization": f"Bearer {token}"})

    async def test_owner_only_configured_accounts_and_stable_ids(self):
        self.assertEqual((await self.post([], token="bad")).status_code, 401)
        self.assertEqual((await self.post([], token="f" * 24)).status_code, 403)
        self.assertEqual((await self.post([], username="someone_else")).status_code, 409)
        self.assertEqual((await self.post([{}])).status_code, 422)
        self.source.external = False
        self.assertEqual((await self.post([])).status_code, 409)
        self.assertEqual(self.store.list_opportunities(), [])

    async def test_first_poll_is_silent_repeats_do_not_push_then_a_fresh_story_alerts_once(self):
        old = {"pk": "1", "text": "SWE Intern", "links": ["https://example.com/old"]}
        new = {"pk": "2", "text": "SWE Intern", "links": ["https://example.com/new"]}
        self.assertTrue((await self.post([old])).json()["backfill"])
        self.assertEqual((self.sent, self.announced), ([], []))
        self.assertEqual((await self.post([old, new])).json()["new"], 1)
        await self.post([old, new])
        self.assertEqual((len(self.sent), len(self.announced)), (1, 1))
        self.assertEqual(len(self.store.list_opportunities()), 2)
        state = self.store.get_source_state(self.source.name)
        self.assertIsNotNone(state["last_ok"])
        self.assertEqual(state["fail_count"], 0)

    async def test_vm_never_polls_external_instagram_and_a_sleeping_mac_is_visible(self):
        self.scheduler.launch_due()
        self.assertEqual(self.scheduler.running, {})
        self.assertGreaterEqual(self.scheduler._idle_s(), 1)
        self.store.save_source_state(self.source.name, last_ok=utcnow() - timedelta(hours=1))
        self.assertTrue(self.scheduler.health()[0]["stale"])
        await self.post([])
        self.assertFalse(self.scheduler.health()[0]["stale"])


class RelayTransportTests(unittest.TestCase):
    def test_a_server_restart_retries_the_same_batch_without_repolling_instagram(self):
        path = Path(__file__).resolve().parents[1] / "deploy/instagram-relay.py"
        spec = importlib.util.spec_from_file_location("relay_client", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        info = json.dumps({"session": "test", "accounts": [{"username": "zero2sudo", "user_id": "123"}]})
        with patch.object(module, "remote", side_effect=[info, subprocess.CalledProcessError(1, "ssh"), '{"new": 0}']) as send:
            with patch.object(module, "InstagramClient") as client, patch.object(module.time, "sleep"):
                client.return_value.stories.return_value = [{"pk": "1"}]
                module.main()
        client.return_value.stories.assert_called_once_with("zero2sudo", "123")
        self.assertEqual(send.call_args_list[1].args, send.call_args_list[2].args)
