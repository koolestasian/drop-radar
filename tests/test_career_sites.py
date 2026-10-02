"""Companies on their own career-site platforms (not a per-board ATS listing):
Oracle HCM, Eightfold, Amazon, Google, Workable. Offline; payload shapes are
trimmed copies of live responses from 2026-10-02."""
import asyncio
import json
import unittest

from radar.config import Company
from radar.errors import ConfigError, SourceError
from radar.models import utcnow
from radar.scheduler import FetchContext, HostLimiter
from radar.sources import registry
from radar.sources.discover import _slug_from_url


class Resp:
    def __init__(self, payload=None, status_code=200, text=None):
        self.status_code, self._payload, self.headers = status_code, payload, {}
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON")
        return self._payload


class FakeHttp:
    """route(method, url, json_body) -> Resp, so a test can serve one 'board state' per poll."""

    def __init__(self, route):
        self.route, self.calls = route, []

    async def get(self, url, **kw):
        self.calls.append(("GET", url))
        return self.route("GET", url, None)

    async def post(self, url, json=None, **kw):
        self.calls.append(("POST", url))
        return self.route("POST", url, json)


class Clock:
    def now(self):
        return utcnow()

    async def sleep(self, s):
        await asyncio.sleep(0)


def ctx(http, cursor=None):
    clock = Clock()
    return FetchContext("t", http, clock, HostLimiter(clock, 1000.0), asyncio.Semaphore(5), None, cursor)


def source(ats, slug):
    registry._import_source_modules()
    return registry.FACTORIES[ats](Company(name="Acme", ats=ats, slug=slug, tier="B"), None)


class WindowedContract:
    """Seed silently, then exactly one item for one new posting; never a closed signal
    for a posting that merely left the search window."""
    ats = slug = None

    def jobs(self, new):  # -> route function serving the old jobs, plus one new one if `new`
        raise NotImplementedError

    async def test_seed_then_one_new_posting_and_no_false_close(self):
        src = source(self.ats, self.slug)
        first = ctx(FakeHttp(self.jobs(new=False)))
        seeded = await src.fetch(first)
        self.assertTrue(seeded and all(i.raw == {"seed": True} for i in seeded))
        self.assertTrue(all(i.url.startswith("https://") for i in seeded))

        later = ctx(FakeHttp(self.jobs(new=True)), cursor=first.pending["cursor"])
        items = await src.fetch(later)
        self.assertEqual([(i.external_id, i.raw) for i in items], [(self.new_id, {})])
        self.assertIsNotNone(items[0].published_at)

        gone = ctx(FakeHttp(self.jobs(new=False)), cursor=later.pending["cursor"])
        self.assertEqual(await src.fetch(gone), [])  # the new one fell out of the window: not "closed"


class OracleTests(WindowedContract, unittest.IsolatedAsyncioTestCase):
    ats, slug, new_id = "oracle", "egug.fa.us2/CX_1", "26020002"

    def jobs(self, new):
        reqs = [{"Id": "26010001", "Title": "Software Engineer Intern", "PostedDate": "2026-09-30",
                 "PrimaryLocation": "New York, NY, United States"},
                {"Id": "26010009", "Title": "Director, Compliance", "PostedDate": "2026-09-30", "PrimaryLocation": ""}]
        if new:
            reqs.insert(0, {"Id": self.new_id, "Title": "Technology Summer Analyst 2027", "PostedDate": "2026-10-02",
                            "PrimaryLocation": "Phoenix, AZ, United States"})

        def route(method, url, body):
            assert url.startswith("https://egug.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/"
                                  "recruitingCEJobRequisitions?"), url
            assert "siteNumber=CX_1" in url and "sortBy=POSTING_DATES_DESC" in url
            return Resp({"items": [{"TotalJobsCount": len(reqs), "requisitionList": reqs}]})
        return route

    async def test_job_url_is_the_candidate_experience_page(self):
        [item] = await source(self.ats, self.slug).fetch(ctx(FakeHttp(self.jobs(new=False))))
        self.assertEqual(item.url, "https://egug.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/26010001")

    def test_bad_slug(self):
        with self.assertRaises(ConfigError):
            source("oracle", "egug")


class EightfoldTests(WindowedContract, unittest.IsolatedAsyncioTestCase):
    ats, slug, new_id = "eightfold", "apply.careers.microsoft.com/microsoft.com", "1970393557021999"

    def jobs(self, new):
        pos = [{"id": 1970393557021552, "name": "Software Engineer - Intern", "locations": ["Redmond, WA, US"],
                "postedTs": 1790908370, "positionUrl": "/careers/job/1970393557021552"}]
        if new:
            pos.insert(0, {"id": int(self.new_id), "name": "Software Engineer: New Graduate", "locations": [],
                           "postedTs": 1790990000, "positionUrl": f"/careers/job/{self.new_id}"})

        def route(method, url, body):
            assert url.startswith("https://apply.careers.microsoft.com/api/pcsx/search?domain=microsoft.com&"), url
            start = int(url.split("start=")[1].split("&")[0])
            return Resp({"status": 200, "data": {"positions": pos[start:start + 10], "count": len(pos)}})
        return route


