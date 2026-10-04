import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from radar.alerts import AlertDispatcher
from radar.config import Profile
from radar.models import Item
from radar.pipeline import Pipeline, matches_profile
from radar.pipeline.enrich import Enricher
from radar.pipeline.normalize import canonical_company, canonical_url
from radar.store import Store

T0 = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
APPLY_URL = "https://boards.greenhouse.io/stripe/jobs/1"


def item(source, external_id, url=APPLY_URL, **kw):
    return Item(source=source, external_id=external_id, url=url, title=kw.pop("title", "SWE Intern"),
                seen_at=kw.pop("seen_at", T0), **kw)


class FakeExtractor:
    """Deterministic stand-in for radar.legacy.llm_extraction.Extractor."""

    def __init__(self, facts=None, results=None):
        self.facts = facts or {"organization": "Stripe", "title": "SWE Intern", "deadline": "2026-12-01"}
        self.results = list(results) if results is not None else None  # overrides self.facts, one per call
        self.calls = 0
        self.usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    def extract(self, text, link="", posted="", page=None):
        self.usage["calls"] += 1
        self.usage["input_tokens"] += 100
        self.usage["output_tokens"] += 50
        if self.results is not None:
            result = self.results[self.calls]
        else:
            result = dict(self.facts)
        self.calls += 1
        return result


def pipeline(store, extractor=None):
    # channels=() : the unit suite must never reach a real alert channel (no NTFY_TOPIC
    # dependence), even if the ambient env happens to have one set (T7-alerts.md review).
    return Pipeline(store, enricher=Enricher(store, extractor=extractor or FakeExtractor()),
                     alerter=AlertDispatcher(store, channels=()))


class NormalizeTests(unittest.TestCase):
    def test_canonical_url_strips_utm_and_simplify_ref(self):
        url = "https://boards.greenhouse.io/stripe/jobs/1?utm_source=x&ref=Simplify"
        self.assertEqual(canonical_url(url), "https://boards.greenhouse.io/stripe/jobs/1")

    def test_canonical_company_known_alias(self):
        self.assertEqual(canonical_company("doordashusa"), "DoorDash")

    def test_canonical_company_blank_passthrough(self):
        self.assertEqual(canonical_company(""), "")


