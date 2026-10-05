"""T16.6 feedback and dry-run diagnostics; all network is mocked."""
import dataclasses
import asyncio
import json
import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import yaml

from radar.api.app import create_app
from radar.config import Profile, User, Watchlist, parse_profile
from radar.models import Item, utcnow
from radar.store import Store


class FeedbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(self.store.close)
        for target in ("radar.pipeline.pagefacts._public", "radar.api.diagnostics._public"):
            guard = patch(target, side_effect=lambda host: host != "127.0.0.1")
            guard.start()
            self.addCleanup(guard.stop)
        self.source = "ats.greenhouse.demo"
        self.user = User(id="owner", profile=Profile(), watchlist=Watchlist())
        self.runtime = SimpleNamespace(users={"owner": self.user}, owned={"owner": {self.source}}, scheduler=None)
        self.app = create_app(self.store, self.runtime, tokens={"k" * 24: "owner"})
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test",
                                      headers={"Authorization": "Bearer " + "k" * 24})
        self.ids = [self.add(str(i), f"Sales Engineer Intern {i}") for i in range(5)]

    async def asyncTearDown(self):
        await self.client.aclose()

    def add(self, key, title, source=None, raw=None):
        return self.store.upsert_item(Item(source=source or self.source, external_id=key,
                                          title=title, url=f"https://example.com/jobs/{key}", raw=raw or {}))[0]

    async def hide(self, id, term="sales"):
        r = await self.client.patch(f"/api/opportunities/{id}", json={"status": "ignored", "hide_term": term})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    async def suggestions(self):
        r = await self.client.get("/api/profile/suggestions")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    async def test_threshold_distinct_jobs_preview_and_unhide(self):
        await self.hide(self.ids[0], "  SaLeS  ")
        await self.hide(self.ids[0])
        await self.hide(self.ids[1])
        self.assertEqual((await self.suggestions())["suggestions"], [])
        await self.hide(self.ids[2])
        result = (await self.suggestions())["suggestions"][0]
        self.assertEqual((result["term"], result["support_count"], result["affected_count"]), ("sales", 3, 2))
        self.assertEqual(len(result["examples"]), 2)
        await self.client.patch(f"/api/opportunities/{self.ids[2]}", json={"notes": "keep me"})
        self.assertEqual((await self.suggestions())["suggestions"][0]["support_count"], 3)
        r = await self.client.patch(f"/api/opportunities/{self.ids[2]}", json={"status": "saved"})
        self.assertIsNone(r.json()["action"]["hide_term"])
        self.assertEqual(r.json()["action"]["notes"], "keep me")
        self.assertEqual((await self.suggestions())["suggestions"], [])

    async def test_recent_explicit_feedback_only_and_user_isolation(self):
        for id in self.ids[:3]:
            await self.hide(id)
        with self.store.conn:
            self.store.conn.execute("UPDATE actions SET hide_term_at=? WHERE opportunity_id=?",
                                    ((utcnow() - timedelta(days=31)).isoformat(), self.ids[0]))
        self.assertEqual((await self.suggestions())["suggestions"], [])
        self.store.set_action(self.ids[3], "other", status="ignored", hide_term="sales")
        self.store.set_action(self.ids[4], "owner", status="ignored")
        self.assertEqual((await self.suggestions())["suggestions"], [])

    async def test_preview_matches_displayed_duplicate_requisitions(self):
        for id in self.ids[:3]:
            await self.hide(id)
        duplicate = self.add("duplicate", "Sales Engineer Intern 4")
        self.assertEqual((await self.suggestions())["suggestions"][0]["affected_count"], 2)
        response = await self.client.get("/api/opportunities", params={"sort": "found"})
        self.assertEqual(len(response.json()["items"]), 2)
        await self.hide(duplicate)
        # A hidden newest twin also suppresses the older copy in Jobs.
        result = (await self.suggestions())["suggestions"][0]
        response = await self.client.get("/api/opportunities", params={"sort": "found"})
        self.assertEqual(result["affected_count"], len(response.json()["items"]))
        self.assertEqual(result["affected_count"], 1)

    async def test_invalid_feedback_does_not_change_actions(self):
        for body in ({"status": "ignored", "hide_term": "marketing"}, {"hide_term": "sales"},
                     {"status": "ignored", "hide_term": " "}, {"status": "saved", "hide_term": "sales"}):
            r = await self.client.patch(f"/api/opportunities/{self.ids[0]}", json=body)
            self.assertEqual(r.status_code, 422, r.text)
        self.assertIsNone(self.store.get_opportunity(self.ids[0], user_id="owner")["action"])

    async def test_mute_restore_and_curated_bypass(self):
        story = "instagram.zero2sudo"
        self.runtime.owned["owner"].add(story)
        self.add("story", "Sales Engineer Intern", story)
        for id in self.ids[:3]:
            await self.hide(id)
        self.assertEqual((await self.suggestions())["suggestions"][0]["affected_count"], 2)
        for decision in ("mute", "restore"):
            r = await self.client.post("/api/profile/suggestions", json={"term": "sales", "decision": decision})
            self.assertEqual(r.status_code, 200, r.text)
            data = await self.suggestions()
            self.assertEqual(len(data["suggestions"]), 0 if decision == "mute" else 1)
            self.assertEqual(data["muted"], ["sales"] if decision == "mute" else [])

    async def test_apply_merges_latest_profile(self):
        for id in self.ids[:3]:
            await self.hide(id)
        path = Path(tempfile.mkdtemp()) / "profile.yaml"
        path.write_text("exclude: [senior]\nlocations: [US]\n")
        self.runtime.users["owner"] = dataclasses.replace(self.user, profile=Profile(exclude=("senior",), locations=("US",)), profile_path=path)
        def reload():
            current = self.runtime.users["owner"]
            self.runtime.users["owner"] = dataclasses.replace(current, profile=parse_profile(yaml.safe_load(path.read_text()), "test"))
        self.runtime.reload = reload
        r = await self.client.post("/api/profile/suggestions", json={"term": "sales", "decision": "apply"})
        self.assertEqual(r.status_code, 200, r.text)
        data = yaml.safe_load(path.read_text())
        self.assertEqual(data["exclude"], ["senior", "sales"])
        self.assertEqual(data["locations"], ["US"])
        self.assertEqual(r.json()["suggestions"], [])

    async def test_known_diagnostic_is_read_only_and_honest(self):
        await self.hide(self.ids[0])
        before = list(self.store.conn.iterdump())
        r = await self.client.post("/api/diagnostics/link", json={"url": "https://example.com/jobs/0?utm_source=x"})
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertTrue(data["collected"])
        self.assertEqual(next(c for c in data["checks"] if c["stage"] == "visibility")["verdict"], "blocked")
        self.assertEqual(list(self.store.conn.iterdump()), before)

    async def test_unknown_preview_no_writes_and_profile_gate(self):
        self.runtime.users["owner"] = dataclasses.replace(self.user, profile=Profile(exclude=("sales",)))
        facts = {"title": "Sales Engineer Intern", "source": self.source, "location": "US"}
        before = list(self.store.conn.iterdump())
        with patch("radar.api.diagnostics.fetch_preview", return_value=facts):
            r = await self.client.post("/api/diagnostics/link", json={"url": "https://boards.greenhouse.io/demo/jobs/123"})
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertFalse(data["collected"])
        self.assertEqual(next(c for c in data["checks"] if c["stage"] == "profile")["verdict"], "blocked")
        self.assertIn("current", data["summary"].lower())
        self.assertEqual(list(self.store.conn.iterdump()), before)

    async def test_unowned_job_does_not_leak_and_unavailable_is_inconclusive(self):
        self.add("private", "Secret Intern", "ats.greenhouse.private")
        with patch("radar.api.diagnostics.fetch_preview", return_value=None):
            r = await self.client.post("/api/diagnostics/link", json={"url": "https://example.com/jobs/private"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn("Secret", json.dumps(r.json()))
        self.assertFalse(r.json()["collected"])
        self.assertEqual(next(c for c in r.json()["checks"] if c["stage"] == "profile")["verdict"], "unknown")

    async def test_auth_rate_limit_and_url_validation(self):
        self.assertEqual((await self.client.post("/api/diagnostics/link", headers={"Authorization": ""},
                                               json={"url": "https://example.com"})).status_code, 401)
        for url in ("file:///etc/passwd", "http://user:pass@example.com", "http://127.0.0.1/job"):
            r = await self.client.post("/api/diagnostics/link", json={"url": url})
            self.assertEqual(r.status_code, 422, r.text)
        with patch("radar.api.diagnostics.fetch_preview", return_value=None):
            for _ in range(7):  # invalid requests consume the same rate limit, before DNS work
                self.assertEqual((await self.client.post("/api/diagnostics/link", json={"url": "https://example.com/job"})).status_code, 200)
            self.assertEqual((await self.client.post("/api/diagnostics/link", json={"url": "https://example.com/job"})).status_code, 429)

    async def test_thirty_day_boundary_and_dead_jobs_are_not_previewed(self):
        from radar.api.feedback import suggestions
        frozen = utcnow()
        for id in self.ids[:3]:
            await self.hide(id)
        with self.store.conn:
            self.store.conn.execute("UPDATE actions SET hide_term_at=? WHERE user_id='owner'",
                                    ((frozen - timedelta(days=30)).isoformat(),))
        self.store.save_opportunity(self.ids[3], first_seen=frozen, status="Closed")
        self.store.set_action(self.ids[4], "owner", status="ignored")
        result = suggestions(self.store, self.user, self.runtime.owned["owner"], frozen)
        self.assertEqual(result.suggestions[0].support_count, 3)
        self.assertEqual(result.suggestions[0].affected_count, 0)
        self.assertEqual(suggestions(self.store, self.user, self.runtime.owned["owner"], frozen + timedelta(microseconds=1000)).suggestions, [])

    async def test_timeout_keeps_both_fetch_slots_until_workers_finish(self):
        release = threading.Event()
        original_wait = asyncio.wait_for
        async def short_wait(awaitable, timeout):
            return await original_wait(awaitable, 0.02 if timeout == 25 else timeout)
        def blocked(url):
            release.wait(2)
            return None
        with patch("radar.api.diagnostics.fetch_preview", side_effect=blocked), patch("radar.api.app.asyncio.wait_for", side_effect=short_wait):
            try:
                responses = await asyncio.gather(*[self.client.post("/api/diagnostics/link", json={"url": f"https://example.com/{i}"}) for i in range(2)])
                self.assertEqual([r.status_code for r in responses], [200, 200])
                self.assertEqual((await self.client.post("/api/diagnostics/link", json={"url": "https://example.com/third"})).status_code, 429)
            finally:
                release.set()
                await asyncio.sleep(0.05)

    async def test_source_specific_matching_seed_closed_and_sent_evidence(self):
        github = "github_repo.SimplifyJobs/New-Grad-Positions"
        self.runtime.owned["owner"].add(github)
        id = self.add("seed", "Software Engineer", github, {"seed": True})
        self.runtime.users["owner"] = dataclasses.replace(self.user, profile=Profile(roles=("software engineer",), keywords=("intern",)))
        before = list(self.store.conn.iterdump())
        r = await self.client.post("/api/diagnostics/link", json={"url": "https://example.com/jobs/seed"})
        self.assertEqual(next(c for c in r.json()["checks"] if c["stage"] == "profile")["verdict"], "passed")
        self.assertEqual(next(c for c in r.json()["checks"] if c["stage"] == "backfill")["verdict"], "blocked")
        self.assertEqual(list(self.store.conn.iterdump()), before)
        self.store.save_opportunity(id, first_seen=utcnow(), status="Closed")
        self.store.record_alert(id, "private-owner-channel", sent_at=utcnow())
        self.store.record_alert(id, "someone-else", sent_at=utcnow())
        self.runtime.pipeline = SimpleNamespace(alerter=SimpleNamespace(dispatchers={"owner": SimpleNamespace(channels=[SimpleNamespace(name="private-owner-channel")])}))
        r = await self.client.post("/api/diagnostics/link", json={"url": "https://example.com/jobs/seed"})
        self.assertEqual(next(c for c in r.json()["checks"] if c["stage"] == "visibility")["verdict"], "blocked")
        self.assertIn("device receipt", next(c for c in r.json()["checks"] if c["stage"] == "alerts")["explanation"])
        self.assertNotIn("someone-else", r.text)

    async def test_canonical_sighting_alias_and_curated_story(self):
        story = "instagram.zero2sudo"
        self.runtime.owned["owner"].add(story)
        id = self.add("story", "Sales", story)
        self.runtime.users["owner"] = dataclasses.replace(self.user, profile=Profile(exclude=("sales",)))
        self.store.upsert_item(Item(source=story, external_id="story-alias", url="https://example.com/alias", title="Sales"), opportunity_id=id)
        r = await self.client.post("/api/diagnostics/link", json={"url": "https://example.com/alias"})
        self.assertTrue(r.json()["collected"])
        self.assertEqual(next(c for c in r.json()["checks"] if c["stage"] == "profile")["verdict"], "passed")