class AmazonTests(WindowedContract, unittest.IsolatedAsyncioTestCase):
    ats, slug, new_id = "amazon", "amazon", "10567999"

    def jobs(self, new):
        jobs = [{"id_icims": "10566344", "title": "Software Dev Engineer Intern", "posted_date": "October  1, 2026",
                 "job_path": "/en/jobs/10566344/software-dev-engineer-intern", "normalized_location": "Seattle, WA, USA"}]
        if new:
            jobs.insert(0, {"id_icims": self.new_id, "title": "Software Dev Engineer I, 2027 University Graduate",
                            "posted_date": "October 2, 2026", "job_path": f"/en/jobs/{self.new_id}/sde",
                            "normalized_location": "Austin, TX, USA"})

        def route(method, url, body):
            assert url.startswith("https://www.amazon.jobs/en/search.json?"), url
            return Resp({"hits": len(jobs), "jobs": jobs})
        return route


class GoogleTests(WindowedContract, unittest.IsolatedAsyncioTestCase):
    ats, slug, new_id = "google", "google", "105628505345000002"

    def jobs(self, new):
        rows = [["105628505345000001", "Software Engineering Intern, BS, Summer 2027", None, None, None, None, None,
                 "Google", "en-US", [["Mountain View, CA, USA"]], None, None, [1790919373, 0]]]
        if new:
            rows.insert(0, [self.new_id, "Software Engineer, Early Career, 2027", None, None, None, None, None,
                            "Google", "en-US", [["New York, NY, USA"]], None, None, [1790999999, 0]])
        page = ("<html><script>AF_initDataCallback({key: 'ds:1', hash: '2', data:"
                + json.dumps([rows, None, len(rows), 20]) + ", sideChannel: {}});</script></html>")

        def route(method, url, body):
            assert url.startswith("https://www.google.com/about/careers/applications/jobs/results?"), url
            return Resp(text=page)
        return route

    async def test_page_without_the_data_block_is_a_schema_error(self):
        http = FakeHttp(lambda *a: Resp(text="<html>captcha</html>"))
        with self.assertRaises(SourceError) as err:
            await source("google", "google").fetch(ctx(http))
        self.assertEqual(err.exception.kind, "schema")


class WorkableTests(unittest.IsolatedAsyncioTestCase):
    """A whole-board listing (paged by token), so closed detection stays on."""

    def board(self, shortcodes):
        jobs = [{"shortcode": s, "title": f"Software Engineer Intern {s}", "published": "2026-09-01T00:00:00.000Z",
                 "location": {"city": "Arlington", "region": "Virginia", "country": "United States"}} for s in shortcodes]

        def route(method, url, body):
            assert (method, url) == ("POST", "https://apply.workable.com/api/v3/accounts/acme/jobs"), (method, url)
            start = int(body.get("token") or 0)
            nxt = str(start + 10) if start + 10 < len(jobs) else None
            return Resp({"total": len(jobs), "results": jobs[start:start + 10], **({"nextPage": nxt} if nxt else {})})
        return route

    async def test_pages_through_the_board_then_diffs_it(self):
        src = source("workable", "acme")
        first_ids = [f"A{i:02}" for i in range(12)]  # two pages
        first = ctx(FakeHttp(self.board(first_ids)))
        self.assertEqual(len(await src.fetch(first)), 12)
        later = ctx(FakeHttp(self.board(first_ids[1:] + ["NEW"])), cursor=first.pending["cursor"])
        items = await src.fetch(later)
        self.assertEqual(sorted((i.external_id, bool(i.raw.get("closed"))) for i in items), [("A00", True), ("NEW", False)])
        self.assertEqual([i.url for i in items if i.external_id == "NEW"], ["https://apply.workable.com/acme/j/NEW/"])


class MiningTests(unittest.TestCase):
    def test_career_site_links(self):
        cases = {
            "https://egug.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/26011987": ("oracle", "egug.fa.us2/CX_1"),
            "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/210773978": ("oracle", "jpmc.fa/CX_1001"),
            "https://fa-evmr-saasfaprod1.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/39978":
                ("oracle", "fa-evmr-saasfaprod1.fa.ocs/CX_1"),
            "https://qualcomm.eightfold.ai/careers/job/446716226621": ("eightfold", "qualcomm.eightfold.ai/qualcomm.com"),
            "https://apply.workable.com/avalore/j/F157AC3B65/apply": ("workable", "avalore"),
        }
        for url, want in cases.items():
            self.assertEqual(_slug_from_url(url), want, url)


if __name__ == "__main__":
    unittest.main()
