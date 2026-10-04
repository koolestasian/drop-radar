import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from radar.models import Item
from radar.pipeline import Pipeline
from radar.pipeline import pagefacts as pf
from radar.store import Store

ASHBY_HTML = """<html><head><script type="application/ld+json">%s</script></head><body>role</body></html>""" % json.dumps({
    "@context": "https://schema.org/", "@type": "JobPosting", "title": "2027 Internship Behavior ML Engineer",
    "hiringOrganization": {"@type": "Organization", "name": "Bedrock Robotics Inc"},
    "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress", "addressLocality": "San Francisco",
                                                  "addressRegion": "California", "addressCountry": "United States"}},
    "datePosted": "2026-10-02", "validThrough": None})


def response(status=200, body=b"", headers=None, json_body=None):
    r = mock.Mock()
    r.status_code, r.headers = status, headers or {}
    r.is_redirect = status in (301, 302, 303, 307, 308)
    r.content = body
    r.text = body.decode() if isinstance(body, bytes) else body
    r.json = lambda: json_body
    return r


class ReaderTests(unittest.TestCase):
    def test_json_ld_on_a_company_page_gives_the_location_company_and_date(self):
        with mock.patch.object(pf, "_robots_allows", return_value=True), \
             mock.patch.object(pf, "_get", return_value=response(body=ASHBY_HTML.encode())):
            facts = pf.fetch_facts("https://jobs.ashbyhq.com/bedrock-robotics/96a6423e")
        self.assertEqual(facts, {"title": "2027 Internship Behavior ML Engineer", "location": "San Francisco, California", "company": "Bedrock Robotics Inc",
                                 "posted": "2026-10-02", "deadline": "", "description": "", "pay": None})

    def test_workday_detail_turns_a_count_into_the_real_places(self):
        detail = {"jobPostingInfo": {"location": "Dallas, Texas", "additionalLocations": ["Austin, Texas", "Remote"],
                                     "startDate": "2026-09-28"}}
        seen = []
        def fake(url, accept="application/json"):
            seen.append(url)
            return response(json_body=detail)
        with mock.patch.object(pf, "_get", side_effect=fake):
            facts = pf.fetch_facts("https://rb.wd5.myworkdayjobs.com/en-US/FRS/job/Dallas-TX/Intern-Statistics_R-0000033575")
        self.assertEqual(facts["location"], "Dallas, Texas; Austin, Texas; Remote")
        self.assertEqual(seen, ["https://rb.wd5.myworkdayjobs.com/wday/cxs/rb/FRS/job/Dallas-TX/Intern-Statistics_R-0000033575"])

    def test_greenhouse_and_lever_and_smartrecruiters_use_their_public_apis(self):
        cases = [
            ("https://boards.greenhouse.io/xai/jobs/5255116007", {"location": {"name": "Palo Alto, CA"}, "company_name": "xAI",
                                                                    "first_published": "2026-09-01T10:00:00-04:00"}, "Palo Alto, CA"),
            ("https://jobs.lever.co/acme/f65cb715", {"categories": {"location": "Remote - US"}, "createdAt": 1790000000000}, "Remote - US"),
            ("https://jobs.smartrecruiters.com/AECOM2/744000153243027-high-school-intern",
             {"location": {"city": "Virginia Beach", "region": "va"}, "company": {"name": "AECOM"}, "releasedDate": "2026-10-02T17:21:20Z"},
             "Virginia Beach, VA"),
        ]
        for url, body, place in cases:
            with self.subTest(url=url), mock.patch.object(pf, "_get", return_value=response(json_body=body)):
                self.assertEqual(pf.fetch_facts(url)["location"], place)

    def test_each_source_hands_over_the_pay_its_posting_states(self):
        text = "The base salary range for this role is $120,000 - $165,000 per year."
        cases = [
            ("https://boards.greenhouse.io/figureai/jobs/4718858006",  # structured ranges come in cents
             {"pay_input_ranges": [{"min_cents": 12000000, "max_cents": 16500000, "currency_type": "USD"}]}, "$120,000–$165,000/yr"),
            ("https://boards.greenhouse.io/figureai/jobs/4718858006", {"content": "&lt;p&gt;" + text + "&lt;/p&gt;"}, "$120,000–$165,000/yr"),
            ("https://jobs.lever.co/weride/abc",
             {"salaryRange": {"interval": "per-year-salary", "min": 120000, "max": 165000, "currency": "USD"}}, "$120,000–$165,000/yr"),
            ("https://jobs.lever.co/acme/abc", {"descriptionPlain": "Pay: $38 - $44 per hour"}, "$38–$44/hr"),
            ("https://jobs.smartrecruiters.com/AECOM2/744000153243027-intern",
             {"compensation": {"min": 20, "max": 24, "currency": "USD", "period": "HOURLY"}}, "$20–$24/hr"),
            ("https://jobs.smartrecruiters.com/ServiceNow/74400015324302-x",
             {"jobAd": {"sections": {"jobDescription": {"text": text}}}}, "$120,000–$165,000/yr"),
            ("https://rb.wd5.myworkdayjobs.com/en-US/FRS/job/Dallas-TX/Intern_R-0000033575",
             {"jobPostingInfo": {"location": "Dallas, Texas", "jobDescription": "<p>" + text + "</p>"}}, "$120,000–$165,000/yr"),
        ]
        for url, body, expected in cases:
            with self.subTest(url=url, body=body), mock.patch.object(pf, "_get", return_value=response(json_body=body)):
                self.assertEqual(pf.show(pf.fetch_facts(url)["pay"]), expected)

    def test_ashby_pages_state_pay_in_their_schema_org_data(self):
        page = ASHBY_HTML.replace('"validThrough": null', '"validThrough": null, "baseSalary": {"@type": "MonetaryAmount", '
                                  '"currency": "USD", "value": {"@type": "QuantitativeValue", "minValue": 62, "maxValue": 72, '
                                  '"unitText": "HOUR"}}')
        with mock.patch.object(pf, "_robots_allows", return_value=True), \
             mock.patch.object(pf, "_get", return_value=response(body=page.encode())):
            self.assertEqual(pf.show(pf.fetch_facts("https://jobs.ashbyhq.com/vey/3a34578d")["pay"]), "$62–$72/hr")

    def test_nothing_is_fetched_from_private_or_internal_addresses(self):
        for url in ("http://169.254.169.254/latest/meta-data", "http://127.0.0.1:8000/api/me", "http://10.0.0.5/x",
                    "http://localhost/x", "file:///etc/passwd", "ftp://example.com/x"):
            with self.subTest(url=url), mock.patch("requests.get") as get:
                self.assertIsNone(pf._get(url))
                get.assert_not_called()

    def test_a_redirect_into_a_private_address_is_not_followed(self):
        redirect = response(302, headers={"location": "http://169.254.169.254/latest"})
        with mock.patch.object(pf, "_public", side_effect=lambda host: host == "jobs.example.com"), \
             mock.patch("requests.get", return_value=redirect) as get, mock.patch.object(pf.time, "sleep"):
            self.assertIsNone(pf._get("https://jobs.example.com/x"))
        self.assertEqual(get.call_count, 1)

    def test_a_page_robots_txt_disallows_is_not_read(self):
        pf._robots.clear()
        def fake(url, accept="application/json"):
            if url.endswith("/robots.txt"):
                return response(body=b"User-agent: *\nDisallow: /careers/")
            raise AssertionError("the page itself must not be fetched")
        with mock.patch.object(pf, "_get", side_effect=fake):
            self.assertIsNone(pf.fetch_facts("https://www.example-co.com/careers/job-1"))

    def test_the_answer_never_raises(self):
        with mock.patch.object(pf, "_get", side_effect=RuntimeError("boom")):
            self.assertIsNone(pf.fetch_facts("https://rb.wd5.myworkdayjobs.com/FRS/job/Dallas-TX/x_R-1"))


