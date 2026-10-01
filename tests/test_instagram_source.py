import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from radar.config import ConfigError, InstagramAccount, Settings, load_watchlist
from radar.errors import SourceError
from radar.legacy.instagram_scraper import InstagramAuthError, InstagramBlockedError
from radar.models import Item, utcnow
from radar.sources import instagram as instagram_source
from radar.store import Store

# Shared fixture, same cache key/pk as tests/test_instagram.py's identity test,
# so this is a known-good native/Apify pair, not a re-derived one.
PK = "3988152627153629542"
APIFY_CACHE_KEY = "Mzk4ODE1MjYyNzE1MzYyOTU0Mg%3D%3D.3-ccb7-5"


def write(text):
    d = tempfile.mkdtemp()
    p = Path(d) / "c.yaml"
    p.write_text(text, encoding="utf-8")
    return p


class FakeClock:
    def __init__(self):
        self.t = utcnow()

    def now(self):
        return self.t

    def advance(self, seconds):
        self.t += timedelta(seconds=seconds)


class Ctx:
    def __init__(self, clock):
        self.clock = clock

    def now(self):
        return self.clock.now()


class FakeNativeClient:
    """`.stories()` always raises the given exception (disable/cool-down path)."""

    def __init__(self, exc):
        self.exc = exc
        self.calls = 0

    def stories(self, username):
        self.calls += 1
        raise self.exc


def make_source(client=None, apify_token=""):
    account = InstagramAccount(username="zero2sudo", interval_s=120.0)
    settings = Settings(ig_sessionid="sid", apify_token=apify_token)
    return instagram_source.InstagramSource(account, settings, client=client)


class DisableCooldownTests(unittest.IsolatedAsyncioTestCase):
    async def test_auth_error_without_apify_raises_auth(self):
        source = make_source(client=FakeNativeClient(InstagramAuthError("expired")))
        with self.assertRaises(SourceError) as cm:
            await source.fetch(Ctx(FakeClock()))
        self.assertEqual(cm.exception.kind, "auth")

    async def test_blocked_error_without_apify_raises_blocked(self):
        source = make_source(client=FakeNativeClient(InstagramBlockedError("rate limited")))
        with self.assertRaises(SourceError) as cm:
            await source.fetch(Ctx(FakeClock()))
        self.assertEqual(cm.exception.kind, "blocked")


class ApifyFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_rate_limited_to_one_run_per_15_min(self):
        # Blocked, not auth: a blocked native source only cools down (T2 keeps
        # calling fetch every 30 min), so it is the scenario where the real
        # scheduler can actually retry across the 15 min Apify window. An auth
        # failure gets the source disabled after the first uncovered tick, so
        # fetch() would never be called a third time in production.
        clock = FakeClock()
        ctx = Ctx(clock)
        source = make_source(client=FakeNativeClient(InstagramBlockedError("rate limited")), apify_token="tok")
        apify_raw = [{"pk": "1", "taken_at": 1700000000}]
        with patch.object(instagram_source.legacy, "run_actor", return_value=apify_raw) as run_actor:
            items = await source.fetch(ctx)
            self.assertEqual(len(items), 1)
            self.assertEqual(run_actor.call_count, 1)

            clock.advance(60)  # well within the 15 min window
            with self.assertRaises(SourceError):
                await source.fetch(ctx)
            self.assertEqual(run_actor.call_count, 1)  # not called again

            clock.advance(900)  # past the window
            items2 = await source.fetch(ctx)
            self.assertEqual(len(items2), 1)
            self.assertEqual(run_actor.call_count, 2)

    async def test_apify_unavailable_raises_native_error(self):
        source = make_source(client=FakeNativeClient(InstagramAuthError("expired")), apify_token="")
        with self.assertRaises(SourceError) as cm:
            await source.fetch(Ctx(FakeClock()))
        self.assertEqual(cm.exception.kind, "auth")

    async def test_apify_failure_raises_native_error_not_apify_error(self):
        source = make_source(client=FakeNativeClient(InstagramBlockedError("blocked")), apify_token="tok")
        with patch.object(instagram_source.legacy, "run_actor", side_effect=RuntimeError("actor boom")):
            with self.assertRaises(SourceError) as cm:
                await source.fetch(Ctx(FakeClock()))
        self.assertEqual(cm.exception.kind, "blocked")


class IdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_and_apify_items_share_external_id(self):
        now = utcnow()
        native_raw = {
            "pk": PK,
            "url": f"https://www.instagram.com/stories/zero2sudo/{PK}/",
            "taken_at": 1700000000,
            "text": "Palantir SWE internship applications are open",
            "links": ["https://jobs.lever.co/palantir/abc"],
        }
        apify_raw = {
            "id": "something-else",
            "text": "Palantir SWE internship applications are open",
            "image": f"https://scontent-lax.cdninstagram.com/v/a.jpg?ig_cache_key={APIFY_CACHE_KEY}",
            "link": "https://jobs.lever.co/palantir/abc",
        }
        with patch.object(instagram_source.legacy, "ocr_image", return_value=""):
            native_item = await instagram_source._build_item("zero2sudo", native_raw, now)
            apify_item = await instagram_source._build_item("zero2sudo", apify_raw, now)
        # "media:" prefix matches radar.store.migrate_legacy.record_semantic_key,
        # so a Story already migrated from the legacy tracker is not re-added.
        self.assertEqual(native_item.external_id, f"media:{PK}")
        self.assertEqual(native_item.external_id, apify_item.external_id)
        # url is the application link (what the contract calls canonical), not
        # the Story permalink, so this item can merge with an ATS source that
        # sees the same posting.
        self.assertEqual(native_item.url, "https://jobs.lever.co/palantir/abc")
        self.assertEqual(native_item.url, apify_item.url)

    async def test_falls_back_to_permalink_without_an_application_link(self):
        now = utcnow()
        raw = {"pk": PK, "url": f"https://www.instagram.com/stories/zero2sudo/{PK}/", "text": "no link here"}
        item = await instagram_source._build_item("zero2sudo", raw, now)
        self.assertEqual(item.url, f"https://www.instagram.com/stories/zero2sudo/{PK}/")

    async def test_ocr_runs_once_per_external_id_with_a_shared_cache(self):
        now = utcnow()
        raw = {"pk": PK, "image_url": "https://scontent.cdninstagram.com/v/a.jpg", "text": "hi"}
        cache = {}
        with patch.object(instagram_source.legacy, "item_text", wraps=lambda r: "hi") as item_text:
            await instagram_source._build_item("zero2sudo", raw, now, text_cache=cache)
            await instagram_source._build_item("zero2sudo", raw, now, text_cache=cache)
        self.assertEqual(item_text.call_count, 1)


class MigrationConvergenceTests(unittest.IsolatedAsyncioTestCase):
    """What T5 actually guarantees for a Story already migrated from the legacy
    tracker (radar/store/migrate_legacy.py) and still live: it converges to the
    SAME (source, external_id) items row, so it is not double-counted as a new
    sighting. This does NOT by itself guarantee one opportunities row -- that
    needs a Store/migration-level fix outside T5's scope; see the final report.
    """

    async def test_items_row_converges_with_the_legacy_migration_key(self):
        legacy_row = {
            "Application / Registration Link": "https://jobs.lever.co/palantir/abc",
            "Instagram Source": f"https://www.instagram.com/stories/zero2sudo/{PK}/",
            "Opportunity": "Palantir SWE Internship",
            "Raw Text": "Palantir SWE internship applications are open",
            "Posted At": "",
        }
        semantic_key = instagram_source.legacy.record_semantic_key(legacy_row)

        raw = {
            "pk": PK,
            "url": legacy_row["Instagram Source"],
            "text": legacy_row["Raw Text"],
            "links": [legacy_row["Application / Registration Link"]],
        }
        item = await instagram_source._build_item("zero2sudo", raw, utcnow())
        self.assertEqual(item.external_id, semantic_key)  # real function, not a hardcoded "media:" string

        store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(store.close)
        store.upsert_item(
            Item(source="instagram.zero2sudo", external_id=semantic_key,
                 url=legacy_row["Application / Registration Link"],
                 title=legacy_row["Opportunity"], seen_at=utcnow()),
            opportunity_id="legacyid00000000000",  # stand-in for migrate_legacy's preserved tracker ID
        )
        store.upsert_item(item)
        since = utcnow() - timedelta(days=3650)
        self.assertEqual(store.count_items("instagram.zero2sudo", since), 1)


class IntervalTests(unittest.TestCase):
    def test_interval_comes_from_watchlist_account_no_extra_jitter(self):
        account = InstagramAccount(username="zero2sudo", interval_s=120.0)
        source = instagram_source.InstagramSource(account, Settings())
        self.assertEqual(source.interval_s, 120.0)
        self.assertEqual(source.name, "instagram.zero2sudo")


class WatchlistCapTests(unittest.TestCase):
    def test_sixth_instagram_account_is_rejected(self):
        entries = "\n".join(f"  - {{username: user{i}}}" for i in range(6))
        with self.assertRaisesRegex(ConfigError, "at most 5"):
            load_watchlist(write(f"instagram:\n{entries}\n"))

    def test_five_instagram_accounts_are_fine(self):
        entries = "\n".join(f"  - {{username: user{i}}}" for i in range(5))
        wl = load_watchlist(write(f"instagram:\n{entries}\n"))
        self.assertEqual(len(wl.instagram), 5)


if __name__ == "__main__":
    unittest.main()
