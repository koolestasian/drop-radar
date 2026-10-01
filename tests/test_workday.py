"""WorkdaySource against the public CXS jobs endpoint shape, verified live
2026-10-01 on 14 tenants (POST /wday/cxs/<tenant>/<site>/jobs ->
{"total", "jobPostings": [{title, externalPath, locationsText, postedOn, bulletFields}]})."""
import asyncio
import unittest

from radar.config import Company
from radar.errors import ConfigError, SourceError
from radar.models import utcnow
from radar.scheduler import FetchContext, HostLimiter
from radar.sources import registry
from radar.sources.workday import QUERIES, WorkdaySource

JOBS = "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/Campus/jobs"


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code, self._payload = status_code, payload

    def json(self):
        return self._payload


class FakeWorkday:
    """Answers POSTs to JOBS from {searchText: [postings]}, paginated by limit/offset."""

    def __init__(self, by_query, status=200):
        self.by_query, self.status, self.calls = by_query, status, []

    async def post(self, url, json=None, **kwargs):
        assert url == JOBS, url
        self.calls.append((json["searchText"], json["offset"]))
        if self.status != 200:
            return FakeResponse(self.status)
        rows = self.by_query.get(json["searchText"], [])
        page = rows[json["offset"]:json["offset"] + json["limit"]]
        return FakeResponse(payload={"total": len(rows), "jobPostings": page})


class Clock:
    def now(self):
        return utcnow()

    async def sleep(self, seconds):
        await asyncio.sleep(0)


def ctx(http, cursor=None):
    clock = Clock()
    return FetchContext("t", http, clock, HostLimiter(clock, per_second=1000.0), asyncio.Semaphore(5), None, cursor)


def posting(n, title, location="New York, NY"):
    return {"title": title, "externalPath": f"/job/NY/{n}", "locationsText": location,
            "postedOn": "Posted Today", "bulletFields": [f"R{n}"]}


def source(slug="acme.wd5/Campus"):
    return WorkdaySource(Company(name="Acme Bank", ats="workday", slug=slug))


class WorkdaySourceTests(unittest.IsolatedAsyncioTestCase):
    def test_slug_names_tenant_host_and_site(self):
        s = source()
        self.assertEqual(s.name, "ats.workday.acme.wd5/Campus")
        self.assertEqual(s.jobs_url(), JOBS)

    def test_bad_slug_is_a_config_error_naming_the_expected_shape(self):
        for slug in ("acme", "acme/Campus", "acme.wd5", "https://acme.wd5.myworkdayjobs.com/Campus"):
            with self.subTest(slug=slug), self.assertRaisesRegex(ConfigError, "tenant.wdN/site"):
                source(slug)

    def test_registered_as_an_ats_kind(self):
        sources, skipped = registry.build_sources(
            type("W", (), {"companies": (Company("Acme", "workday", "acme.wd5/Campus"),),
                           "instagram": (), "feeds": (), "repos": ()})())
        self.assertEqual(([s.name for s in sources], skipped), (["ats.workday.acme.wd5/Campus"], []))

    async def test_seeds_silently_then_emits_only_new_early_career_postings(self):
        baseline = [posting(1, "2027 Summer Analyst - Investment Banking"), posting(2, "Vice President, Risk")]
        seed = ctx(FakeWorkday({"": baseline}))
        self.assertEqual(await source().fetch(seed), [])

        later = [posting(3, "Software Engineer Intern - Summer 2027", "Santa Clara, CA")] + baseline
        items = await source().fetch(ctx(FakeWorkday({"": later}), cursor=seed.pending["cursor"]))
        [item] = items
        self.assertEqual((item.source, item.external_id, item.title, item.location, item.company),
                         ("ats.workday.acme.wd5/Campus", "/job/NY/3", "Software Engineer Intern - Summer 2027",
                          "Santa Clara, CA", "Acme Bank"))
        self.assertEqual(item.url, "https://acme.wd5.myworkdayjobs.com/Campus/job/NY/3")

    async def test_a_posting_found_only_by_a_targeted_search_counts(self):
        """The newest-first page can miss an older posting a search still finds."""
        seed = ctx(FakeWorkday({}))
        await source().fetch(seed)
        http = FakeWorkday({"summer analyst": [posting(9, "Summer Analyst - Sales & Trading")]})
        items = await source().fetch(ctx(http, cursor=seed.pending["cursor"]))
        self.assertEqual([i.external_id for i in items], ["/job/NY/9"])

    async def test_the_same_posting_from_several_searches_is_one_item(self):
        seed = ctx(FakeWorkday({}))
        await source().fetch(seed)
        p = posting(5, "Summer Analyst - Investment Banking")
        http = FakeWorkday({q: [p] for q in QUERIES})
        items = await source().fetch(ctx(http, cursor=seed.pending["cursor"]))
        self.assertEqual(len(items), 1)

    async def test_request_budget_is_bounded_per_poll(self):
        many = [posting(n, f"Analyst {n}") for n in range(200)]
        http = FakeWorkday({q: many for q in QUERIES})
        await source().fetch(ctx(http))
        self.assertLessEqual(len(http.calls), len(QUERIES) + 1)  # newest-first gets 2 pages, searches 1

    async def test_never_reports_closed_postings(self):
        """Paged search can't see the whole board, so a vanished id may just
        have slid off a page -- never guess it closed."""
        seed = ctx(FakeWorkday({"": [posting(1, "2027 Summer Analyst")]}))
        await source().fetch(seed)
        slid_off = FakeWorkday({"": [posting(2, "Vice President, Risk")]})
        items = await source().fetch(ctx(slid_off, cursor=seed.pending["cursor"]))
        self.assertEqual([i for i in items if i.raw.get("closed")], [])

    async def test_http_errors_map_to_source_error_kinds(self):
        for status, kind in ((429, "blocked"), (503, "transient"), (422, "schema"), (401, "schema")):
            with self.subTest(status=status):
                with self.assertRaises(SourceError) as caught:
                    await source().fetch(ctx(FakeWorkday({}, status=status)))
                self.assertEqual(caught.exception.kind, kind)


if __name__ == "__main__":
    unittest.main()