class ApplyTests(unittest.TestCase):
    FACTS = {"location": "San Francisco, California", "company": "Bedrock", "posted": "2026-10-02", "deadline": "2026-11-01"}

    def test_blanks_and_bare_counts_are_filled(self):
        for loc in ("", "  ", "4 Locations", "12 locations"):
            with self.subTest(loc=loc):
                out = pf.changes_for({"location": loc, "company": "", "published_at": None, "deadline": ""}, self.FACTS)
                self.assertEqual(out["location"], "San Francisco, California")
                self.assertEqual((out["company"], out["published_at"], out["deadline"]),
                                 ("Bedrock", "2026-10-02T00:00:00+00:00", "2026-11-01"))

    def test_a_value_the_source_stated_is_never_changed(self):
        opp = {"location": "New York, NY", "company": "Stripe", "published_at": "2026-09-01T00:00:00+00:00", "deadline": "2026-12-01"}
        self.assertEqual(pf.changes_for(opp, self.FACTS), {})
        self.assertEqual(pf.changes_for({**opp, "location": "4 locations | Des Moines, IA | Raleigh, NC"}, self.FACTS), {})

    def test_what_needs_filling(self):
        base = {"location": "NYC", "company": "X", "published_at": "2026-09-01T00:00:00+00:00"}
        self.assertFalse(pf.needs_facts(base))
        for change in ({"location": ""}, {"location": "3 locations"}, {"company": ""}, {"published_at": None}):
            self.assertTrue(pf.needs_facts({**base, **change}), change)


class PageFactsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(self.store.close)
        self.when = datetime(2026, 10, 2, tzinfo=timezone.utc)

    def add(self, external_id="a", location="", company="Bedrock", url="https://jobs.ashbyhq.com/b/1"):
        opp, _ = self.store.upsert_item(Item(source="ats.ashby.b", external_id=external_id, url=url, title="Intern", company=company,
                                              location=location, seen_at=self.when, published_at=self.when))
        return opp

    async def test_fill_sets_the_blank_caches_and_does_not_refetch(self):
        opp = self.add()
        fetch = mock.Mock(return_value={"location": "San Francisco, California", "company": "", "posted": "", "deadline": ""})
        pages = pf.PageFacts(self.store, fetch=fetch)
        self.assertEqual(await pages.fill(opp), {"location": "San Francisco, California"})
        self.assertEqual(self.store.get_opportunity(opp)["location"], "San Francisco, California")
        await pages.fill(opp)
        self.assertEqual(fetch.call_count, 1)

    async def test_a_dry_run_writes_nothing(self):
        opp = self.add()
        pages = pf.PageFacts(self.store, fetch=lambda url: {"location": "Austin, Texas"})
        self.assertEqual(await pages.fill(opp, dry_run=True), {"location": "Austin, Texas"})
        self.assertEqual(self.store.get_opportunity(opp)["location"], "")
        self.assertIsNone(self.store.get_enrichment("page:https://jobs.ashbyhq.com/b/1"))

    async def test_a_page_that_gave_nothing_is_asked_again_only_after_a_week(self):
        opp = self.add()
        fetch = mock.Mock(return_value=None)
        pages = pf.PageFacts(self.store, fetch=fetch)
        await pages.fill(opp)
        await pages.fill(opp)
        self.assertEqual(fetch.call_count, 1)
        self.store.set_enrichment("page:https://jobs.ashbyhq.com/b/1", {"t": "2000-01-01T00:00:00+00:00", "facts": None})
        await pages.fill(opp)
        self.assertEqual(fetch.call_count, 2)

    async def test_pay_is_filled_only_when_asked_and_never_over_a_stored_one(self):
        opp = self.add(location="San Francisco, CA")  # nothing else missing
        pay = {"min": 62, "max": 72, "currency": "USD", "period": "hr"}
        fetch = mock.Mock(return_value={"location": "Elsewhere", "pay": pay})
        pages = pf.PageFacts(self.store, fetch=fetch)
        self.assertEqual(await pages.fill(opp), {})        # not asked for pay: no fetch at all
        fetch.assert_not_called()
        self.assertEqual(await pages.fill(opp, pay=True), {"pay": "$62–$72/hr"})
        stored = self.store.get_opportunity(opp)
        self.assertEqual((stored["fields"]["Pay"], stored["location"]), ("$62–$72/hr", "San Francisco, CA"))
        self.assertEqual(await pages.fill(opp, pay=True), {})  # has pay now: left alone
        self.assertEqual(fetch.call_count, 1)

    async def test_a_page_read_before_pay_existed_is_read_again_once(self):
        opp = self.add(location="San Francisco, CA")
        url = "https://jobs.ashbyhq.com/b/1"
        self.store.set_enrichment(f"page:{url}", {"t": datetime.now(timezone.utc).isoformat(), "facts": {"location": "x"}})
        fetch = mock.Mock(return_value={"pay": {"min": 20, "max": 24, "currency": "USD", "period": "hr"}})
        pages = pf.PageFacts(self.store, fetch=fetch)
        self.assertEqual(await pages.fill(opp, pay=True), {"pay": "$20–$24/hr"})
        self.assertEqual(self.store.get_enrichment(f"page:{url}")["pv"], pf.PAY_VERSION)

    async def test_a_new_drop_waits_for_no_page_just_for_its_pay(self):
        sent = []
        class Alerter:
            async def dispatch(self, item, opp_id):
                sent.append(self.store.get_opportunity(opp_id)["fields"].get("Pay"))
            async def retry_pending(self):
                pass
        alerter = Alerter()
        alerter.store = self.store
        pages = pf.PageFacts(self.store, fetch=lambda url: {"pay": {"min": 20, "max": 24, "currency": "USD", "period": "hr"}})
        pipe = Pipeline(self.store, alerter=alerter, pagefacts=pages, enricher=SimpleNamespace(enrich=mock.AsyncMock()))
        drop = Item(source="ats.ashby.b", external_id="d1", url="https://jobs.ashbyhq.com/b/d1", title="Intern", company="Bedrock",
                    location="Austin, TX", seen_at=self.when, published_at=self.when)
        await pipe(SimpleNamespace(name="ats.ashby.b"), [drop])
        self.assertEqual(sent, [None])                        # the push did not wait for the page
        await asyncio.gather(*list(pipe._background))
        stored = self.store.get_opportunity(self.store.item_opportunity_id("ats.ashby.b", "d1"))
        self.assertEqual(stored["fields"]["Pay"], "$20–$24/hr")

    async def test_a_fine_posting_is_never_fetched(self):
        opp = self.add(location="San Francisco, CA")
        fetch = mock.Mock()
        self.assertEqual(await pf.PageFacts(self.store, fetch=fetch).fill(opp), {})
        fetch.assert_not_called()

    async def test_a_new_drop_gets_its_location_before_the_alert_and_a_seed_in_the_background(self):
        sent = []
        class Alerter:
            async def dispatch(self, item, opp_id):
                sent.append(self.store.get_opportunity(opp_id)["location"])
            async def retry_pending(self):
                pass
        alerter = Alerter()
        alerter.store = self.store
        pages = pf.PageFacts(self.store, fetch=lambda url: {"location": "San Francisco, California"})
        pipe = Pipeline(self.store, alerter=alerter, pagefacts=pages, enricher=SimpleNamespace(enrich=mock.AsyncMock()))
        drop = Item(source="ats.ashby.b", external_id="d1", url="https://jobs.ashbyhq.com/b/d1", title="Intern", company="Bedrock",
                    location="", seen_at=self.when, published_at=self.when)
        seed = Item(source="ats.ashby.b", external_id="s1", url="https://jobs.ashbyhq.com/b/s1", title="Intern", company="Bedrock",
                    location="3 locations", seen_at=self.when, published_at=self.when, raw={"seed": True})
        await pipe(SimpleNamespace(name="ats.ashby.b"), [drop, seed])
        self.assertEqual(sent, ["San Francisco, California"])  # filled before the push went out
        await asyncio.gather(*list(pipe._background))
        seeded = self.store.get_opportunity(self.store.item_opportunity_id("ats.ashby.b", "s1"))
        self.assertEqual(seeded["location"], "San Francisco, California")


if __name__ == "__main__":
    unittest.main()
