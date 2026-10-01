import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from radar.alerts import AlertDispatcher, MultiUserAlertDispatcher, channels_for
from radar.config import Profile
from radar.models import Item
from radar.store import Store

T0 = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
CS = Profile(roles=("software engineer intern",), keywords=("intern",))
FINANCE = Profile(roles=("investment banking", "private equity"), keywords=("summer analyst", "finance"))


class FakeChannel:
    def __init__(self, name):
        self.name = name
        self.sent = []

    def send(self, opp, reasons, drop_latency_s):
        self.sent.append(opp["id"])


class Exploding:
    async def dispatch(self, item, opportunity_id):
        raise RuntimeError("boom")

    async def retry_pending(self):
        raise RuntimeError("boom")


def item(source, title, external_id="1"):
    return Item(source=source, external_id=external_id, url=f"https://x.example/{source}/{external_id}",
                title=title, seen_at=T0)


class MultiUserAlertDispatcherTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(self.store.close)
        self.kevin, self.friend = FakeChannel("ntfy"), FakeChannel("ntfy:friend")
        self.dispatchers = {
            "kevin": AlertDispatcher(self.store, profile=CS, channels=[self.kevin]),
            "friend": AlertDispatcher(self.store, profile=FINANCE, channels=[self.friend]),
        }

    def alerter(self, owned, dispatchers=None):
        return MultiUserAlertDispatcher(dispatchers or self.dispatchers, owned)

    async def dispatch(self, alerter, it):
        opp_id, _ = self.store.upsert_item(it)
        await alerter.dispatch(it, opp_id)

    async def test_a_profile_match_only_alerts_the_user_whose_watchlist_found_it(self):
        """A SWE posting on a board only the friend watches matches kevin's CS
        profile -- without the ownership gate kevin would be alerted on it."""
        alerter = self.alerter({"kevin": frozenset({"ats.greenhouse.stripe"}),
                                "friend": frozenset({"ats.greenhouse.goldman"})})
        await self.dispatch(alerter, item("ats.greenhouse.goldman", "Software Engineer Intern"))
        self.assertEqual((self.kevin.sent, self.friend.sent), ([], []))

    async def test_a_shared_source_alerts_each_user_on_their_own_profile(self):
        both = frozenset({"ats.greenhouse.jpmorgan"})
        alerter = self.alerter({"kevin": both, "friend": both})
        await self.dispatch(alerter, item("ats.greenhouse.jpmorgan", "Software Engineer Intern", "1"))
        await self.dispatch(alerter, item("ats.greenhouse.jpmorgan", "Investment Banking Summer Analyst", "2"))
        self.assertEqual(len(self.kevin.sent), 1)
        self.assertEqual(len(self.friend.sent), 1)
        self.assertNotEqual(self.kevin.sent, self.friend.sent)

    async def test_one_users_failure_does_not_block_another(self):
        alerter = self.alerter(
            {"broken": frozenset({"ats.a"}), "friend": frozenset({"ats.a"})},
            {"broken": Exploding(), "friend": self.dispatchers["friend"]},
        )
        await self.dispatch(alerter, item("ats.a", "Private Equity Summer Analyst"))
        self.assertEqual(len(self.friend.sent), 1)
        await alerter.retry_pending()  # must not raise either

    def test_two_users_sharing_a_channel_name_is_rejected(self):
        clash = {"a": AlertDispatcher(self.store, profile=CS, channels=[FakeChannel("ntfy")]),
                 "b": AlertDispatcher(self.store, profile=CS, channels=[FakeChannel("ntfy")])}
        with self.assertRaisesRegex(ValueError, "ntfy"):
            MultiUserAlertDispatcher(clash, {"a": frozenset(), "b": frozenset()})


class ChannelsForTests(unittest.TestCase):
    def test_the_owner_keeps_the_original_channel_and_topic(self):
        """The first user's channel stays named "ntfy" so every alerts row
        written before multi-user support still matches it."""
        [channel] = channels_for("kevin", owner=True, env={"NTFY_TOPIC": "k-topic"})
        self.assertEqual((channel.name, channel.topic), ("ntfy", "k-topic"))

    def test_other_users_get_their_own_channel_and_topic_env_var(self):
        [channel] = channels_for("friend-2", owner=False, env={"NTFY_TOPIC": "k", "NTFY_TOPIC_FRIEND_2": "f"})
        self.assertEqual((channel.name, channel.topic), ("ntfy:friend-2", "f"))

    def test_no_topic_means_no_channel_never_the_owners_topic(self):
        self.assertEqual(channels_for("friend", owner=False, env={"NTFY_TOPIC": "kevins"}), [])
        self.assertEqual(channels_for("kevin", owner=True, env={}), [])


if __name__ == "__main__":
    unittest.main()
