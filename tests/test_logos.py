import tempfile
import unittest
from pathlib import Path

from datetime import datetime, timedelta, timezone

from radar.logos import LogoResolver, name_is_domain, name_on_page, pick, registrable
from radar.store import Store


class PickTests(unittest.TestCase):
    def test_only_a_confident_name_match_gets_a_domain(self):
        self.assertEqual(pick("Stripe", [{"name": "Stripe", "domain": "stripe.com"}]), "stripe.com")
        self.assertEqual(pick("The Walt Disney Company", [{"name": "Walt Disney", "domain": "disney.com"}]), "disney.com")
        # a country site for the exact name loses to the global "Anduril Industries"
        self.assertEqual(pick("Anduril", [{"name": "Anduril Industries", "domain": "anduril.com"},
                                          {"name": "Anduril", "domain": "andurilgroup.co.za"}]), "anduril.com")
        # a different company that merely starts the same never matches
        self.assertIsNone(pick("Revel", [{"name": "RevelDigital", "domain": "reveldigital.com"}]))
        self.assertIsNone(pick("Fab2", [{"name": "Fabletics", "domain": "fabletics.com"}]))
        self.assertEqual(pick("Booz Allen", []), "boozallen.com")  # hand-checked override


class ResolverCacheTests(unittest.TestCase):
    def test_a_miss_is_queued_once_resolved_it_is_answered(self):
        store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(store.close)
        logos = LogoResolver(store)
        self.assertIsNone(logos.domain("Stripe"))
        self.assertEqual(logos.pending, {"Stripe"})
        store.set_enrichment("logo:stripe", {"domain": "stripe.com"})
        self.assertEqual(logos.domain("Stripe, Inc."), "stripe.com")


class LadderTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(self.store.close)
        self.logos = LogoResolver(self.store)
        self.sites = {}  # domain -> page title
        self.logos._title = lambda domain: self.sites.get(domain)
        self.logos._site_hint = lambda name, row: None
        self.logos._wikidata = lambda name, row: None
        self.logos._clearbit = lambda name, row: None
        self.logos._llm = lambda name, row: None

    def run_one(self, name):
        import asyncio
        result = asyncio.run(self.logos.resolve(name))
        self.assertEqual(result.pop("v"), 2)
        return result

    def test_name_on_page_needs_the_company_not_a_stranger(self):
        self.assertTrue(name_on_page("TD Bank", "TD Bank | Personal & Business Banking"))
        self.assertTrue(name_on_page("Hudson River Trading", "HRT - Hudson River Trading"))
        self.assertFalse(name_on_page("TD Bank", "Sosonko - hosting"))
        self.assertFalse(name_on_page("", "anything"))
        # whole words only: a short name never matches inside a longer word
        self.assertFalse(name_on_page("ABB", "AbbVie | Pharmaceutical Research"))
        self.assertFalse(name_on_page("EA", "Eater: Food News"))
        self.assertTrue(name_on_page("Dick's Sporting Goods", "DICK'S Sporting Goods - Official Site"))

    def test_name_is_domain_only_on_a_commercial_ending(self):
        self.assertTrue(name_is_domain("Rocket Lab USA", "rocketlabusa.com"))
        self.assertTrue(name_is_domain("KLA Corporation", "kla.com"))
        self.assertFalse(name_is_domain("DTCC", "dtcc.edu"))
        self.assertFalse(name_is_domain("Swib", "swib.org"))
        self.assertFalse(name_is_domain("Arc", "archive.org"))

    def test_registrable_strips_www_and_paths(self):
        self.assertEqual(registrable("https://www.careers.quora.com/jobs"), "quora.com")
        self.assertEqual(registrable("http://www.bbc.co.uk/x"), "bbc.co.uk")
        self.assertIsNone(registrable("https://www.linkedin.com/company/x"))  # a social/ATS host is not the company
        self.assertIsNone(registrable("https://boards.greenhouse.io/x"))

    def test_first_verified_rung_wins_and_records_where_it_came_from(self):
        self.logos._site_hint = lambda name, row: "muonspace.com"
        self.logos._wikidata = lambda name, row: "wrong.com"
        self.sites["muonspace.com"] = "Muon Space - satellites"
        self.assertEqual(self.run_one("Muon Space"), {"domain": "muonspace.com", "source": "posting", "verified": True})

    def test_a_candidate_whose_homepage_names_someone_else_is_rejected(self):
        self.logos._wikidata = lambda name, row: "arch.jp"
        self.sites["arch.jp"] = "Arch Inc. Japan"
        self.logos._clearbit = lambda name, row: "archinsurance.com"
        self.sites["archinsurance.com"] = "Arch Capital Group"
        self.assertIsNone(self.run_one("Arch Robotics")["domain"])

    def test_a_real_source_domain_that_is_the_name_needs_no_homepage(self):
        self.logos._clearbit = lambda name, row: "rocketlabusa.com"      # homepage unreadable
        self.assertEqual(self.run_one("Rocket Lab USA"),
                         {"domain": "rocketlabusa.com", "source": "clearbit", "verified": True})

    def test_an_llm_guess_must_show_its_homepage_even_when_it_is_the_name(self):
        self.logos._llm = lambda name, row: "capstoneinvestmentadvisors.com"   # invented: no such site
        self.assertIsNone(self.run_one("Capstone Investment Advisors")["domain"])
        self.logos._llm = lambda name, row: "k2space.com"
        self.sites["k2space.com"] = "High-Power Satellite Platforms | K2 Space"
        self.assertEqual(self.run_one("K2 Space"), {"domain": "k2space.com", "source": "llm", "verified": True})

    def test_an_answer_on_a_job_board_host_is_never_the_company(self):
        self.logos._clearbit = lambda name, row: "ashbyhq.com"
        self.assertIsNone(self.run_one("Ashbyhq")["domain"])

    def test_unreachable_homepage_trusts_only_the_name_matched_clearbit_answer(self):
        self.logos._wikidata = lambda name, row: "kla-tencor.com"   # homepage 403s: no title to check
        self.assertIsNone(self.run_one("KLA")["domain"])
        self.logos._clearbit = lambda name, row: "kla-tencor.com"
        self.assertEqual(self.run_one("KLA"), {"domain": "kla-tencor.com", "source": "clearbit", "verified": False})

    def test_wikidata_429_backs_off_instead_of_retrying_every_name(self):
        import httpx
        from unittest import mock
        calls = []
        def fake_get(*a, **k):
            calls.append(1)
            return httpx.Response(429, request=httpx.Request("GET", "http://x"))
        real = LogoResolver(self.store)
        with mock.patch("radar.logos.httpx.get", fake_get):
            self.assertIsNone(real._wikidata("A", None))
            self.assertIsNone(real._wikidata("B", None))
        self.assertEqual(len(calls), 1)

    def test_llm_rung_asks_haiku_first_and_gemini_only_if_haiku_fails(self):
        real = LogoResolver(self.store)
        real._posting = lambda name: None
        asked = []
        def haiku(prompt, schema):
            asked.append("haiku"); raise RuntimeError("overloaded")
        def gemini(prompt, schema):
            asked.append("gemini"); return {"domain": "https://www.erieinsurance.com/"}
        real._ask_haiku, real._ask_gemini = haiku, gemini
        self.assertEqual(real._llm("Erie Insurance Group", None), "erieinsurance.com")
        self.assertEqual(asked, ["haiku", "gemini"])
        real._ask_haiku = lambda p, s: {"domain": None}  # a confident "not sure" is final, no second opinion
        asked.clear()
        self.assertIsNone(real._llm("Acme", None))
        self.assertEqual(asked, [])

    def test_posting_is_read_on_the_loop_thread_and_a_crashed_rung_is_not_cached_as_a_miss(self):
        import asyncio, threading
        seen = []
        self.logos._posting = lambda name: seen.append(threading.current_thread() is threading.main_thread()) or ("https://x.com/job", "Intern")
        def boom(name, row):
            raise RuntimeError("down")
        self.logos._site_hint = boom
        result = self.run_one("Acme")
        self.assertEqual(seen, [True])
        self.assertTrue(result["failed"])
        stop = asyncio.Event()
        async def drain():
            self.logos.pending = {"Acme"}
            self.logos.pause_s = 0
            task = asyncio.create_task(self.logos.run(stop))
            while self.logos.pending:
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.05); stop.set(); await task
        asyncio.run(drain())
        self.assertIsNone(self.store.get_enrichment("logo:acme"))  # not cached: asked again next time

    def test_a_miss_from_an_older_ladder_is_retried(self):
        now = datetime.now(timezone.utc).isoformat()
        self.store.set_enrichment("logo:acme", {"domain": None, "checked_at": now})  # v1: written by the buggy deploy
        self.assertIsNone(self.logos.domain("Acme"))
        self.assertEqual(self.logos.pending, {"Acme"})

    def test_a_miss_is_retried_after_a_week_not_never(self):
        now = datetime.now(timezone.utc)
        self.store.set_enrichment("logo:acme", {"domain": None, "v": 2, "checked_at": (now - timedelta(days=1)).isoformat()})
        self.assertIsNone(self.logos.domain("Acme"))
        self.assertEqual(self.logos.pending, set())
        self.store.set_enrichment("logo:acme", {"domain": None, "v": 2, "checked_at": (now - timedelta(days=8)).isoformat()})
        self.assertIsNone(self.logos.domain("Acme"))
        self.assertEqual(self.logos.pending, {"Acme"})

    def test_old_cache_misses_without_a_date_are_retried_old_hits_are_kept(self):
        self.store.set_enrichment("logo:acme", {"domain": None})
        self.store.set_enrichment("logo:stripe", {"domain": "stripe.com"})
        self.assertIsNone(self.logos.domain("Acme"))
        self.assertEqual(self.logos.domain("Stripe"), "stripe.com")
        self.assertEqual(self.logos.pending, {"Acme"})


if __name__ == "__main__":
    unittest.main()
