"""T18: the bitmap index must answer every list and count exactly as the SQL path does."""
import asyncio
import itertools
import random
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import httpx

from radar.api.app import create_app
from radar.api import bitindex
from radar.api.events import EventBus
from radar.api.bitindex import BitIndex
from radar.config import Profile, User, Watchlist
from radar.models import Item
from radar.store import Store

T0 = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)
KEVIN, FRIEND = "k" * 24, "f" * 24
TOKENS = {KEVIN: "kevin", FRIEND: "friend"}
PROFILES = {
    "kevin": Profile(roles=("software engineer", "quant"), keywords=("intern", "new grad")),
    "friend": Profile(roles=("investment banking",), keywords=("summer analyst", "intern")),
}
OWNED = {"kevin": frozenset({"ats.greenhouse.stripe", "ats.greenhouse.airbnb", "ats.lever.citadel"}),
         "friend": frozenset({"ats.greenhouse.stripe", "ats.greenhouse.point72"})}
SOURCES = ["ats.greenhouse.stripe", "ats.greenhouse.airbnb", "ats.greenhouse.point72", "ats.lever.citadel"]
COMPANIES = ["Stripe", "Airbnb", "Point72", "Citadel"]
TITLES = ["Software Engineer Intern", "Quant Trader New Grad", "Investment Banking Summer Analyst",
          "Data Scientist", "Tax Intern", "Product Manager", "Junior Software Engineer"]
PLACES = ["New York, NY", "Toronto, ON, Canada", "", "London, UK", "Remote"]


def seed_store(store, rng, n=90):
    for company, tier in {"Stripe": "S", "Citadel": "A", "Airbnb": "C"}.items():
        store.set_enrichment("company_tier:" + company.lower(), {"tier": tier})
    ids = []
    for k in range(n):
        posted = rng.choice([None, None, datetime(2026, 9, rng.randint(1, 30), tzinfo=timezone.utc),
                             (T0 + timedelta(hours=rng.randint(0, 700))).astimezone(timezone(timedelta(hours=-4)))])
        # few distinct titles/places make plenty of twins; some twins are seen by two sources
        opp_id, _ = store.upsert_item(Item(
            source=rng.choice(SOURCES), external_id=f"e{k}", url=f"https://x.example/{k}", title=rng.choice(TITLES),
            company=rng.choice(COMPANIES), location=rng.choice(PLACES), published_at=posted,
            seen_at=T0 + timedelta(hours=rng.randint(0, 700)), raw={"seed": True} if rng.random() < 0.3 else {}))
        ids.append(opp_id)
    for opp_id in rng.sample(ids, 8):
        store.save_opportunity(opp_id, first_seen=T0, status="Closed")
    for opp_id in rng.sample(ids, 10):
        store.set_action(opp_id, "kevin", status="ignored")
    return ids


def make_app(store, bitmap):
    runtime = SimpleNamespace(users={u: User(id=u, watchlist=Watchlist(), profile=p) for u, p in PROFILES.items()},
                              owned=OWNED, scheduler=None)
    app = create_app(store, runtime, tokens=TOKENS, now=lambda: NOW)
    if not bitmap:
        app.state.index.view = lambda *a, **k: None  # every request reads SQL
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    client.index = app.state.index
    return client


