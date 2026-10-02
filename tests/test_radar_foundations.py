import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from radar.config import load_profile, load_settings, load_watchlist
from radar.errors import ConfigError, SourceError
from radar.models import Item, Opportunity, opportunity_id

ROOT = Path(__file__).resolve().parent.parent


def write(text):
    d = tempfile.mkdtemp()
    p = Path(d) / "c.yaml"
    p.write_text(text, encoding="utf-8")
    return p


class ModelTests(unittest.TestCase):
    def test_item_defaults_and_frozen(self):
        item = Item(source="s", external_id="1", url="https://x/y", title="T")
        self.assertIsNotNone(item.seen_at.tzinfo)
        with self.assertRaises(Exception):
            item.title = "other"

    def test_opportunity_id_prefers_url_and_is_stable(self):
        a = opportunity_id("https://x/y", "Co", "T", "L")
        self.assertEqual(a, opportunity_id("https://x/y", "Other", "T2", "L2"))
        self.assertEqual(len(a), 20)
        b = opportunity_id("", "Co", "T", "L")
        self.assertEqual(b, opportunity_id("", " co ", "t", "l"))
        self.assertNotEqual(a, b)

    def test_drop_latency(self):
        t = datetime(2026, 1, 1, tzinfo=timezone.utc)
        opp = Opportunity(id="a", title="t", first_seen=t.replace(minute=5), published_at=t)
        self.assertEqual(opp.drop_latency_s, 300)
        self.assertIsNone(Opportunity(id="a", title="t").drop_latency_s)

    def test_source_error_kinds(self):
        self.assertEqual(SourceError("x", kind="auth").kind, "auth")
        with self.assertRaises(ValueError):
            SourceError("x", kind="nope")


class ConfigTests(unittest.TestCase):
    def test_shipped_config_loads(self):
        wl = load_watchlist(ROOT / "config" / "watchlist.yaml")
        self.assertTrue(wl.companies and wl.instagram)
        self.assertEqual(wl.instagram[0].username, "zero2sudo")
        profile = load_profile(ROOT / "config" / "profile.yaml")
        self.assertEqual(profile.grad_year, 2027)

    def test_settings_from_env(self):
        s = load_settings({"NTFY_TOPIC": "t", "IG_SESSIONID": "s"})
        self.assertEqual((s.ntfy_topic, s.ig_sessionid, s.apify_token), ("t", "s", ""))

    def test_bad_yaml_message(self):
        with self.assertRaisesRegex(ConfigError, "invalid YAML"):
            load_watchlist(write("companies: [unclosed"))

    def test_missing_file(self):
        with self.assertRaisesRegex(ConfigError, "cannot read"):
            load_watchlist(Path(tempfile.mkdtemp()) / "nope.yaml")

    def test_bad_values_name_the_field(self):
        cases = [
            ("companies: [{name: A, ats: nope, slug: a}]", r"companies\[0\].*'ats'"),
            ("companies: [{name: A, ats: lever}]", r"'slug'"),
            ("companies: [{name: A, ats: lever, slug: a, tier: Z}]", r"'tier'"),
            ("instagram: [{username: x, interval_s: -1}]", r"'interval_s'"),
            ("feeds: [{url: ftp://x}]", r"'url'"),
            ("repos: [{name: noslash}]", r"owner/name"),
            ("companies: {a: 1}", r"'companies' must be a list"),
            ("- just a list", r"top level"),
        ]
        for text, pattern in cases:
            with self.subTest(text=text), self.assertRaisesRegex(ConfigError, pattern):
                load_watchlist(write(text))

    def test_profile_validation(self):
        with self.assertRaisesRegex(ConfigError, "grad_year"):
            load_profile(write("grad_year: soon"))
        with self.assertRaisesRegex(ConfigError, "roles"):
            load_profile(write("roles: 5"))
        with self.assertRaisesRegex(ConfigError, "company_tiers"):
            load_profile(write("company_tiers: {A: Q}"))
        self.assertEqual(load_profile(write("")).roles, ())


if __name__ == "__main__":
    unittest.main()
