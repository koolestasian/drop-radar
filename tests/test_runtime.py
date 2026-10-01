import tempfile
import unittest
from pathlib import Path

from radar.api.runtime import Runtime
from radar.config import load_settings
from radar.errors import ConfigError
from radar.store import Store

KEVIN_WL = "companies: [{name: Stripe, ats: greenhouse, slug: stripe}, {name: Airbnb, ats: greenhouse, slug: airbnb}]"
FRIEND_WL = "companies: [{name: Stripe, ats: greenhouse, slug: stripe}]"
USERS = """users:
  - {id: kevin, watchlist: kevin/w.yaml, profile: kevin/p.yaml}
  - {id: friend, watchlist: friend/w.yaml, profile: friend/p.yaml}
"""


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.write("users.yaml", USERS)
        self.write("kevin/w.yaml", KEVIN_WL)
        self.write("kevin/p.yaml", "roles: [software engineer]")
        self.write("friend/w.yaml", FRIEND_WL)
        self.write("friend/p.yaml", "roles: [investment banking]")
        self.store = Store(self.dir / "radar.db")
        self.addCleanup(self.store.close)

    def write(self, rel, text):
        (self.dir / rel).parent.mkdir(parents=True, exist_ok=True)
        (self.dir / rel).write_text(text)

    def runtime(self, env=None):
        return Runtime(self.store, settings=load_settings({}), users_path=self.dir / "users.yaml", env=env or {})

    def test_one_scheduler_polls_the_union_and_each_user_owns_their_own_sources(self):
        rt = self.runtime()
        self.assertEqual(sorted(rt.scheduler.sources), ["ats.greenhouse.airbnb", "ats.greenhouse.stripe"])
        self.assertEqual(rt.owned["friend"], {"ats.greenhouse.stripe"})
        self.assertIs(rt.scheduler.sink, rt.pipeline)

    def test_each_user_gets_their_own_alert_channel(self):
        rt = self.runtime({"NTFY_TOPIC": "k", "NTFY_TOPIC_FRIEND": "f"})
        channels = {uid: [c.name for c in d.channels] for uid, d in rt.pipeline.alerter.dispatchers.items()}
        self.assertEqual(channels, {"kevin": ["ntfy"], "friend": ["ntfy:friend"]})

    def test_reload_picks_up_an_edit_in_place(self):
        rt = self.runtime()
        scheduler, pipeline = rt.scheduler, rt.pipeline
        self.write("friend/w.yaml", "companies: [{name: Point72, ats: greenhouse, slug: point72}]")
        rt.reload()
        self.assertIs(rt.scheduler, scheduler)
        self.assertIs(rt.pipeline, pipeline)
        self.assertEqual(rt.owned["friend"], {"ats.greenhouse.point72"})
        self.assertIn("ats.greenhouse.point72", rt.scheduler.sources)

    def test_a_bad_edit_raises_and_leaves_the_running_config_alone(self):
        rt = self.runtime()
        before = (dict(rt.scheduler.sources), rt.pipeline.alerter, rt.owned)
        self.write("friend/w.yaml", "companies: [unclosed")
        with self.assertRaisesRegex(ConfigError, "invalid YAML"):
            rt.reload()
        self.assertEqual((dict(rt.scheduler.sources), rt.pipeline.alerter, rt.owned), before)

    def test_renaming_a_user_who_has_saved_statuses_is_refused(self):
        self.runtime()
        self.store.save_opportunity("o1", first_seen="2026-09-01T00:00:00+00:00")
        self.store.set_action("o1", "friend", status="applied")
        self.write("users.yaml", USERS.replace("id: friend", "id: buddy"))
        with self.assertRaisesRegex(ConfigError, "friend"):
            self.runtime()

    def test_the_first_user_owns_the_original_alert_channel_and_cannot_silently_change(self):
        """Swapping the order would hand kevin's "ntfy" alert history to friend and
        re-send every alert kevin already got, under "ntfy:kevin"."""
        self.runtime()
        self.write("users.yaml", "users:\n" + "\n".join(reversed(USERS.splitlines()[1:])) + "\n")
        with self.assertRaisesRegex(ConfigError, "first user"):
            self.runtime()


if __name__ == "__main__":
    unittest.main()
