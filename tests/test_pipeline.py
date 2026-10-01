import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

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
    return Pipeline(store, enricher=Enricher(store, extractor=extractor or FakeExtractor()))


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
        await Pipeline(self.store, enricher=enricher)(
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


if __name__ == "__main__":
    unittest.main()
