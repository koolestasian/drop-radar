import asyncio
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from radar.alerts import ZERO2SUDO_SOURCE, AlertDispatcher, should_alert
from radar.config import Profile
from radar.models import Item, utcnow
from radar.store import Store

T0 = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
PROFILE = Profile(roles=("software engineer intern",), locations=("Remote",), keywords=("intern",))


def item(source="ats.greenhouse.stripe", external_id="1", **kw):
    return Item(source=source, external_id=external_id, url=kw.pop("url", "https://x.example/1"),
                title=kw.pop("title", "Software Engineer Intern"), seen_at=kw.pop("seen_at", T0), **kw)


class FakeChannel:
    def __init__(self, name="ntfy", fail_times=0, delay_s=0.0):
        self.name = name
        self.fail_times = fail_times
        self.delay_s = delay_s
        self.sent = []  # [(opp, reasons, drop_latency_s)]

    def send(self, opp, reasons, drop_latency_s):
        if self.delay_s:
            time.sleep(self.delay_s)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("channel unavailable")
        self.sent.append((opp, reasons, drop_latency_s))


class ShouldAlertTests(unittest.TestCase):
    def test_instagram_source_always_alerts_regardless_of_profile(self):
        opp = {"title": "Random unrelated post", "company": "", "location": "", "fields": {}}
        ok, reasons = should_alert(ZERO2SUDO_SOURCE, opp, PROFILE)
        self.assertTrue(ok)
        self.assertIn("insider", reasons[0])

    def test_other_instagram_accounts_are_not_the_insider_source(self):
        opp = {"title": "Random unrelated post", "company": "", "location": "", "fields": {}}
        ok, _ = should_alert("instagram.some_other_account", opp, PROFILE)
        self.assertFalse(ok)

    def test_non_instagram_source_defers_to_matches_profile(self):
        opp = {"title": "Marketing Manager", "company": "", "location": "Remote", "fields": {}}
        ok, _ = should_alert("ats.greenhouse.stripe", opp, PROFILE)
        self.assertFalse(ok)


class AlertDispatcherTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(self.store.close)

    async def test_no_channels_configured_is_a_safe_no_op(self):
        dispatcher = AlertDispatcher(self.store, profile=PROFILE, channels=[])
        opp_id, _ = self.store.upsert_item(item())
        await dispatcher.dispatch(item(), opp_id)  # must not raise
        self.assertIsNone(self.store.get_alert(opp_id, "ntfy"))

    async def test_matching_item_alerts_once_and_stores_latency(self):
        channel = FakeChannel()
        dispatcher = AlertDispatcher(self.store, profile=PROFILE, channels=[channel])
        published = utcnow() - timedelta(seconds=30)
        it = item(published_at=published, seen_at=published)
        opp_id, _ = self.store.upsert_item(it)
        await dispatcher.dispatch(it, opp_id)
        self.assertEqual(len(channel.sent), 1)
        alert = self.store.get_alert(opp_id, "ntfy")
        self.assertIsNotNone(alert["sent_at"])
        self.assertAlmostEqual(alert["drop_latency_s"], 30, delta=5)

        # A later resighting of the same opportunity must not alert twice.
        await dispatcher.dispatch(it, opp_id)
        self.assertEqual(len(channel.sent), 1)

    async def test_non_matching_item_never_alerts(self):
        channel = FakeChannel()
        dispatcher = AlertDispatcher(self.store, profile=PROFILE, channels=[channel])
        it = item(title="Marketing Manager", location="London")
        opp_id, _ = self.store.upsert_item(it)
        await dispatcher.dispatch(it, opp_id)
        self.assertEqual(channel.sent, [])
        self.assertIsNone(self.store.get_alert(opp_id, "ntfy"))

    async def test_instagram_item_alerts_even_without_a_profile_match(self):
        channel = FakeChannel()
        dispatcher = AlertDispatcher(self.store, profile=PROFILE, channels=[channel])
        it = item(source=ZERO2SUDO_SOURCE, title="Unrelated caption", location="")
        opp_id, _ = self.store.upsert_item(it)
        await dispatcher.dispatch(it, opp_id)
        self.assertEqual(len(channel.sent), 1)

    async def test_failed_send_leaves_alert_pending_and_dispatch_does_not_retry_it(self):
        """dispatch() only claims a fresh (opportunity, channel); once claimed
        (sent or pending), only retry_pending() may act on it again -- this is
        what makes a slow in-flight send race-safe against a concurrent dispatch."""
        channel = FakeChannel(fail_times=1)
        dispatcher = AlertDispatcher(self.store, profile=PROFILE, channels=[channel])
        it = item()
        opp_id, _ = self.store.upsert_item(it)
        await dispatcher.dispatch(it, opp_id)  # fails, claims the slot
        self.assertEqual(channel.sent, [])
        pending = self.store.get_alert(opp_id, "ntfy")
        self.assertIsNotNone(pending)
        self.assertIsNone(pending["sent_at"])

        await dispatcher.dispatch(it, opp_id)  # already claimed; dispatch() leaves it alone
        self.assertEqual(channel.sent, [])

    async def test_retry_pending_resends_a_failed_claim_and_backs_off_between_attempts(self):
        channel = FakeChannel(fail_times=1)
        dispatcher = AlertDispatcher(self.store, profile=PROFILE, channels=[channel])
        it = item()
        opp_id, _ = self.store.upsert_item(it)
        await dispatcher.dispatch(it, opp_id)  # fails, claims the slot, schedules backoff
        self.assertEqual(channel.sent, [])

        await dispatcher.retry_pending()  # still inside backoff: must not hammer the channel
        self.assertEqual(channel.sent, [])

        dispatcher._backoff_until.clear()  # simulate backoff having elapsed
        await dispatcher.retry_pending()
        self.assertEqual(len(channel.sent), 1)
        self.assertIsNotNone(self.store.get_alert(opp_id, "ntfy")["sent_at"])

    async def test_retry_pending_never_re_gates_on_matches_profile(self):
        """The overview says an ATS board usually publishes before zero2sudo
        posts about it. If that first (non-matching) sighting's source were
        used to re-decide eligibility on retry, a failed zero2sudo send would
        get stuck pending forever -- the exact opposite of "insider, highest
        priority". The claim already decided; retry_pending must only retry
        the send, never cancel an alert a later, non-matching item happens to
        also touch."""
        channel = FakeChannel(fail_times=1)
        dispatcher = AlertDispatcher(self.store, profile=PROFILE, channels=[channel])
        non_matching = item(source="ats.greenhouse.stripe", title="Marketing Manager", location="London")
        opp_id, _ = self.store.upsert_item(non_matching)
        await dispatcher.dispatch(non_matching, opp_id)
        self.assertIsNone(self.store.get_alert(opp_id, "ntfy"))  # not eligible yet, nothing claimed

        zero2sudo_item = item(source=ZERO2SUDO_SOURCE, external_id="media:1", title="Marketing Manager")
        self.store.upsert_item(zero2sudo_item, opportunity_id=opp_id)
        await dispatcher.dispatch(zero2sudo_item, opp_id)  # claims, first send fails
        self.assertEqual(channel.sent, [])
        self.assertIsNone(self.store.get_alert(opp_id, "ntfy")["sent_at"])

        dispatcher._backoff_until.clear()
        await dispatcher.retry_pending()
        self.assertEqual(len(channel.sent), 1, "a pending alert must never be silently dropped")

    async def test_retry_pending_does_not_duplicate_across_concurrent_sweeps(self):
        """pending_alerts() is a snapshot taken once per sweep. Two sweeps
        (e.g. two sources' poll ticks) running concurrently must not let one
        finish a row that the other, still awaiting an earlier row in its own
        stale snapshot, goes on to send again."""
        class FlakyThenStallOnceChannel:
            name = "ntfy"

            def __init__(self):
                self.sent = []
                self._fail_remaining = 2
                self._stalled_once = False

            def send(self, opp, reasons, drop_latency_s):
                if self._fail_remaining > 0:
                    self._fail_remaining -= 1
                    raise RuntimeError("channel unavailable")
                if not self._stalled_once:
                    self._stalled_once = True
                    time.sleep(0.1)  # whichever row sends first stalls, opening the race window
                self.sent.append(opp["id"])

        channel = FlakyThenStallOnceChannel()
        dispatcher = AlertDispatcher(self.store, profile=PROFILE, channels=[channel])
        opp_a, _ = self.store.upsert_item(item(external_id="a", url="https://x.example/a"))
        opp_b, _ = self.store.upsert_item(item(external_id="b", url="https://x.example/b"))
        await dispatcher.dispatch(item(external_id="a", url="https://x.example/a"), opp_a)  # fails, claims
        await dispatcher.dispatch(item(external_id="b", url="https://x.example/b"), opp_b)  # fails, claims
        self.assertEqual(channel.sent, [])
        dispatcher._backoff_until.clear()

        await asyncio.gather(dispatcher.retry_pending(), dispatcher.retry_pending())
        self.assertEqual(len(channel.sent), 2, "each opportunity must be sent exactly once, never duplicated")

    async def test_concurrent_dispatch_of_the_same_opportunity_sends_only_once(self):
        """A slow in-flight send (await asyncio.to_thread) must not be raced by
        another coroutine dispatching the same opportunity in the meantime."""
        channel = FakeChannel(delay_s=0.05)
        dispatcher = AlertDispatcher(self.store, profile=PROFILE, channels=[channel])
        it = item()
        opp_id, _ = self.store.upsert_item(it)
        await asyncio.gather(dispatcher.dispatch(it, opp_id), dispatcher.dispatch(it, opp_id))
        self.assertEqual(len(channel.sent), 1)

    async def test_malformed_published_at_still_sends_with_no_latency(self):
        channel = FakeChannel()
        dispatcher = AlertDispatcher(self.store, profile=PROFILE, channels=[channel])
        it = item()
        opp_id, _ = self.store.upsert_item(it)
        self.store.save_opportunity(opp_id, first_seen=T0, published_at="garbage")
        await dispatcher.dispatch(it, opp_id)
        self.assertEqual(len(channel.sent), 1)
        self.assertIsNone(channel.sent[0][2])  # drop_latency_s
        self.assertIsNone(self.store.get_alert(opp_id, "ntfy")["drop_latency_s"])

    async def test_closed_opportunity_does_not_alert(self):
        channel = FakeChannel()
        dispatcher = AlertDispatcher(self.store, profile=PROFILE, channels=[channel])
        it = item(raw={"closed": True})
        opp_id, _ = self.store.upsert_item(item())
        self.store.save_opportunity(opp_id, first_seen=T0, status="Closed")
        await dispatcher.dispatch(it, opp_id)
        self.assertEqual(channel.sent, [])


if __name__ == "__main__":
    unittest.main()
