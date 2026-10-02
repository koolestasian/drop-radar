import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from radar.models import Item
from radar.stats import format_latency_table, latency_by_source
from radar.store import Store

T0 = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)


class LatencyBySourceTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(self.store.close)

    def _sent(self, source, external_id, latency):
        opp_id, _ = self.store.upsert_item(Item(source=source, external_id=external_id,
                                                  url=f"https://x.example/{external_id}", title="t", seen_at=T0))
        self.store.record_alert(opp_id, "ntfy")
        self.store.mark_alert_sent(opp_id, "ntfy", T0 + timedelta(seconds=latency), latency)
        return opp_id

    def test_empty_store_has_no_latencies(self):
        self.assertEqual(latency_by_source(self.store), {})
        self.assertEqual(format_latency_table({}), "No alerts sent yet.")

    def test_groups_and_computes_percentiles_per_source(self):
        for latency in (10, 20, 30, 40, 100):
            self._sent("ats.greenhouse.stripe", f"job-{latency}", latency)
        self._sent("instagram.zero2sudo", "media:1", 5)

        by_source = latency_by_source(self.store)
        self.assertEqual(set(by_source), {"ats.greenhouse.stripe", "instagram.zero2sudo"})
        stripe = by_source["ats.greenhouse.stripe"]
        self.assertEqual(stripe["n"], 5)
        self.assertEqual(stripe["p50"], 30)
        self.assertEqual(stripe["p95"], 100)
        self.assertIn("ats.greenhouse.stripe", format_latency_table(by_source))

    def test_pending_alert_is_excluded(self):
        opp_id, _ = self.store.upsert_item(Item(source="ats.a", external_id="1", url="https://x.example/1",
                                                  title="t", seen_at=T0))
        self.store.record_alert(opp_id, "ntfy")  # claimed, never sent
        self.assertEqual(latency_by_source(self.store), {})

    def test_a_shared_source_does_not_mix_the_friends_delivery_time_into_mine(self):
        opp_id = self._sent("ats.greenhouse.stripe", "shared", 30)
        self.store.record_alert(opp_id, "ntfy:friend")
        self.store.mark_alert_sent(opp_id, "ntfy:friend", T0 + timedelta(seconds=90), 90)
        self.assertEqual(latency_by_source(self.store, channel="ntfy")["ats.greenhouse.stripe"]["p50"], 30)
        self.assertEqual(latency_by_source(self.store, channel="ntfy:friend")["ats.greenhouse.stripe"]["p50"], 90)


if __name__ == "__main__":
    unittest.main()
