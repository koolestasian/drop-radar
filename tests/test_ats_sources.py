import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from radar.config import Company
from radar.errors import SourceError
from radar.models import utcnow
from radar.scheduler import FetchContext, HostLimiter, Scheduler
from radar.sources import registry
from radar.sources.ashby import AshbySource
from radar.sources.ats import matches_title
from radar.sources.discover import mine_tracker_slugs
from radar.sources.greenhouse import GreenhouseSource
from radar.sources.lever import LeverSource
from radar.sources.smartrecruiters import SmartRecruitersSource
from radar.store import Store


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text="not json"):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload


class FakeHttp:
    """Routes keyed by exact URL; records every URL `ctx.get` is asked for."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append(url)
        if url not in self.routes:
            raise AssertionError(f"unexpected URL requested: {url}")
        result = self.routes[url]
        if isinstance(result, Exception):
            raise result
        return result


class FakeClock:
    def __init__(self):
        self.t = utcnow()

    def now(self):
        return self.t

    async def sleep(self, seconds):
        await asyncio.sleep(0)


def make_ctx(http, cursor=None):
    clock = FakeClock()
    return FetchContext(
        "test", http, clock, HostLimiter(clock, per_second=1000.0), asyncio.Semaphore(10), None, cursor,
    )


def company(ats, slug="acme", tier="B"):
    return Company(name="Acme", ats=ats, slug=slug, tier=tier)


class AtsSourceContractMixin:
    """Shared assertions run against each concrete ATS source.

    Not a TestCase itself (no source_cls set) -- mixed into one per ATS below
    so unittest discovery doesn't try to instantiate and run this directly.
    """

    source_cls = None  # set by subclass
    ats = None

    def url(self, slug="acme"):
        return self.source_cls(company(self.ats, slug)).board_url()

    async def test_first_poll_seeds_baseline_and_emits_nothing(self):
        http = FakeHttp({self.url(): FakeResponse(payload=self.payload(self.baseline_jobs()))})
        source = self.source_cls(company(self.ats))
        ctx = make_ctx(http)
        items = await source.fetch(ctx)
        self.assertEqual(items, [])
        self.assertEqual(http.calls, [self.url()])  # fetch went through ctx.get, one request
        self.assertIn("cursor", ctx.pending)

    async def test_second_poll_with_one_new_job_emits_exactly_one_item(self):
        source = self.source_cls(company(self.ats))
        seed_ctx = make_ctx(FakeHttp({self.url(): FakeResponse(payload=self.payload(self.baseline_jobs()))}))
        await source.fetch(seed_ctx)

        jobs = self.baseline_jobs() + [self.new_job()]
        http = FakeHttp({self.url(): FakeResponse(payload=self.payload(jobs))})
        ctx = make_ctx(http, cursor=seed_ctx.pending["cursor"])
        items = await source.fetch(ctx)

        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.external_id, self.new_job_id())
        self.assertEqual(item.source, f"ats.{self.ats}.acme")
        self.assertTrue(matches_title(item.title))
        self.assertIsNotNone(item.published_at)
        self.assertIsNotNone(item.published_at.tzinfo)

    async def test_removed_job_emits_closed_signal(self):
        source = self.source_cls(company(self.ats))
        seed_ctx = make_ctx(FakeHttp({self.url(): FakeResponse(payload=self.payload(self.baseline_jobs()))}))
        await source.fetch(seed_ctx)

        remaining = self.baseline_jobs()[1:]  # drop the first (matching) posting
        http = FakeHttp({self.url(): FakeResponse(payload=self.payload(remaining))})
        ctx = make_ctx(http, cursor=seed_ctx.pending["cursor"])
        items = await source.fetch(ctx)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].external_id, self.baseline_matching_id())
        self.assertEqual(items[0].raw, {"closed": True})
        self.assertEqual(items[0].source, f"ats.{self.ats}.acme")

    async def test_non_200_raises_schema_error(self):
        http = FakeHttp({self.url(): FakeResponse(status_code=404, payload=None)})
        with self.assertRaises(SourceError) as ctxmgr:
            await self.source_cls(company(self.ats)).fetch(make_ctx(http))
        self.assertEqual(ctxmgr.exception.kind, "schema")

    async def test_unparseable_json_raises_schema_error(self):
        http = FakeHttp({self.url(): FakeResponse(payload=None)})  # .json() raises
        with self.assertRaises(SourceError) as ctxmgr:
            await self.source_cls(company(self.ats)).fetch(make_ctx(http))
        self.assertEqual(ctxmgr.exception.kind, "schema")

    async def test_missing_expected_key_raises_schema_error(self):
        http = FakeHttp({self.url(): FakeResponse(payload={"unexpected": "shape"})})
        with self.assertRaises(SourceError) as ctxmgr:
            await self.source_cls(company(self.ats)).fetch(make_ctx(http))
        self.assertEqual(ctxmgr.exception.kind, "schema")

    async def test_429_raises_blocked_error(self):
        http = FakeHttp({self.url(): FakeResponse(status_code=429, payload={})})
        with self.assertRaises(SourceError) as ctxmgr:
            await self.source_cls(company(self.ats)).fetch(make_ctx(http))
        self.assertEqual(ctxmgr.exception.kind, "blocked")

    async def test_connection_error_raises_transient(self):
        http = FakeHttp({self.url(): ConnectionError("boom")})
        with self.assertRaises(SourceError) as ctxmgr:
            await self.source_cls(company(self.ats)).fetch(make_ctx(http))
        self.assertEqual(ctxmgr.exception.kind, "transient")

    async def test_interval_from_tier(self):
        self.assertEqual(self.source_cls(company(self.ats, tier="S")).interval_s, 120.0)
        self.assertEqual(self.source_cls(company(self.ats, tier="A")).interval_s, 120.0)
        self.assertEqual(self.source_cls(company(self.ats, tier="B")).interval_s, 300.0)
        self.assertEqual(self.source_cls(company(self.ats, tier="C")).interval_s, 900.0)


class GreenhouseTests(AtsSourceContractMixin, unittest.IsolatedAsyncioTestCase):
    source_cls, ats = GreenhouseSource, "greenhouse"

    def payload(self, jobs):
        return {"jobs": jobs}

    def baseline_jobs(self):
        return [
            {"id": 1, "title": "Software Engineering Intern, Summer 2027",
             "updated_at": "2026-01-10T12:00:00Z", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
             "location": {"name": "Remote"}},
            {"id": 2, "title": "Senior Staff Engineer", "updated_at": "2026-01-10T12:00:00Z",
             "absolute_url": "https://boards.greenhouse.io/acme/jobs/2", "location": {"name": "NYC"}},
        ]

    def new_job(self):
        return {"id": 3, "title": "New Grad Software Engineer 2027", "updated_at": "2026-02-01T00:00:00Z",
                "absolute_url": "https://boards.greenhouse.io/acme/jobs/3", "location": {"name": "SF"}}

    def new_job_id(self):
        return "3"

    def baseline_matching_id(self):
        return "1"


class LeverTests(AtsSourceContractMixin, unittest.IsolatedAsyncioTestCase):
    source_cls, ats = LeverSource, "lever"

    def payload(self, jobs):
        return jobs  # Lever returns a JSON array directly

    def baseline_jobs(self):
        return [
            {"id": "a1", "text": "Data Engineering Co-op", "createdAt": 1770000000000,
             "categories": {"location": "Remote"}, "hostedUrl": "https://jobs.lever.co/acme/a1"},
            {"id": "a2", "text": "Staff Engineer", "createdAt": 1770000000000,
             "categories": {"location": "NYC"}, "hostedUrl": "https://jobs.lever.co/acme/a2"},
        ]

    def new_job(self):
        return {"id": "a3", "text": "Early Career Research Fellowship", "createdAt": 1772000000000,
                "categories": {"location": "Remote"}, "hostedUrl": "https://jobs.lever.co/acme/a3"}

    def new_job_id(self):
        return "a3"

    def baseline_matching_id(self):
        return "a1"


class AshbyTests(AtsSourceContractMixin, unittest.IsolatedAsyncioTestCase):
    source_cls, ats = AshbySource, "ashby"

    def payload(self, jobs):
        return {"jobs": jobs}

    def baseline_jobs(self):
        return [
            {"id": "b1", "title": "Residency Program 2026", "publishedAt": "2026-01-15T00:00:00Z",
             "isListed": True, "jobUrl": "https://jobs.ashbyhq.com/acme/b1", "location": "Remote"},
            {"id": "b2", "title": "Principal Engineer", "publishedAt": "2026-01-15T00:00:00Z",
             "isListed": True, "jobUrl": "https://jobs.ashbyhq.com/acme/b2", "location": "NYC"},
            {"id": "b3", "title": "Unlisted Internship", "publishedAt": "2026-01-15T00:00:00Z",
             "isListed": False, "jobUrl": "https://jobs.ashbyhq.com/acme/b3", "location": "NYC"},
        ]

    def new_job(self):
        return {"id": "b4", "title": "Apprentice, Platform Team", "publishedAt": "2026-02-10T00:00:00Z",
                "isListed": True, "jobUrl": "https://jobs.ashbyhq.com/acme/b4", "location": "Remote"}

    def new_job_id(self):
        return "b4"

    def baseline_matching_id(self):
        return "b1"

    async def test_unlisted_job_is_never_tracked(self):
        http = FakeHttp({self.url(): FakeResponse(payload=self.payload(self.baseline_jobs()))})
        ctx = make_ctx(http)
        await self.source_cls(company(self.ats)).fetch(ctx)
        self.assertNotIn("b3", json.loads(ctx.pending["cursor"]))


class SmartRecruitersTests(AtsSourceContractMixin, unittest.IsolatedAsyncioTestCase):
    source_cls, ats = SmartRecruitersSource, "smartrecruiters"

    def payload(self, jobs):
        return {"totalFound": len(jobs), "content": jobs}

    def baseline_jobs(self):
        # "ref" is the real API's shape: its OWN self-link (api.smartrecruiters.com/...),
        # confirmed live against real boards -- never a public job page. Fixtures use
        # that real shape so a test trusting "ref" for url would actually fail.
        return [
            {"id": "c1", "name": "Fellowship: Applied Research", "releasedDate": "2026-01-20T00:00:00Z",
             "ref": "https://api.smartrecruiters.com/v1/companies/acme/postings/c1"},
            {"id": "c2", "name": "VP of Engineering", "releasedDate": "2026-01-20T00:00:00Z",
             "ref": "https://api.smartrecruiters.com/v1/companies/acme/postings/c2"},
        ]

    def new_job(self):
        return {"id": "c3", "name": "Intern - Summer 2026", "releasedDate": "2026-02-05T00:00:00Z",
                "ref": "https://api.smartrecruiters.com/v1/companies/acme/postings/c3"}

    def new_job_id(self):
        return "c3"

    def baseline_matching_id(self):
        return "c1"

    async def test_url_is_the_public_job_page_not_the_api_self_link(self):
        source = self.source_cls(company(self.ats))
        seed_ctx = make_ctx(FakeHttp({self.url(): FakeResponse(payload=self.payload(self.baseline_jobs()))}))
        await source.fetch(seed_ctx)
        jobs = self.baseline_jobs() + [self.new_job()]
        ctx = make_ctx(FakeHttp({self.url(): FakeResponse(payload=self.payload(jobs))}), seed_ctx.pending["cursor"])
        items = await source.fetch(ctx)
        self.assertEqual(items[0].url, "https://jobs.smartrecruiters.com/acme/c3")

    async def test_truncated_page_skips_closed_detection(self):
        source = self.source_cls(company(self.ats))
        seed_ctx = make_ctx(FakeHttp({self.url(): FakeResponse(payload=self.payload(self.baseline_jobs()))}))
        await source.fetch(seed_ctx)

        # totalFound says there are more postings than this page returned, and the
        # matching c1 posting isn't on this (truncated) page -- must NOT read as closed.
        page = [self.baseline_jobs()[1]]
        payload = {"totalFound": 50, "content": page}
        http = FakeHttp({self.url(): FakeResponse(payload=payload)})
        ctx = make_ctx(http, cursor=seed_ctx.pending["cursor"])
        items = await source.fetch(ctx)

        self.assertEqual(items, [])  # no closed signal fired on a merely-truncated page
        self.assertIn("c1", json.loads(ctx.pending["cursor"]))  # kept in the baseline, not dropped


class EmptyListingGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_listing_after_non_empty_baseline_is_transient_not_closed_flood(self):
        source = GreenhouseSource(company("greenhouse"))
        url = source.board_url()
        seed_jobs = [{"id": 1, "title": "Internship", "updated_at": "2026-01-01T00:00:00Z",
                      "absolute_url": "https://boards.greenhouse.io/acme/jobs/1", "location": {}}]
        seed_ctx = make_ctx(FakeHttp({url: FakeResponse(payload={"jobs": seed_jobs})}))
        await source.fetch(seed_ctx)

        http = FakeHttp({url: FakeResponse(payload={"jobs": []})})
        ctx = make_ctx(http, cursor=seed_ctx.pending["cursor"])
        with self.assertRaises(SourceError) as ctxmgr:
            await source.fetch(ctx)
        self.assertEqual(ctxmgr.exception.kind, "transient")


class TitleFilterTests(unittest.TestCase):
    def test_kept(self):
        for title in (
            "Software Engineering Intern, Summer 2027", "Data Science Interns", "Platform Internship",
            "New Grad Software Engineer", "New Graduate - Backend", "Co-Op, Infrastructure",
            "Early Career Analyst", "Research Fellowship", "Residency Program", "Apprentice Electrician",
            "Backend Engineer (Class of 2026)",
            # Business/finance and big-tech university titles that carry no "intern"/year
            # (2026-10-01 audit: these were dropped before any profile saw them).
            "Summer Analyst - Investment Banking", "Private Equity Summer Associate",
            "Analyst Program - Global Markets", "Associate Consultant", "Off-Cycle Analyst, Equity Research",
            "Software Engineer (University Grad)", "Student Researcher", "Campus Hire - Sales & Trading",
            "Rotational Program Associate", "Leadership Development Program", "Entry Level Financial Analyst",
            "Early Talent - Wealth Management", "Spring Insight Week", "Undergraduate Business Analyst",
        ):
            self.assertTrue(matches_title(title), title)

    def test_dropped(self):
        for title in (
            "Senior Staff Engineer", "Internal Tools Engineer", "International Sales Director",
            "VP of Engineering", "Principal Scientist",
        ):
            self.assertFalse(matches_title(title), title)


class SlugMiningTests(unittest.TestCase):
    """_slug_from_url has already broken twice on real tracker links (an embed
    query-param form, and app3.greenhouse.io session links with no slug in the
    path) -- pin the real cases down instead of only the happy path."""

    def test_real_tracker_link_shapes(self):
        records = [
            {"Application / Registration Link":
                "https://boards.greenhouse.io/embed/job_app?for=financialtimes33&token=123"},
            {"Application / Registration Link": "https://app3.greenhouse.io/e/arnmvw"},  # session link, no slug
            {"Application / Registration Link":
                "https://job-boards.eu.greenhouse.io/financialtimes33/jobs/4986356101?gh_src=x"},
            {"Application / Registration Link":
                "https://jobs.lever.co/arcteryx.com/826dc4d8-f91e-4893-b8d6-56706194edfb"},
            {"Application / Registration Link": "https://jobs.ashbyhq.com/acme/abc-123"},
            {"Application / Registration Link": "https://jobs.smartrecruiters.com/Acme/744000152787099"},
            {"Application / Registration Link": "https://lu.ma/some-event"},  # not an ATS link
            {"Application / Registration Link": ""},
        ]
        pairs = mine_tracker_slugs(records=records)
        self.assertEqual(pairs, sorted({
            ("ashby", "acme"),
            ("greenhouse", "financialtimes33"),  # both the embed and the direct form
            ("lever", "arcteryx.com"),
            ("smartrecruiters", "Acme"),
        }))


class RegistryTests(unittest.TestCase):
    def test_all_four_kinds_registered(self):
        registry._import_source_modules()
        for ats, cls in (
            ("greenhouse", GreenhouseSource), ("lever", LeverSource),
            ("ashby", AshbySource), ("smartrecruiters", SmartRecruitersSource),
        ):
            factory = registry.FACTORIES[ats]
            source = factory(company(ats, slug="acme"), settings=None)
            self.assertIsInstance(source, cls)
            self.assertEqual(source.name, f"ats.{ats}.acme")


class SchedulerIntegrationTests(unittest.IsolatedAsyncioTestCase):
    """End-to-end: the real Scheduler + Store drive seed-then-diff across two polls."""

    async def test_first_poll_stores_nothing_second_stores_one_opportunity(self):
        store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(store.close)
        source = GreenhouseSource(company("greenhouse", tier="B"))
        url = source.board_url()
        baseline = [{"id": 1, "title": "Senior Engineer", "updated_at": "2026-01-01T00:00:00Z",
                     "absolute_url": "https://boards.greenhouse.io/acme/jobs/1", "location": {}}]
        grown = baseline + [{"id": 2, "title": "SWE Intern, Summer 2027", "updated_at": "2026-02-01T00:00:00Z",
                              "absolute_url": "https://boards.greenhouse.io/acme/jobs/2", "location": {}}]
        http = FakeHttp({url: FakeResponse(payload={"jobs": baseline})})
        clock = FakeClock()
        sched = Scheduler([source], store, http=http, clock=clock, jitter=0)

        sched.launch_due()
        await sched.drain()
        self.assertEqual(store.list_opportunities(), [])

        http.routes[url] = FakeResponse(payload={"jobs": grown})
        clock.t = sched.next_run[source.name]
        sched.launch_due()
        await sched.drain()
        opportunities = store.list_opportunities()
        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0]["title"], "SWE Intern, Summer 2027")


if __name__ == "__main__":
    unittest.main()