class DedupeTests(unittest.IsolatedAsyncioTestCase):
    """Table-driven: the same apply URL via ATS, a community list and Instagram
    must converge to one opportunity (T6-pipeline.md acceptance criterion)."""

    CASES = [
        ("ats", "ats.greenhouse.stripe", "1"),
        ("list", "github_repo.SimplifyJobs/Summer2027-Internships", "row-1"),
        ("instagram", "instagram.zero2sudo", "media:1"),
    ]

    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(self.store.close)
        self.pipeline = pipeline(self.store)

    async def test_same_url_three_sources_one_opportunity(self):
        for _, source, external_id in self.CASES:
            with self.subTest(source=source):
                await self.pipeline(None, [item(source, external_id)])
        self.assertEqual(len(self.store.list_opportunities()), 1)

    async def test_each_new_source_sighting_is_announced_but_a_repeat_is_not(self):
        announced = []
        self.pipeline.on_new = announced.append
        await self.pipeline(None, [item("ats.greenhouse.a", "1")])
        await self.pipeline(None, [item("ats.greenhouse.b", "2")])
        await self.pipeline(None, [item("ats.greenhouse.b", "2")])
        [opp] = self.store.list_opportunities()
        self.assertEqual(announced, [opp["id"], opp["id"]])

    async def test_live_event_does_not_wait_for_phone_delivery(self):
        started, release = asyncio.Event(), asyncio.Event()
        announced = []

        class SlowAlerter:
            async def retry_pending(self):
                pass

            async def dispatch(self, *_):
                started.set()
                await release.wait()

        self.pipeline.alerter = SlowAlerter()
        self.pipeline.on_new = announced.append
        task = asyncio.create_task(self.pipeline(None, [item("ats.greenhouse.a", "1")]))
        try:
            await asyncio.wait_for(started.wait(), 1)
            self.assertEqual(len(announced), 1)
        finally:
            release.set()
            await task

    async def test_earliest_seen_at_wins_regardless_of_arrival_order(self):
        later = item("ats.greenhouse.stripe", "1", seen_at=T0)
        earlier = item("instagram.zero2sudo", "media:1", seen_at=T0.replace(hour=1))
        await self.pipeline(None, [later])
        await self.pipeline(None, [earlier])
        [opp] = self.store.list_opportunities()
        self.assertEqual(opp["first_seen"], earlier.seen_at.isoformat())

    async def test_blank_url_never_matches_across_items(self):
        await self.pipeline(None, [item("ats.greenhouse.a", "1", url="", company="A")])
        await self.pipeline(None, [item("ats.greenhouse.b", "1", url="", company="B")])
        self.assertEqual(len(self.store.list_opportunities()), 2)

    async def test_resighting_own_item_does_not_orphan_a_migrated_id(self):
        self.store.upsert_item(item("instagram.zero2sudo", "media:1"), opportunity_id="legacy123")
        await self.pipeline(None, [item("instagram.zero2sudo", "media:1")])
        self.assertEqual(len(self.store.list_opportunities()), 1)
        self.assertEqual(self.store.list_opportunities()[0]["id"], "legacy123")

    async def test_different_source_converges_on_a_migrated_url_through_dedupe_py(self):
        """The exact gap T1/T5 flagged: a *different* source seeing an
        *already-migrated* URL (through resolve_opportunity_id/opportunity_id_for_url,
        not the (source, external_id) reuse Store.upsert_item already does on its own)."""
        self.store.upsert_item(
            item("instagram.zero2sudo", "media:1", url=APPLY_URL), opportunity_id="legacy123",
        )
        noisy_url = APPLY_URL + "?ref=Simplify&utm_source=x"
        await self.pipeline(None, [item("ats.greenhouse.stripe", "1", url=noisy_url)])
        self.assertEqual(len(self.store.list_opportunities()), 1)
        self.assertEqual(self.store.list_opportunities()[0]["id"], "legacy123")


class ClosedDetectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(self.store.close)
        self.pipeline = pipeline(self.store)

    async def test_close_signal_marks_known_opportunity_closed(self):
        await self.pipeline(None, [item("ats.greenhouse.stripe", "1")])
        await self.pipeline(None, [item("ats.greenhouse.stripe", "1", raw={"closed": True})])
        [opp] = self.store.list_opportunities()
        self.assertEqual(opp["status"], "Closed")

    async def test_close_signal_for_unknown_item_is_ignored(self):
        await self.pipeline(None, [item("ats.greenhouse.stripe", "unknown", raw={"closed": True})])
        self.assertEqual(self.store.list_opportunities(), [])


class LlmBudgetTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(self.store.close)

    async def test_structured_sources_get_season_and_track_from_the_title_without_the_llm(self):
        """An ATS/list item has no caption, but its title carries the season the
        profile's grad year filters on ("... Internship (Summer 2026)")."""
        extractor = FakeExtractor()
        await pipeline(self.store, extractor)(
            None, [item("ats.greenhouse.stripe", "1", title="Software Engineering Internship (Summer 2027)")])
        [opp] = self.store.list_opportunities()
        fields = self.store.get_opportunity(opp["id"])["fields"]
        self.assertEqual(fields["Season / Year"], "Summer 2027")
        self.assertIn("Software Engineering", fields["Role / Track"])
        self.assertFalse(matches_profile({**opp, "fields": fields}, Profile(grad_year=2026))[0])
        self.assertEqual(extractor.calls, 0)

    async def test_llm_not_called_for_ats_items(self):
        extractor = FakeExtractor()
        await pipeline(self.store, extractor)(None, [item("ats.greenhouse.stripe", "1", text="whatever")])
        self.assertEqual(extractor.calls, 0)

    async def test_llm_not_called_for_github_repo_items(self):
        extractor = FakeExtractor()
        await pipeline(self.store, extractor)(
            None, [item("github_repo.SimplifyJobs/Summer2027-Internships", "row-1", text="whatever")]
        )
        self.assertEqual(extractor.calls, 0)

    async def test_llm_called_for_ambiguous_instagram_item_and_cached_on_resighting(self):
        extractor = FakeExtractor()
        p = pipeline(self.store, extractor)
        text = "Stripe internship applications open, apply by Dec 1 2026"
        await p(None, [item("instagram.zero2sudo", "media:1", text=text, title="")])
        self.assertEqual(extractor.calls, 1)
        [opp] = self.store.list_opportunities()
        self.assertEqual(opp["company"], "Stripe")
        self.assertEqual(opp["deadline"], "2026-12-01")

        await p(None, [item("instagram.zero2sudo", "media:2", url="https://x.example/other", text=text)])
        self.assertEqual(extractor.calls, 1, "same text -> cached, not re-billed")

    async def test_the_llm_title_replaces_only_a_composed_or_ocr_junk_story_title(self):
        extractor = FakeExtractor({"organization": "Stripe", "title": "Software Engineer Intern, Summer 2027"})
        p = pipeline(self.store, extractor)
        for n, title in enumerate(["Other Opportunity · 2026", "= 3 hackathon teams",
                                   "Categories: Summer Internship Program", "Backend Engineer Intern"]):
            await p(None, [item("instagram.zero2sudo", f"media:{n}", url=f"https://x.example/{n}",
                                text=f"post {n}", title=title)])
        titles = sorted(o["title"] for o in self.store.list_opportunities())
        self.assertEqual(titles, ["Backend Engineer Intern"] + ["Software Engineer Intern, Summer 2027"] * 3)

    async def test_a_story_the_llm_is_sure_is_not_an_opportunity_is_marked_not_actionable(self):
        for n, (verdict, confidence, status) in enumerate([(False, 0.95, "Not actionable"), (False, 0.5, "New"),
                                                           (True, 0.95, "New")]):
            extractor = FakeExtractor({"is_opportunity": verdict, "confidence": confidence, "title": ""})
            await pipeline(self.store, extractor)(None, [item(
                "instagram.zero2sudo", f"m{n}", url=f"https://www.instagram.com/stories/zero2sudo/m{n}",  # a Story with no apply link
                text=f"meme {n}", title="= 3 hackathon teams")])
            [opp] = [o for o in self.store.list_opportunities() if o["url"].endswith(f"/m{n}")]
            self.assertEqual(self.store.get_opportunity(opp["id"])["status"], status)

    async def test_a_story_with_an_application_link_is_never_hidden_as_not_an_opportunity(self):
        extractor = FakeExtractor({"is_opportunity": False, "confidence": 0.99, "title": ""})
        await pipeline(self.store, extractor)(None, [item("instagram.zero2sudo", "lk", url="https://jobs.example/apply/1",
                                                          text="Visit Link", title="Intern")])
        [opp] = self.store.list_opportunities()
        self.assertEqual(self.store.get_opportunity(opp["id"])["status"], "New")

    async def test_failed_llm_call_is_not_cached_and_retries_next_sighting(self):
        extractor = FakeExtractor(results=[None, {"organization": "Stripe", "deadline": "2026-12-01"}])
        p = pipeline(self.store, extractor)
        text = "internship applications open, apply by Dec 1 2026"  # no org a regex can find
        no_org_url = "https://forms.gle/abc123"  # a generic link host; extract_organization finds nothing
        await p(None, [item("instagram.zero2sudo", "media:1", url=no_org_url, text=text, title="")])
        self.assertEqual(extractor.calls, 1)
        self.assertEqual(self.store.list_opportunities()[0]["company"], "")

        await p(None, [item("instagram.zero2sudo", "media:2", url="https://x.example/other", text=text)])
        self.assertEqual(extractor.calls, 2, "the failed call must not have been cached as {}")

    async def test_budget_exhaustion_degrades_to_regex_without_erroring(self):
        extractor = FakeExtractor()
        enricher = Enricher(self.store, extractor=extractor, daily_token_budget=0)
        await Pipeline(self.store, enricher=enricher, alerter=AlertDispatcher(self.store, channels=()))(
            None, [item("instagram.zero2sudo", "media:1", text="Software Engineer Intern at Stripe", title="")]
        )
        self.assertEqual(extractor.calls, 0)
        self.assertEqual(len(self.store.list_opportunities()), 1)  # still processed, just LLM-less


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.profile = Profile(
            roles=("software engineer intern",), grad_year=2027, locations=("Remote", "United States"),
            keywords=("intern",), exclude=("senior",),
        )

    def test_matching_opportunity_passes_with_a_reason(self):
        opp = {"title": "Software Engineer Intern", "company": "Stripe", "location": "Remote",
               "fields": {"Season / Year": "Summer 2027"}}
        ok, reasons = matches_profile(opp, self.profile)
        self.assertTrue(ok)
        self.assertTrue(reasons)

    def test_us_city_state_matches_united_states(self):
        opp = {"title": "Software Engineer Intern", "company": "Stripe", "location": "New York, NY", "fields": {}}
        ok, reasons = matches_profile(opp, self.profile)
        self.assertTrue(ok, reasons)

    def test_excluded_keyword_fails_with_a_reason(self):
        opp = {"title": "Senior Software Engineer Intern", "company": "Stripe", "location": "Remote", "fields": {}}
        ok, reasons = matches_profile(opp, self.profile)
        self.assertFalse(ok)
        self.assertIn("senior", reasons[0])

    def test_exclude_only_checks_the_title_not_free_text_fields(self):
        opp = {"title": "Software Engineer Intern", "company": "Stripe", "location": "Remote",
               "fields": {"Raw Text": "open to juniors and seniors alike"}}
        ok, reasons = matches_profile(opp, self.profile)
        self.assertTrue(ok, reasons)

    def test_no_role_keyword_fails(self):
        opp = {"title": "Marketing Manager", "company": "Stripe", "location": "Remote", "fields": {}}
        ok, reasons = matches_profile(opp, self.profile)
        self.assertFalse(ok)

    def test_wrong_grad_year_season_fails(self):
        opp = {"title": "Software Engineer Intern", "company": "Stripe", "location": "Remote",
               "fields": {"Season / Year": "Summer 2026"}}
        ok, reasons = matches_profile(opp, self.profile)
        self.assertFalse(ok)

    def test_wrong_location_fails(self):
        opp = {"title": "Software Engineer Intern", "company": "Stripe", "location": "London", "fields": {}}
        ok, reasons = matches_profile(opp, self.profile)
        self.assertFalse(ok)


