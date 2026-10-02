import json
import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from radar.legacy import job_pages
from radar.legacy import llm_extraction
from radar.legacy import opportunity_monitor as monitor


class FakeResponse:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text if payload is None else json.dumps(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, routes):
        self.routes = routes
        self.requested = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        for prefix, response in self.routes.items():
            if url.startswith(prefix):
                return response
        return FakeResponse(404, text="missing")


class JobPageTests(unittest.TestCase):
    def setUp(self):
        job_pages._ashby_boards.clear()

    def facts(self, url, routes):
        return job_pages.fetch_job_facts(url, FakeSession(routes))

    def test_greenhouse_open_and_closed(self):
        api = "https://boards-api.greenhouse.io/v1/boards/amca/jobs/"
        facts = self.facts("https://job-boards.greenhouse.io/amca/jobs/4425120009", {
            api + "4425120009": FakeResponse(payload={
                "title": "Software Engineer Intern", "location": {"name": "Austin, TX"},
                "company_name": "AMCA", "content": "&lt;p&gt;Build things&lt;/p&gt;",
            }),
        })
        self.assertEqual(facts["status"], "open")
        self.assertEqual(facts["title"], "Software Engineer Intern")
        self.assertEqual(facts["location"], "Austin, TX")
        self.assertEqual(facts["description"], "Build things")
        closed = self.facts("https://job-boards.greenhouse.io/amca/jobs/1", {api + "1": FakeResponse(404)})
        self.assertEqual(closed["status"], "closed")

    def test_greenhouse_embed_links(self):
        session = FakeSession({"https://boards-api.greenhouse.io/v1/boards/doordashusa/jobs/7848317":
                               FakeResponse(payload={"title": "ML Fellow"})})
        facts = job_pages.fetch_job_facts(
            "https://job-boards.greenhouse.io/embed/job_app?for=doordashusa&token=7848317", session)
        self.assertEqual(facts["title"], "ML Fellow")

    def test_lever_and_smartrecruiters(self):
        lever = self.facts("https://jobs.lever.co/palantir/ef725594-42dd-4f0d-ba8e-df8179dbc6cb", {
            "https://api.lever.co/v0/postings/palantir/": FakeResponse(payload={
                "text": "Software Engineer, Internship", "categories": {"location": "New York, NY"},
            }),
        })
        self.assertEqual((lever["status"], lever["location"]), ("open", "New York, NY"))
        inactive = self.facts("https://jobs.smartrecruiters.com/Wise/744000151030889-graduate-software-engineer", {
            "https://api.smartrecruiters.com/v1/companies/Wise/postings/744000151030889":
                FakeResponse(payload={"name": "Graduate Software Engineer", "active": False,
                                      "company": {"name": "Wise"}}),
        })
        self.assertEqual(inactive["status"], "closed")

    def test_ashby_missing_job_is_closed(self):
        routes = {"https://api.ashbyhq.com/posting-api/job-board/ramp": FakeResponse(payload={"jobs": [
            {"id": "aaaaaaaa-0000-0000-0000-000000000000", "title": "SWE Intern", "isListed": True},
        ]})}
        found = self.facts("https://jobs.ashbyhq.com/ramp/aaaaaaaa-0000-0000-0000-000000000000", routes)
        gone = self.facts("https://jobs.ashbyhq.com/ramp/bbbbbbbb-0000-0000-0000-000000000000/application", routes)
        self.assertEqual((found["status"], found["title"]), ("open", "SWE Intern"))
        self.assertEqual(gone["status"], "closed")

    def test_json_ld_page(self):
        page = """<html><script type="application/ld+json">{"@context": "https://schema.org",
            "@graph": [{"@type": "JobPosting", "title": "Software Engineering Intern",
            "hiringOrganization": {"name": "Garmin"}, "validThrough": "2026-10-15T00:00:00",
            "jobLocation": {"address": {"addressLocality": "Olathe", "addressRegion": "KS"}}}]}
            </script></html>"""
        facts = self.facts("https://careers.garmin.com/jobs/20255", {
            "https://careers.garmin.com": FakeResponse(text=page),
        })
        self.assertEqual(facts["status"], "open")
        self.assertEqual(facts["deadline"], "2026-10-15")
        self.assertEqual(facts["location"], "Olathe, KS")
        self.assertEqual(facts["organization"], "Garmin")

    def test_errors_and_og_titles_never_mean_closed(self):
        blocked = self.facts("https://example.com/jobs/1", {"https://example.com": FakeResponse(403, text="no")})
        self.assertEqual(blocked["status"], "unknown")
        og = self.facts("https://example.com/jobs/2", {"https://example.com": FakeResponse(
            text='<meta property="og:title" content="Data Science Intern | Example" />')})
        self.assertEqual((og["status"], og["title"]), ("unknown", "Data Science Intern | Example"))
        gone = self.facts("https://example.com/jobs/3", {"https://example.com": FakeResponse(410)})
        self.assertEqual(gone["status"], "closed")

        class Exploding:
            def get(self, *args, **kwargs):
                raise job_pages.requests.ConnectionError("down")
        self.assertEqual(job_pages.fetch_job_facts("https://example.com/x", Exploding())["status"], "unknown")


