import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from radar.pipeline.enrich import _today
from radar.pipeline.pay_llm import PayLLM, verified
from radar.pipeline.pagefacts import PageFacts
from radar.store import Store
from radar.models import Item
from datetime import datetime, timezone

TEXT = "The annual base salary in USD has a minimum of 120,000 and a maximum of 150,000."
RESULT = {"min": 120000, "max": 150000, "currency": "USD", "period": "yr", "evidence": TEXT}


class EvidenceTests(unittest.TestCase):
    def test_haiku_request_uses_schema_without_effort(self):
        from types import SimpleNamespace
        reply = SimpleNamespace(usage=SimpleNamespace(input_tokens=80, output_tokens=40), stop_reason="end_turn",
                                content=[SimpleNamespace(type="text", text=__import__("json").dumps(RESULT))])
        client = mock.Mock()
        client.messages.create.return_value = reply
        with mock.patch("anthropic.Anthropic", return_value=client):
            data, tokens, model = PayLLM(None)._ask(TEXT)
        self.assertEqual((data, tokens, model), (RESULT, 120, "claude-haiku-4-5"))
        params = client.messages.create.call_args.kwargs
        self.assertNotIn("effort", params)
        self.assertEqual(params["max_tokens"], 500)
        self.assertIn("json_schema", str(params["output_config"]))

    def test_non_regex_range_is_grounded(self):
        from radar.pipeline.pay import pay_from_text
        self.assertIsNone(pay_from_text(TEXT))
        self.assertEqual(verified(RESULT, TEXT)["max"], 150000)

    def test_invented_amount_currency_period_and_quote_are_rejected(self):
        for patch in ({"max": 160000}, {"currency": "GBP"}, {"period": "hr"}, {"evidence": "invented"}):
            with self.subTest(patch=patch):
                self.assertIsNone(verified({**RESULT, **patch}, TEXT))
        cad = TEXT.replace("USD", "CAD")
        self.assertIsNone(verified({**RESULT, "evidence": cad}, cad))

    def test_non_base_pay_is_rejected(self):
        for word in ("bonus", "equity", "stipend", "estimated", "scholarship", "total compensation"):
            text = TEXT.replace("base salary", word + " pay")
            self.assertIsNone(verified({**RESULT, "evidence": text}, text), word)


class PayFallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(Path(self.tmp.name) / "radar.db")
        self.addCleanup(self.store.close)
        self.ask = mock.Mock(return_value=(RESULT, 123, "claude-haiku-4-5"))
        self.llm = PayLLM(self.store, ask=self.ask)

    async def test_cache_deduplicates_concurrent_calls_and_shares_story_budget(self):
        key = f"llm_budget:{_today()}"
        self.store.set_enrichment(key, {"tokens": 500})
        results = await asyncio.gather(self.llm.extract(TEXT), self.llm.extract(TEXT))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.ask.call_count, 1)
        self.assertEqual(self.store.get_enrichment(key)["tokens"], 623)
        await self.llm.extract(TEXT + " Updated.")
        self.assertEqual(self.ask.call_count, 2)

    async def test_budget_and_dry_run_do_not_call_or_write(self):
        self.llm.budget = 1
        self.assertIsNone(await self.llm.extract(TEXT))
        self.llm.budget = 200000
        self.assertIsNone(await self.llm.extract(TEXT, dry_run=True))
        self.ask.assert_not_called()
        self.assertIsNone(self.store.get_enrichment(f"llm_budget:{_today()}"))

    async def test_unknown_is_cached_failures_retry(self):
        self.ask.return_value = ({**RESULT, "min": 0, "max": 0, "evidence": ""}, 20, "haiku")
        await self.llm.extract(TEXT)
        await self.llm.extract(TEXT)
        self.assertEqual(self.ask.call_count, 1)
        self.ask.return_value = (None, 0, "haiku")
        await self.llm.extract(TEXT + " changed")
        await self.llm.extract(TEXT + " changed")
        self.assertEqual(self.ask.call_count, 3)

    async def test_page_fills_blanks_and_preserves_concurrent_notes_and_pay(self):
        opp, _ = self.store.upsert_item(Item(source="ats.test", external_id="a", title="Intern",
                                           company="Test", location="Austin, TX", url="https://example.org/job",
                                           seen_at=datetime.now(timezone.utc)))
        fallback = mock.Mock()
        fallback.extract = mock.AsyncMock(return_value=verified(RESULT, TEXT))
        pages = PageFacts(self.store, fetch=lambda url: {"description": TEXT}, pay_llm=fallback)
        self.assertEqual(await pages.fill(opp, pay=True), {"pay": "$120,000–$150,000/yr"})
        fallback.extract.assert_awaited_once()
        self.store.save_opportunity(opp, first_seen=self.store.get_opportunity(opp)["first_seen"], fields={"Notes": "keep"})
        async def race(*args, **kwargs):
            self.store.save_opportunity(opp, first_seen=self.store.get_opportunity(opp)["first_seen"], fields={"Pay": "$30–$40/hr", "Notes": "new note"})
            return verified(RESULT, TEXT)
        fallback.extract.side_effect = race
        self.assertEqual(await pages.fill(opp, pay=True), {})
        self.assertEqual(self.store.get_opportunity(opp)["fields"], {"Pay": "$30–$40/hr", "Notes": "new note"})

    async def test_missing_location_is_filled_before_alert_without_waiting_for_model(self):
        from types import SimpleNamespace
        from radar.pipeline import Pipeline
        gate = asyncio.Event()
        async def slow_model(*args, **kwargs):
            await gate.wait()
            return verified(RESULT, TEXT)
        fallback = SimpleNamespace(extract=slow_model)
        pages = PageFacts(self.store, fetch=lambda url: {"location": "Austin, TX", "description": TEXT}, pay_llm=fallback)
        sent = []
        async def dispatch(item, opp_id):
            row = self.store.get_opportunity(opp_id)
            sent.append((row["location"], row["fields"].get("Pay")))
        pipe = Pipeline(self.store, pagefacts=pages,
                        alerter=SimpleNamespace(dispatch=dispatch, retry_pending=mock.AsyncMock()),
                        enricher=SimpleNamespace(enrich=mock.AsyncMock()))
        item = Item(source="ats.test", external_id="new", title="Intern", company="Test",
                    url="https://example.org/new", seen_at=datetime.now(timezone.utc))
        await asyncio.wait_for(pipe(SimpleNamespace(name="ats.test"), [item]), 1)
        self.assertEqual(sent, [("Austin, TX", None)])
        gate.set()
        await asyncio.gather(*pipe._background)
        opp = self.store.item_opportunity_id("ats.test", "new")
        self.assertEqual(self.store.get_opportunity(opp)["fields"]["Pay"], "$120,000–$150,000/yr")

    async def test_structured_pay_skips_model(self):
        opp, _ = self.store.upsert_item(Item(source="ats.test", external_id="b", title="Intern",
                                           company="Test", location="Austin, TX", url="https://example.org/b",
                                           seen_at=datetime.now(timezone.utc)))
        fallback = mock.Mock(extract=mock.AsyncMock())
        pages = PageFacts(self.store, fetch=lambda url: {"pay": verified(RESULT, TEXT)}, pay_llm=fallback)
        await pages.fill(opp, pay=True)
        fallback.extract.assert_not_called()
