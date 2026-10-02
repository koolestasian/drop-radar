import tempfile
import unittest
from pathlib import Path

from radar.config import Company, InstagramAccount, Profile, User, Watchlist, load_settings, load_users
from radar.errors import ConfigError
from radar.sources.registry import build_sources_for_users

ROOT = Path(__file__).resolve().parent.parent
SETTINGS = load_settings({})


def config_dir(files):
    """Write {relative path: text} into a fresh dir; returns the users.yaml path."""
    d = Path(tempfile.mkdtemp())
    for rel, text in files.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(text, encoding="utf-8")
    return d / "users.yaml"


def user(id, companies=(), instagram=()):
    return User(id=id, watchlist=Watchlist(companies=tuple(companies), instagram=tuple(instagram)), profile=Profile())


class LoadUsersTests(unittest.TestCase):
    def test_shipped_users_config_loads(self):
        kevin, friend = load_users(ROOT / "config" / "users.yaml")
        self.assertEqual((kevin.id, friend.id), ("kevin", "friend"))
        self.assertEqual(kevin.watchlist.instagram[0].username, "zero2sudo")
        self.assertEqual(kevin.profile.grad_year, 2027)
        self.assertTrue(friend.watchlist.companies)
        self.assertEqual(friend.watchlist.instagram, ())  # zero2sudo is CS-focused; that one is kevin's

    def test_paths_resolve_relative_to_users_yaml_not_the_cwd(self):
        path = config_dir({
            "users.yaml": "users: [{id: a, watchlist: a/w.yaml, profile: a/p.yaml}]",
            "a/w.yaml": "companies: [{name: Stripe, ats: greenhouse, slug: stripe}]",
            "a/p.yaml": "grad_year: 2028",
        })
        [a] = load_users(path)
        self.assertEqual(a.watchlist.companies[0].slug, "stripe")
        self.assertEqual(a.profile.grad_year, 2028)

    def test_the_shipped_guest_profile_loads_and_is_broad(self):
        from radar.config import load_guest_profile
        guest = load_guest_profile()
        self.assertIn("software engineer", guest.roles)
        self.assertIn("investment banking", guest.roles)
        self.assertIsNone(guest.grad_year)
        self.assertEqual(guest.locations, ())

    def test_invalid_users_name_the_problem(self):
        ok = {"w.yaml": "", "p.yaml": ""}
        cases = [
            ("users: []", "at least one user"),
            ("users: [{id: a, watchlist: w.yaml}]", r"users\[0\].*'profile'"),
            ("users: [{watchlist: w.yaml, profile: p.yaml}]", r"users\[0\].*'id'"),
            ("users: [{id: a, watchlist: w.yaml, profile: p.yaml}, {id: a, watchlist: w.yaml, profile: p.yaml}]",
             "duplicate user id"),
            ("users: [{id: a, watchlist: missing.yaml, profile: p.yaml}]", "cannot read"),
            ("users: [{id: guest, watchlist: w.yaml, profile: p.yaml}]", "reserved"),
        ]
        for text, pattern in cases:
            with self.subTest(text=text), self.assertRaisesRegex(ConfigError, pattern):
                load_users(config_dir({"users.yaml": text, **ok}))


class BuildSourcesForUsersTests(unittest.TestCase):
    def test_a_company_both_users_list_is_polled_once_and_owned_by_both(self):
        stripe = Company(name="Stripe", ats="greenhouse", slug="stripe")
        airbnb = Company(name="Airbnb", ats="greenhouse", slug="airbnb")
        sources, owned, _ = build_sources_for_users(
            [user("kevin", [stripe, airbnb]), user("friend", [stripe])], SETTINGS
        )
        self.assertEqual(sorted(s.name for s in sources), ["ats.greenhouse.airbnb", "ats.greenhouse.stripe"])
        self.assertEqual(owned["kevin"], {"ats.greenhouse.airbnb", "ats.greenhouse.stripe"})
        self.assertEqual(owned["friend"], {"ats.greenhouse.stripe"})

    def test_a_shared_source_polls_at_the_faster_users_interval(self):
        slow = Company(name="Stripe", ats="greenhouse", slug="stripe", tier="C")
        fast = Company(name="Stripe", ats="greenhouse", slug="stripe", tier="S")
        for order in ([slow, fast], [fast, slow]):
            with self.subTest(first=order[0].tier):
                sources, _, _ = build_sources_for_users([user("a", [order[0]]), user("b", [order[1]])], SETTINGS)
                expected, _, _ = build_sources_for_users([user("x", [fast])], SETTINGS)
                self.assertEqual(sources[0].interval_s, expected[0].interval_s)

    def test_a_user_with_an_empty_watchlist_owns_nothing(self):
        sources, owned, _ = build_sources_for_users([user("friend")], SETTINGS)
        self.assertEqual((sources, owned), ([], {"friend": frozenset()}))

    def test_instagram_cap_applies_to_the_union_across_users(self):
        """One IG_SESSIONID serves every user, so 3 + 3 accounts is over the cap
        even though each file alone is under it."""
        a = [InstagramAccount(username=f"a{i}") for i in range(3)]
        b = [InstagramAccount(username=f"b{i}") for i in range(3)]
        with self.assertRaisesRegex(ConfigError, "6 instagram accounts"):
            build_sources_for_users([user("a", instagram=a), user("b", instagram=b)], SETTINGS)

    def test_the_same_instagram_account_on_both_lists_counts_once(self):
        shared = [InstagramAccount(username=f"s{i}") for i in range(5)]
        sources, _, _ = build_sources_for_users([user("a", instagram=shared), user("b", instagram=shared)], SETTINGS)
        self.assertEqual(len(sources), 5)


if __name__ == "__main__":
    unittest.main()
