import asyncio
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from radar.api.runtime import Runtime
from radar.config import Company
from radar.models import Item, utcnow
from radar.pipeline import priority
from radar.pipeline.enrich import _today
from radar.sources.ats import AtsSource
from radar.store import Store


def jev(tier="S", confidence=0.9):
    def post(payload, key):
        return {"answers": {qid: {"confidence": confidence, "probabilities": {
            str(i): float(t == tier) for i, t in enumerate(priority.LEVELS)}} for qid in payload["state"]}}
    return post


def ask(prompt, web):
    return ("TIER: S", 150, ["https://example.com/company"]) if web else ("S", 10, [])


class PriorityTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(self.store.close)
        priority._warned = set()

    def refresh(self, **kw):
        return priority.refresh(self.store, ["Acme"], key="test", post=jev(), ask=ask, **kw)

    def test_agreement_cached_and_charged(self):
        calls = []
        def agreed(prompt, web):
            calls.append(web)
            return ask(prompt, web)
        self.assertEqual(priority.refresh(self.store, ["Acme"], key="test", post=jev(), ask=agreed), {"Acme": "S"})
        self.assertEqual(calls, [False])
        cached = self.store.get_enrichment(priority.cache_key("Acme"))
        self.assertEqual(cached["source"], "jev+haiku")
        self.assertEqual(cached["haiku_model"], priority.HAIKU)
        self.assertEqual(self.store.get_enrichment(f"llm_budget:{_today()}")["tokens"], 10)
        self.assertEqual(priority.stale(self.store, ["Acme"]), [])

    def test_disagreement_or_low_confidence_uses_web(self):
        for post in (jev("C"), jev("S", 0.3)):
            calls = []
            def search(prompt, web):
                calls.append(web)
                return ask(prompt, web)
            rated = priority.rate(["Acme"], key="test", post=post, ask=search)
            self.assertEqual(rated["Acme"]["source"], "haiku+web")
            self.assertEqual(calls, [False, True])

    def test_web_requires_cited_evidence_and_strict_final_line(self):
        for response in ("S", "TIER: Sorry", "TIER: S extra"):
            self.assertIsNone(priority.haiku_rate("Acme", web=True, ask=lambda *_: (response, 1, ["https://x.example"])))
        self.assertIsNone(priority.haiku_rate("Acme", web=True, ask=lambda *_: ("TIER: S", 1, [])))
        self.assertIsNone(priority.haiku_rate("Acme", ask=lambda *_: ("Sorry", 1, [])))

    def test_malformed_jev_fails_open_per_company(self):
        def malformed(payload, key):
            answers = jev()(payload, key)["answers"]
            answers["c0"]["probabilities"]["0"] = float("nan")
            return {"answers": answers}
        self.assertEqual(priority.jev_rate(["Bad", "Good"], key="test", post=malformed), {"Good": ("S", 0.9)})
        self.assertEqual(priority.jev_rate(["Acme"], key=""), {})

    def test_failure_keeps_existing_rating(self):
        existing = {"tier": "A", "checked_at": "2020-01-01T00:00:00+00:00"}
        self.store.set_enrichment(priority.cache_key("Acme"), existing)
        def fail(*_):
            raise ConnectionError("unavailable")
        self.assertEqual(priority.refresh(self.store, ["Acme"], key="test", post=fail, ask=fail), {})
        self.assertEqual(self.store.get_enrichment(priority.cache_key("Acme")), existing)

    def test_failed_companies_wait_a_day_without_starving_new_names(self):
        def fail(*_):
            return "", 0, []
        priority.refresh(self.store, ["Acme"], key="", ask=fail)
        self.assertEqual(priority.stale(self.store, ["Acme", "New"]), ["New"])
        self.assertEqual(priority.stale(self.store, ["Acme", "New"], utcnow() + timedelta(days=2)), ["New", "Acme"])

    def test_old_rubric_is_refreshed_even_if_recent(self):
        self.store.set_enrichment(priority.cache_key("Google"), {"tier": "A", "checked_at": utcnow().isoformat()})
        self.assertEqual(priority.stale(self.store, ["Google"]), ["Google"])

    def test_dry_run_writes_nothing(self):
        self.assertEqual(self.refresh(dry_run=True), {"Acme": "S"})
        self.assertIsNone(self.store.get_enrichment(priority.cache_key("Acme")))
        self.assertIsNone(self.store.get_enrichment(f"llm_budget:{_today()}"))

    def test_exhausted_shared_budget_makes_no_requests(self):
        self.store.set_enrichment(f"llm_budget:{_today()}", {"tokens": priority.DEFAULT_DAILY_TOKEN_BUDGET})
        with patch.object(priority, "rate") as rate:
            self.assertEqual(self.refresh(), {})
            rate.assert_not_called()

    def test_no_allowance_for_web_skips_request(self):
        calls = []
        meter = priority._Meter(4096, lambda *args: calls.append(args))
        self.assertEqual(meter("company", True), ("", 0, []))
        self.assertEqual(calls, [])

    def test_stale_deduplicates_aliases_and_retries_invalid_cache(self):
        now = utcnow()
        self.store.set_enrichment(priority.cache_key("Acme"), {"tier": "S", "checked_at": (now - timedelta(days=31)).isoformat()})
        self.store.set_enrichment(priority.cache_key("Beta"), {"tier": "Q", "checked_at": now.isoformat()})
        self.assertEqual(priority.stale(self.store, ["Acme", "acme", "Beta", "New"], now), ["New", "Acme", "Beta"])

    def test_only_company_names_leave_the_machine(self):
        self.store.upsert_item(Item(source="s", external_id="1", url="https://a/1", title="Intern", company="Acme"))
        self.store.set_action(self.store.item_opportunity_id("s", "1"), "kevin", status="Applied", notes="secret")
        calls = []
        def post(payload, key):
            calls.append(payload)
            return jev()(payload, key)
        priority.refresh(self.store, ["Acme"], key="test", post=post, ask=ask)
        self.assertEqual(calls[0]["state"], {"c0": "Acme"})
        self.assertNotIn("secret", str(calls))

    def test_actions_personalize_ranks_without_changing_company_tier(self):
        self.store.upsert_item(Item(source="s", external_id="1", url="https://a/1", title="Intern", company="Acme"))
        self.store.set_action(self.store.item_opportunity_id("s", "1"), "kevin", status="Applied")
        self.store.set_enrichment(priority.cache_key("Acme"), {"tier": "C"})
        self.assertEqual(priority.learned_ranks(self.store, "kevin")["acme"], 2)
        self.assertEqual(priority.learned_ranks(self.store, "other")["acme"], 0)
        self.assertEqual(priority.tier_of(self.store, "Acme"), "C")

    def test_runtime_applies_cached_poll_intervals(self):
        source = AtsSource(Company("Acme", "greenhouse", "acme"))
        runtime = SimpleNamespace(store=self.store, scheduler=SimpleNamespace(sources={source.name: source}))
        for tier, interval in priority.TIER_INTERVAL_S.items():
            self.store.set_enrichment(priority.cache_key("Acme"), {"tier": tier})
            Runtime.apply_tiers(runtime)
            self.assertEqual(source.interval_s, interval)

    def test_background_network_runs_off_thread_but_store_stays_on_owner_thread(self):
        self.store.upsert_item(Item(source="s", external_id="1", url="https://a/1", title="Intern", company="Acme"))
        async def check():
            stop = asyncio.Event()
            with patch.object(priority, "rate", return_value={"Acme": {"tier": "S", "source": "test"}}):
                await priority.run(self.store, lambda: [], stop, on_rated=stop.set)
            self.assertEqual(priority.tier_of(self.store, "Acme"), "S")
        asyncio.run(asyncio.wait_for(check(), timeout=2))