class EnrichmentOverlayTests(unittest.TestCase):
    link = "https://job-boards.greenhouse.io/amca/jobs/4425120009"
    text = "AMCA internship applications are open"

    def setUp(self):
        patcher = patch.object(monitor, "ENRICHMENT", {"version": 1, "pages": {}, "llm": {}})
        patcher.start()
        self.addCleanup(patcher.stop)

    def derive(self, reference=date(2026, 9, 20)):
        return monitor.derive_fields(self.text, [self.link], reference, date(2026, 9, 30))

    def test_page_title_location_and_closed_status_win(self):
        monitor.ENRICHMENT["pages"][self.link] = {
            "status": "closed", "title": "Software Engineer Intern | AMCA Careers",
            "location": "Austin, TX",
        }
        fields = self.derive()
        self.assertEqual(fields["Opportunity"], "Amca — Software Engineer Intern")
        self.assertEqual(fields["Location"], "Austin, TX")
        self.assertEqual(fields["Status"], "Closed")

    def test_live_page_marks_new_rows_open(self):
        monitor.ENRICHMENT["pages"][self.link] = {"status": "open", "title": "SWE Intern"}
        self.assertEqual(self.derive()["Status"], "Open")

    def test_default_validthrough_a_year_out_is_ignored(self):
        monitor.ENRICHMENT["pages"][self.link] = {"status": "open", "deadline": "2027-09-28"}
        self.assertEqual(self.derive()["Deadline"], "")
        monitor.ENRICHMENT["pages"][self.link] = {"status": "open", "deadline": "2026-10-15"}
        self.assertEqual(self.derive()["Deadline"], "2026-10-15")

    def test_generic_page_titles_are_ignored(self):
        self.assertEqual(monitor.clean_page_title("Careers at NVIDIA Corporation"), "")
        self.assertEqual(monitor.clean_page_title("Direct Consideration #007"), "")
        self.assertEqual(
            monitor.clean_page_title("Software Engineering Intern in Louisville, Colorado | Garmin International, Inc."),
            "Software Engineering Intern in Louisville, Colorado",
        )
        self.assertEqual(monitor.clean_page_title("Palantir - Software Engineer, New Grad", "Palantir"),
                         "Software Engineer, New Grad")
        self.assertEqual(monitor.clean_page_title("Code for Good", "JPMorgan Chase", require_role_word=False),
                         "Code for Good")

    def test_llm_fields_override_regex(self):
        monitor.ENRICHMENT["llm"][monitor.text_key(self.text)] = {
            "is_opportunity": True, "confidence": 0.9, "organization": "scale ai",
            "title": "Machine Learning Research Intern", "category": "Research",
            "roles": ["Machine Learning / AI"], "season": "Summer 2027",
            "location": "San Francisco, CA", "deadline": "2026-10-20",
        }
        fields = self.derive()
        self.assertEqual(fields["Organization"], "Scale AI")
        self.assertEqual(fields["Opportunity"], "Scale AI — Machine Learning Research Intern")
        self.assertEqual(fields["Category"], "Research")
        self.assertEqual(fields["Deadline"], "2026-10-20")
        self.assertEqual(fields["Priority"], "High")

    def test_confident_non_opportunity_is_marked(self):
        monitor.ENRICHMENT["llm"][monitor.text_key(self.text)] = {
            "is_opportunity": False, "confidence": 0.95, "organization": "", "title": "",
            "category": "", "roles": [], "season": "", "location": "", "deadline": "",
        }
        self.assertEqual(self.derive()["Status"], "Not actionable")

    def test_unknown_check_keeps_earlier_good_facts(self):
        monitor.store_page_facts(self.link, {"status": "open", "title": "SWE Intern", "checked_at": "t1"})
        monitor.store_page_facts(self.link, {"status": "unknown", "error": "HTTP 503", "checked_at": "t2"})
        entry = monitor.ENRICHMENT["pages"][self.link]
        self.assertEqual((entry["status"], entry["title"], entry["checked_at"]), ("open", "SWE Intern", "t2"))
        monitor.store_page_facts(self.link, {"status": "closed", "checked_at": "t3"})
        entry = monitor.ENRICHMENT["pages"][self.link]
        self.assertEqual((entry["status"], entry["title"], entry["closed_at"]), ("closed", "SWE Intern", "t3"))

    def test_refresh_only_rechecks_stale_open_links(self):
        now = datetime.now(timezone.utc)
        monitor.ENRICHMENT["pages"].update({
            "https://a.com/jobs/1": {"status": "open", "checked_at": now.isoformat()},
            "https://b.com/jobs/2": {"status": "open", "checked_at": (now - timedelta(days=2)).isoformat()},
            "https://c.com/jobs/3": {"status": "closed", "checked_at": (now - timedelta(days=9)).isoformat()},
        })
        records = [
            {"Application / Registration Link": url, "Actioned?": "No", "Status": "Open"}
            for url in ("https://a.com/jobs/1", "https://b.com/jobs/2", "https://c.com/jobs/3",
                        "https://d.com/jobs/4")
        ] + [{"Application / Registration Link": "https://e.com/jobs/5", "Actioned?": "Yes"}]
        checked = []

        def fake_fetch(url):
            checked.append(url)
            return {"status": "closed", "checked_at": now.isoformat(), "source": "html"}

        with patch.object(monitor, "JOB_PAGES_ENABLED", True), \
                patch.object(monitor.job_pages, "fetch_job_facts", fake_fetch):
            monitor.refresh_job_pages(records)
        self.assertEqual(sorted(checked), ["https://b.com/jobs/2", "https://d.com/jobs/4"])