class FakeFailOnceChannel:
    name = "ntfy"

    def __init__(self):
        self.sent = []
        self.failed_once = False

    def send(self, opp, reasons, drop_latency_s):
        if not self.failed_once:
            self.failed_once = True
            raise RuntimeError("channel unavailable")
        self.sent.append(opp["id"])


class AlertRetryWiringTests(unittest.IsolatedAsyncioTestCase):
    """Scheduler._run_one calls the sink every poll tick, even with zero new
    items (radar/scheduler.py); that is the only retry timer a pending alert
    gets, so Pipeline must sweep it on an empty batch too (T7-alerts.md)."""

    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(self.store.close)

    async def test_empty_item_batch_still_retries_a_pending_alert(self):
        channel = FakeFailOnceChannel()
        alerter = AlertDispatcher(self.store, profile=Profile(keywords=("intern",)), channels=[channel])
        p = Pipeline(self.store, enricher=Enricher(self.store, extractor=FakeExtractor()), alerter=alerter)

        await p(None, [item("ats.greenhouse.stripe", "1")])  # claims the alert, fails to send
        self.assertEqual(channel.sent, [])
        self.assertIsNone(self.store.get_alert(self.store.list_opportunities()[0]["id"], "ntfy")["sent_at"])

        alerter._backoff_until.clear()  # simulate backoff having elapsed
        await p(None, [])  # an ordinary poll tick with nothing new
        self.assertEqual(len(channel.sent), 1)

    async def test_retry_sweep_failure_never_blocks_ingestion(self):
        """A bug in the retry sweep (any exception) must not stop this or any
        other source's items from being stored -- Pipeline.__call__ is the
        sink for every source, so one broken alert must not halt them all."""
        class BrokenAlerter:
            async def retry_pending(self):
                raise RuntimeError("boom")

            async def dispatch(self, item, opportunity_id):
                pass

        p = Pipeline(self.store, enricher=Enricher(self.store, extractor=FakeExtractor()), alerter=BrokenAlerter())
        await p(None, [item("ats.greenhouse.stripe", "1")])
        self.assertEqual(len(self.store.list_opportunities()), 1)

    async def test_fresh_ingestion_does_not_wait_behind_old_alert_retries(self):
        retrying, release = asyncio.Event(), asyncio.Event()

        class SlowRetry:
            async def retry_pending(self):
                retrying.set()
                await release.wait()

            async def dispatch(self, *_):
                pass

        p = pipeline(self.store)
        p.alerter = SlowRetry()
        announced = []
        p.on_new = announced.append
        task = asyncio.create_task(p(None, [item("ats.greenhouse.a", "1")]))
        try:
            await asyncio.wait_for(retrying.wait(), 1)
            self.assertEqual(len(announced), 1)
        finally:
            release.set()
            await task


