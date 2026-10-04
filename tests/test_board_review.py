import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock

import httpx

from radar.api.app import create_app
from radar.config import Company, User, Watchlist, Profile
from radar.pipeline import pagefacts
from radar.sources import board_review as br, repair_boards as rb
from radar.store import Store


def response(data=None, status=200):
    return SimpleNamespace(status_code=status, json=lambda: data)


class BoardTests(unittest.TestCase):
    def test_detection_of_direct_and_company_careers_urls(self):
        with patch.object(br, "page_links", side_effect=[["https://acme.example/careers"], ["https://jobs.ashbyhq.com/acme"]]), \
                patch.object(br, "probe", return_value={"status": "ok", "postings": 7}):
            self.assertEqual(br.discover_url("https://acme.example")["slug"], "acme")
        with patch.object(br, "page_links") as pages, patch.object(br, "probe", return_value={"status": "ok", "postings": 7}):
            row = br.discover_url("https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite")
            self.assertEqual(row["slug"], "nvidia.wd5/NVIDIAExternalCareerSite")
            pages.assert_not_called()

    def test_validation_and_ambiguous_boards_are_rejected(self):
        for url in ("file:///etc/passwd", "https://user:pass@jobs.lever.co/acme"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                br.discover_url(url)
        for url in ("https://evilgreenhouse.io/acme/jobs/1", "https://jobs.lever.co/a%2F.."):
            self.assertIsNone(br.pair_from_url(url))
        with patch.object(br, "page_links", return_value=["https://jobs.lever.co/acme", "https://jobs.ashbyhq.com/acme"]), \
                patch.object(br, "probe", return_value={"status": "ok", "postings": 1}), self.assertRaises(ValueError):
            br.discover_url("https://acme.example/careers")

    def test_probe_distinguishes_404_empty_schema_and_transient_errors(self):
        company = Company("Acme", "ashby", "acme")
        for reply, status in ((None, "error"), (response(status=404), "not_found"),
                              (response(status=500), "error"), (response({"jobs": []}), "empty"),
                              (response({"wrong": []}), "error")):
            with self.subTest(status=status), patch.object(pagefacts, "_get", return_value=reply):
                self.assertEqual(br.probe(company)["status"], status)
        with patch.object(pagefacts, "_get") as get:
            self.assertEqual(br.probe(Company("Bad", "lever", "../private"))["status"], "error")
            get.assert_not_called()

    def test_workday_uses_guarded_post_and_redirects_are_not_followed(self):
        with patch.object(pagefacts, "_get", return_value=response({"total": 3, "jobPostings": [{}]})) as get:
            self.assertEqual(br.probe(Company("Acme", "workday", "acme.wd5/jobs"))["postings"], 3)
            self.assertEqual(get.call_args.kwargs["method"], "POST")
        redirect = Mock(status_code=302, is_redirect=True, headers={"location": "http://127.0.0.1"})
        with patch.object(pagefacts, "_public", return_value=True), patch.object(pagefacts.requests, "post", return_value=redirect) as post:
            self.assertIsNone(pagefacts._get("https://acme.wd5.myworkdayjobs.com/jobs", method="POST", json_body={}))
            post.assert_called_once()


class MaintenanceTests(unittest.TestCase):
    def test_only_confirmed_404s_trigger_bounded_repair_guesses(self):
        company = Company("Acme Inc", "greenhouse", "dead")
        with patch.object(rb, "probe", side_effect=lambda c: {"status": "not_found" if c.slug == "dead" else "ok", "postings": 2}):
            _, queue = rb.inspect(company, {}, datetime.now(timezone.utc))
        self.assertTrue(queue)
        self.assertTrue(all(r["action"] == "repair" and not r["company_verified"] for r in queue))
        self.assertLessEqual(len(queue), 12)
        for status in ("empty", "error", "ok"):
            with patch.object(rb, "probe", return_value={"status": status, "postings": 0}) as probe:
                rb.inspect(company, {}, datetime.now(timezone.utc))
                probe.assert_called_once()

    def test_archive_requires_30_days_of_empty_observations_and_resets_after_errors_or_gaps(self):
        now = datetime(2026, 10, 3, tzinfo=timezone.utc)
        prior = {"status": "empty", "checked_at": (now-timedelta(days=1)).isoformat(), "empty_since": (now-timedelta(days=30)).isoformat()}
        company = Company("Acme", "ashby", "acme")
        with patch.object(rb, "probe", return_value={"status": "empty", "postings": 0}):
            _, queue = rb.inspect(company, prior, now)
            self.assertEqual(queue[0]["action"], "archive")
            self.assertEqual(queue[0]["status"], "pending_review")
            for changed in ({"status": "error"}, {"checked_at": (now-timedelta(days=3)).isoformat()}):
                state, queue = rb.inspect(company, {**prior, **changed}, now)
                self.assertEqual(queue, [])
                self.assertEqual(state["empty_since"], now.isoformat())
        with patch.object(rb, "probe", return_value={"status": "error", "postings": 0}):
            state, queue = rb.inspect(company, prior, now)
            self.assertNotIn("empty_since", state)
            self.assertEqual(queue, [])

    def test_cli_logs_observations_and_deduplicates_proposals_without_changing_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            companies = root / "companies.json"
            original = json.dumps([{"name": "Acme", "ats": "ashby", "slug": "acme"}])
            companies.write_text(original)
            proposal = {"company": {"ats": "ashby", "slug": "acme"}, "action": "archive"}
            args = ["--companies", str(companies), "--state", str(root/"state.json"), "--out", str(root/"queue.jsonl"), "--log", str(root/"log.jsonl")]
            with patch.object(rb, "inspect", return_value=({"status": "empty"}, [proposal])):
                rb.main(args)
                rb.main(args)
            self.assertEqual(len((root/"queue.jsonl").read_text().splitlines()), 1)
            self.assertEqual(len((root/"log.jsonl").read_text().splitlines()), 2)
            self.assertEqual(companies.read_text(), original)


class DiscoveryApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_requires_auth_and_does_not_save_anything(self):
        with tempfile.TemporaryDirectory() as directory, Store(Path(directory)/"radar.db") as store:
            user = User(id="owner", watchlist=Watchlist(), profile=Profile())
            runtime = SimpleNamespace(users={"owner": user}, owned={"owner": set()}, scheduler=None)
            app = create_app(store, runtime, tokens={"k"*24: "owner"})
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
                before = "".join(store.conn.iterdump())
                with patch.object(br, "discover_url", return_value={"name": "", "ats": "ashby", "slug": "acme", "tier": "C", "postings": 2}) as discover:
                    rejected = await client.post("/api/config/watchlist/discover", json={"url": "https://jobs.ashbyhq.com/acme"})
                    self.assertEqual(rejected.status_code, 401)
                    discover.assert_not_called()
                    good = await client.post("/api/config/watchlist/discover", json={"url": "https://jobs.ashbyhq.com/acme"}, headers={"Authorization": "Bearer " + "k"*24})
                    self.assertEqual(good.status_code, 200, good.text)
                self.assertEqual("".join(store.conn.iterdump()), before)
                self.assertEqual(runtime.users["owner"].watchlist.companies, ())