class BitIndexTests(unittest.IsolatedAsyncioTestCase):
    def test_close_waits_for_workers_and_prevents_reopening(self):
        index = BitIndex(None)
        connection = Mock()
        index.conn = connection
        started = threading.Event()

        def close():
            started.set()
            index.close()

        with index.lock:
            worker = threading.Thread(target=close)
            worker.start()
            self.assertTrue(started.wait(1))
            connection.close.assert_not_called()
        worker.join(1)
        self.assertFalse(worker.is_alive())
        connection.close.assert_called_once()
        index.safely(User(id="owner", watchlist=Watchlist(), profile=Profile()), set())
        self.assertIsNone(index.conn)

    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "radar.db"
        self.store = Store(self.path)
        self.addCleanup(self.store.close)
        self.rng = random.Random(7)
        self.ids = seed_store(self.store, self.rng)
        self.fast, self.slow = make_app(self.store, True), make_app(self.store, False)

    async def asyncTearDown(self):
        await self.fast.aclose()
        await self.slow.aclose()

    async def walk(self, client, token, **params):
        """Every page of a list: [(ids, next_cursor)], so the cursors are compared too."""
        pages, cursor = [], None
        while True:
            r = await client.get("/api/opportunities", headers={"Authorization": f"Bearer {token}"} if token else {},
                                 params={"limit": 7, **params, **({"cursor": cursor} if cursor else {})})
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            pages.append(([o["id"] for o in body["items"]], body["next_cursor"]))
            if not (cursor := body["next_cursor"]):
                return pages

    async def same(self, token, **params):
        slow = await self.walk(self.slow, token, **params)
        self.assertEqual(await self.walk(self.fast, token, **params), slow, params)
        return slow

    async def test_every_filter_combination_pages_exactly_like_sql(self):
        names = ("include", "sort", "level", "track", "backfill", "posted_within", "us_only", "q")
        space = list(itertools.product(("matches", "all"), ("posted", "prestige"), (None, "intern", "new_grad"),
                                       (None, "Software", "Quant", "Finance"), (None, "false", "true"),
                                       (None, 3, 30), (None, "true"), (None, "intern")))
        shown = 0
        for token, count in ((KEVIN, 120), (FRIEND, 120), (None, 10)):  # a guest is limited to 60 requests a minute
            for combo in self.rng.sample(space, count):
                params = {k: v for k, v in zip(names, combo) if v is not None}
                shown += sum(len(ids) for ids, _ in await self.same(token, **params))
        self.assertEqual(set(self.fast.index.views), {"kevin", "friend", "guest"}, "the fast app must have used the index")
        self.assertGreater(shown, 200, "the combinations must return something or they prove nothing")

    async def test_summary_equals_the_paged_totals(self):
        for token in (KEVIN, FRIEND):
            body = (await self.fast.get("/api/opportunities/summary", headers={"Authorization": f"Bearer {token}"})).json()
            for scope, include in (("you", "matches"), ("everything", "all")):
                rows = []
                cursor = None
                while True:
                    r = (await self.slow.get("/api/opportunities", headers={"Authorization": f"Bearer {token}"},
                                             params={"include": include, "limit": 200,
                                                     **({"cursor": cursor} if cursor else {})})).json()
                    rows += r["items"]
                    if not (cursor := r["next_cursor"]):
                        break
                self.assertEqual(body[scope]["total"], len(rows))
                for lvl in ("intern", "new_grad"):
                    self.assertEqual(body[scope]["level"].get(lvl, 0), sum(o["level"] == lvl for o in rows))
                for name in {o["track"] for o in rows}:
                    self.assertEqual(body[scope]["track"][name], sum(o["track"] == name for o in rows))

    async def test_writes_show_up_on_the_next_read_whoever_made_them(self):
        queries = ({}, {"include": "all"}, {"include": "all", "sort": "prestige"}, {"include": "all", "posted_within": 5})
        pick = self.rng.sample(self.ids, 6)
        other = Store(self.path)  # another connection, like the fixers
        self.addCleanup(other.close)
        steps = (
            lambda: self.store.upsert_item(Item(source=SOURCES[0], external_id="old", url="https://x.example/old",
                                                title="Software Engineer Intern", company="Stripe", location="New York, NY",
                                                seen_at=T0 - timedelta(days=100), raw={"seed": True})),  # out of order
            lambda: self.store.upsert_item(Item(source=SOURCES[1], external_id="new", url="https://x.example/new",
                                                title="Quant Trader New Grad", company="Airbnb", location="New York, NY",
                                                seen_at=NOW - timedelta(hours=1))),
            lambda: self.store.set_action(pick[0], "kevin", status="ignored"),
            lambda: self.store.set_action(pick[0], "kevin", status=""),
            lambda: other.save_opportunity(pick[1], first_seen=T0, published_at=datetime(2026, 9, 30, tzinfo=timezone.utc)),
            lambda: other.save_opportunity(pick[2], first_seen=T0, status="Closed"),
            lambda: other.upsert_item(Item(source=SOURCES[3], external_id="e-twin", url="https://x.example/twin",
                                           title="Tax Intern", company="Stripe", location="New York, NY", seen_at=NOW)),
        )
        for step in steps:
            step()
            for token in (KEVIN, FRIEND):
                for q in queries:
                    await self.same(token, **q)

    async def test_the_index_is_built_in_the_background_without_making_requests_wait(self):
        user = User(id="kevin", watchlist=Watchlist(), profile=PROFILES["kevin"])
        index = BitIndex(self.store)
        self.addCleanup(index.close)
        self.assertIsNone(index.view(user, OWNED["kevin"]), "nothing is ready on the first call")
        for _ in range(200):
            view = index.view(user, OWNED["kevin"])
            if view is not None:
                break
            await asyncio.sleep(0.05)
        self.assertIsNotNone(view)
        self.assertEqual(len(view.snap.recs), len(self.ids))
        self.assertIsNone(index.view(user, frozenset()), "a different set of sources is not served from this view")
        started = time.monotonic()
        index.view(user, OWNED["kevin"])
        self.assertLess(time.monotonic() - started, 0.05)

    async def test_a_new_posting_reaches_the_snapshot_on_a_nudge_and_not_before(self):
        user = User(id="kevin", watchlist=Watchlist(), profile=PROFILES["kevin"])
        index = BitIndex(self.store)
        self.addCleanup(index.close)
        index.update(user, OWNED["kevin"])
        before = index.snap
        new_id, _ = self.store.upsert_item(Item(source=SOURCES[0], external_id="late", url="https://x.example/late",
                                                title="Software Engineer Intern", company="Stripe", seen_at=NOW))
        index.view(user, OWNED["kevin"])  # recently refreshed and nothing nudged: no refresh yet
        await asyncio.sleep(0.2)
        self.assertIs(index.snap, before)
        self.addCleanup(setattr, bitindex, "MIN_GAP", bitindex.MIN_GAP)
        bitindex.MIN_GAP = 0
        index.nudge()
        for _ in range(100):
            if index.snap is not before:
                break
            await asyncio.sleep(0.05)
        self.assertIn(new_id, index.snap.pos)

    async def test_a_drop_is_in_a_list_opened_right_after_its_push_when_run_like_production(self):
        """Production has a scheduler, so the index builds and refreshes in worker threads; a nudge must make
        lists read SQL until the index has caught up, never serve the snapshot from before the drop."""
        bus = EventBus()
        runtime = SimpleNamespace(users={u: User(id=u, watchlist=Watchlist(), profile=p) for u, p in PROFILES.items()},
                                  owned=OWNED, scheduler=object(), events=bus)
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(self.store, runtime, tokens=TOKENS,
                                                                                now=lambda: NOW)), base_url="http://t")
        self.addCleanup(client.aclose)
        self.addCleanup(setattr, bitindex, "MIN_GAP", bitindex.MIN_GAP)
        bitindex.MIN_GAP = 0
        head = {"Authorization": f"Bearer {KEVIN}"}

        async def ids():
            r = await client.get("/api/opportunities", headers=head, params={"include": "all", "limit": 200})
            return {o["id"] for o in r.json()["items"]}

        for _ in range(200):  # warm: the first requests read SQL while a worker builds the view
            await ids()
            have = client._transport.app.state.index.views.get("kevin")
            if have and have[0].gen >= client._transport.app.state.index.wanted:
                break
            await asyncio.sleep(0.05)
        index = client._transport.app.state.index
        self.assertIn("kevin", index.views, "the index never came up")
        new_id, _ = self.store.upsert_item(Item(source=SOURCES[0], external_id="drop", url="https://x.example/drop",
                                                title="Software Engineer Intern", company="Stripe", seen_at=NOW))
        bus.publish("opportunity", new_id)
        self.assertIn(new_id, await ids(), "a list opened right after the push must show the drop")
        for _ in range(200):  # and once the index has caught up it serves the drop itself
            await ids()
            if index.views["kevin"][0].gen >= index.wanted and new_id in index.snap.pos:
                break
            await asyncio.sleep(0.05)
        self.assertIn(new_id, index.snap.pos)
        self.assertIn(new_id, await ids())


if __name__ == "__main__":
    unittest.main()