class BackfillTests(unittest.IsolatedAsyncioTestCase):
    """A source's first poll stores what's already open (raw={"seed": True}) so the
    feed isn't empty on day one -- but it was open before anyone was watching, so
    it is never pushed to a phone or announced on the live stream."""

    async def test_a_seed_is_stored_and_enriched_but_never_alerted_or_announced(self):
        store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(store.close)

        class Channel:
            name, sent = "ntfy", []

            def send(self, opp, reasons, latency):
                self.sent.append(opp["id"])

        channel = Channel()
        announced = []
        p = Pipeline(store, enricher=Enricher(store, extractor=FakeExtractor()),
                     alerter=AlertDispatcher(store, profile=Profile(keywords=("intern",)), channels=[channel]))
        p.on_new = announced.append
        await p(None, [item("ats.greenhouse.stripe", "1", raw={"seed": True},
                            title="Software Engineering Internship (Summer 2027)")])
        [opp] = store.list_opportunities()
        self.assertEqual((channel.sent, announced), ([], []))
        self.assertIsNone(store.get_alert(opp["id"], "ntfy"))
        self.assertEqual(store.get_opportunity(opp["id"])["fields"].get("Season / Year"), "Summer 2027",
                         "enriched like any other item")

        await p(None, [item("ats.greenhouse.stripe", "2", url="https://boards.greenhouse.io/stripe/jobs/2")])
        self.assertEqual(len(channel.sent), 1, "a genuinely new posting still alerts")
        self.assertEqual(len(announced), 1)

    async def test_a_posting_dated_long_before_we_saw_it_is_backfill_not_a_drop(self):
        # a title edit, a widened search or a late list row surfaces an old posting as a new sighting
        store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(store.close)

        class Channel:
            name, sent = "ntfy", []

            def send(self, opp, reasons, latency):
                self.sent.append(opp["id"])

        channel, announced = Channel(), []
        p = Pipeline(store, enricher=Enricher(store, extractor=FakeExtractor()),
                     alerter=AlertDispatcher(store, profile=Profile(keywords=("intern",)), channels=[channel]))
        p.on_new = announced.append
        days = lambda n: T0 - timedelta(days=n)  # noqa: E731
        await p(None, [
            item("ats.oracle.x", "old", url="https://x.example/job/old", published_at=days(10)),
            item("ats.oracle.x", "fresh", url="https://x.example/job/fresh", published_at=days(2)),
            item("ats.oracle.x", "naive", url="https://x.example/job/naive", published_at=datetime(2026, 8, 1)),
        ])
        old = store.item_opportunity_id("ats.oracle.x", "old")
        self.assertEqual(len(channel.sent), 2, "the 2-day-old and the undatable one still alert; the 10-day-old does not")
        self.assertNotIn(old, channel.sent)
        self.assertEqual(len(announced), 2)
        mine = {"ats.oracle.x"}  # the backfill filter is per source set
        self.assertEqual(len(store.list_opportunities(source_names=mine, backfill=False)), 2)
        self.assertEqual([o["id"] for o in store.list_opportunities(source_names=mine, backfill=True)], [old])


if __name__ == "__main__":
    unittest.main()