class ExtractorTests(unittest.TestCase):
    def fake_client(self, payload=None, stop_reason="end_turn"):
        calls = []
        content = [SimpleNamespace(type="text", text=json.dumps(payload))] if payload is not None else []

        def create(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                stop_reason=stop_reason, content=content,
                usage=SimpleNamespace(input_tokens=1200, output_tokens=90),
            )
        client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
        return client, calls

    def extractor(self, client):
        return llm_extraction.Extractor(["Internship", "Other Opportunity"], ["Software Engineering"], client)

    def test_request_shape_and_validation(self):
        client, calls = self.fake_client({
            "is_opportunity": True, "confidence": 1.4, "organization": "Ramp",
            "title": "Software Engineer Intern", "category": "Made Up", "roles": ["Software Engineering", "Nope"],
            "season": "Summer 2027", "location": "NYC", "deadline": "Oct 15",
        })
        extractor = self.extractor(client)
        facts = extractor.extract("Ramp SWE intern apps open", "https://jobs.ashbyhq.com/ramp/x",
                                  "2026-09-30", {"title": "SWE Intern", "description": "Details"})
        request = calls[0]
        self.assertEqual(request["model"], llm_extraction.MODEL)
        self.assertEqual(request["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", request["betas"])
        self.assertEqual(request["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(request["output_config"]["effort"], "low")
        prompt = request["messages"][0]["content"]
        self.assertIn("<job_page>\nDetails\n</job_page>", prompt)
        self.assertIn('"title": "SWE Intern"', prompt)
        self.assertEqual(facts["confidence"], 1.0)
        self.assertEqual(facts["category"], "")
        self.assertEqual(facts["roles"], ["Software Engineering"])
        self.assertEqual(facts["deadline"], "")
        self.assertEqual(extractor.usage["input_tokens"], 1200)

    def test_refusal_and_bad_json_return_none(self):
        client, _ = self.fake_client(stop_reason="refusal")
        self.assertIsNone(self.extractor(client).extract("text"))
        client, _ = self.fake_client(payload=None)
        self.assertIsNone(self.extractor(client).extract("text"))

    def test_schema_is_strict(self):
        schema = llm_extraction.schema(["A"], ["B"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(schema["properties"]))


class EnrichRowsTests(unittest.TestCase):
    def setUp(self):
        for name, value in (
            ("ENRICHMENT", {"version": 1, "pages": {}, "llm": {}}),
            ("LLM_ENABLED", True),
            ("JOB_PAGES_ENABLED", True),
        ):
            patcher = patch.object(monitor, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_new_rows_get_page_and_llm_fields_and_memes_are_dropped(self):
        job = {"Application / Registration Link": "https://jobs.lever.co/palantir/abc",
               "Raw Text": "palantir swe intern apps open", "Posted At": "2026-09-30"}
        meme = {"Application / Registration Link": "", "Raw Text": "when the intern offer hits apply now lol",
                "Posted At": "2026-09-30"}
        answers = {
            monitor.text_key(job["Raw Text"]): {
                "is_opportunity": True, "confidence": 0.9, "organization": "Palantir",
                "title": "", "category": "Internship", "roles": ["Software Engineering"],
                "season": "Summer 2027", "location": "", "deadline": "",
            },
            monitor.text_key(meme["Raw Text"]): {
                "is_opportunity": False, "confidence": 0.95, "organization": "", "title": "",
                "category": "Other Opportunity", "roles": [], "season": "", "location": "", "deadline": "",
            },
        }
        fake_extractor = SimpleNamespace(
            extract=lambda text, link, posted, page: answers[monitor.text_key(text)], usage={})
        page = {"status": "open", "title": "Software Engineer, Internship", "location": "New York, NY",
                "checked_at": datetime.now(timezone.utc).isoformat(), "source": "lever", "description": "desc"}
        with patch.object(monitor, "extractor", lambda: fake_extractor), \
                patch.object(monitor.job_pages, "fetch_job_facts", lambda url: dict(page)):
            kept = monitor.enrich_rows([dict(job), dict(meme)])
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["Opportunity"], "Palantir — Software Engineer, Internship")
        self.assertEqual(kept[0]["Location"], "New York, NY")
        self.assertEqual(kept[0]["Status"], "Open")
        self.assertEqual(kept[0]["Priority"], "High")
        self.assertNotIn("description", monitor.ENRICHMENT["pages"]["https://jobs.lever.co/palantir/abc"])


class PriorityMatchingTests(unittest.TestCase):
    def test_company_name_variants(self):
        self.assertEqual(monitor.priority_for({"Organization": "Palantir Technologies"}), "HIGH")
        self.assertEqual(monitor.priority_for({"Organization": "ScaleAI"}), "HIGH")
        self.assertEqual(monitor.priority_for({"Organization": "Primerica"}), "NORMAL")


if __name__ == "__main__":
    unittest.main()
