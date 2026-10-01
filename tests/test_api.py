import asyncio
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx

from radar.alerts import AlertDispatcher, MultiUserAlertDispatcher, visible_to
from radar.api.app import create_app
from radar.api.runtime import Runtime
from radar.config import load_settings
from radar.config import Profile, User, Watchlist
from radar.models import Item
from radar.store import Store

T0 = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
KEVIN, FRIEND = "k" * 24, "f" * 24
TOKENS = {KEVIN: "kevin", FRIEND: "friend"}
PROFILES = {
    "kevin": Profile(roles=("software engineer",), keywords=("intern", "new grad")),
    "friend": Profile(roles=("investment banking",), keywords=("summer analyst", "intern")),
}
OWNED = {
    "kevin": frozenset({"ats.greenhouse.stripe", "ats.greenhouse.airbnb"}),
    "friend": frozenset({"ats.greenhouse.stripe", "ats.greenhouse.point72"}),
}
SEED = [  # (source, external_id, title, company, hours after T0, deadline)
    ("ats.greenhouse.stripe", "swe", "Software Engineer Intern", "Stripe", 0, ""),
    ("ats.greenhouse.point72", "ib", "Investment Banking Summer Analyst", "Point72", 1, "2026-10-05"),
    ("ats.greenhouse.airbnb", "ng", "Software Engineer, New Grad", "Airbnb", 2, "2026-12-01"),
    ("ats.greenhouse.stripe", "tax", "Tax Intern", "Stripe", 3, ""),
]


def directory():
    users = {uid: User(id=uid, watchlist=Watchlist(), profile=p) for uid, p in PROFILES.items()}
    return SimpleNamespace(users=users, owned=OWNED, scheduler=None)


def auth(token):
    return {"Authorization": f"Bearer {token}"}


class FakeScheduler:
    def __init__(self):
        self.started, self.stopped = asyncio.Event(), False

    async def run(self, stop):
        self.started.set()
        await stop.wait()
        self.stopped = True


class FakeRuntime:
    def __init__(self):
        self.scheduler = FakeScheduler()


class AppLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(self.store.close)

    async def test_the_scheduler_runs_for_exactly_as_long_as_the_server(self):
        runtime = FakeRuntime()
        app = create_app(self.store, runtime)
        async with app.router.lifespan_context(app):
            await asyncio.wait_for(runtime.scheduler.started.wait(), 1)
            self.assertFalse(runtime.scheduler.stopped)
        self.assertTrue(runtime.scheduler.stopped, "shutdown lets the scheduler drain, not just cancels it")

    async def test_without_a_runtime_nothing_polls(self):
        app = create_app(self.store)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
                self.assertEqual((await client.get("/healthz")).json(), {"ok": True})


class OpportunityApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(self.store.close)
        self.ids = {}
        for source, eid, title, company, hours, deadline in SEED:
            opp_id, _ = self.store.upsert_item(Item(source=source, external_id=eid, url=f"https://x.example/{eid}",
                                                    title=title, company=company, location="New York, NY",
                                                    seen_at=T0 + timedelta(hours=hours)))
            if deadline:
                self.store.save_opportunity(opp_id, first_seen=T0 + timedelta(hours=hours), deadline=deadline)
            self.ids[eid] = opp_id
        today = datetime(2026, 10, 1, tzinfo=timezone.utc)
        app = create_app(self.store, directory(), tokens=TOKENS, now=lambda: today)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def get(self, path, token=KEVIN, **params):
        return await self.client.get(path, headers=auth(token), params=params)

    async def ids_of(self, token, **params):
        r = await self.get("/api/opportunities", token, **params)
        self.assertEqual(r.status_code, 200, r.text)
        return {o["id"] for o in r.json()["items"]}

    def names(self, *eids):
        return {self.ids[e] for e in eids}

    async def test_every_api_route_needs_a_valid_token(self):
        for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": KEVIN}):
            with self.subTest(headers=headers):
                r = await self.client.get("/api/opportunities", headers=headers)
                self.assertEqual(r.status_code, 401)
        self.assertEqual((await self.get("/api/me")).json()["user"], "kevin")

    async def test_each_user_sees_matches_from_their_own_sources_only(self):
        self.assertEqual(await self.ids_of(KEVIN), self.names("swe", "ng"))
        self.assertEqual(await self.ids_of(FRIEND), self.names("ib"))

    async def test_include_all_widens_to_everything_their_sources_found_never_the_other_users(self):
        self.assertEqual(await self.ids_of(KEVIN, include="all"), self.names("swe", "ng", "tax"))
        self.assertEqual(await self.ids_of(FRIEND, include="all"), self.names("swe", "ib", "tax"))

    async def test_an_opportunity_from_someone_elses_sources_is_a_404_not_a_403(self):
        self.assertEqual((await self.get(f"/api/opportunities/{self.ids['ib']}", KEVIN)).status_code, 404)
        r = await self.get(f"/api/opportunities/{self.ids['ib']}", FRIEND)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["match"]["ok"])
        self.assertTrue(body["match"]["reasons"])
        self.assertEqual(body["sources"], ["ats.greenhouse.point72"])

    async def test_status_and_notes_are_private_to_whoever_set_them(self):
        swe = self.ids["swe"]
        r = await self.client.patch(f"/api/opportunities/{swe}", headers=auth(FRIEND),
                                    json={"status": "saved", "notes": "ask Kevin about this"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["action"], {"status": "saved", "notes": "ask Kevin about this"})
        mine = (await self.get(f"/api/opportunities/{swe}", KEVIN)).json()
        self.assertIsNone(mine["action"])
        await self.client.patch(f"/api/opportunities/{swe}", headers=auth(FRIEND), json={"status": "applied"})
        theirs = (await self.get(f"/api/opportunities/{swe}", FRIEND)).json()["action"]
        self.assertEqual(theirs, {"status": "applied", "notes": "ask Kevin about this"}, "omitted notes are kept")

    async def test_patch_rejects_unknown_statuses_and_invisible_opportunities(self):
        r = await self.client.patch(f"/api/opportunities/{self.ids['swe']}", headers=auth(KEVIN),
                                    json={"status": "hired!!"})
        self.assertEqual(r.status_code, 422)
        r = await self.client.patch(f"/api/opportunities/{self.ids['ib']}", headers=auth(KEVIN),
                                    json={"status": "saved"})
        self.assertEqual(r.status_code, 404)

    async def test_filters(self):
        await self.client.patch(f"/api/opportunities/{self.ids['ng']}", headers=auth(KEVIN), json={"status": "applied"})
        cases = [
            ({"q": "new grad"}, {"ng"}), ({"company": "stripe"}, {"swe"}),
            ({"action": "applied"}, {"ng"}), ({"source": "ats.greenhouse.airbnb"}, {"ng"}),
            ({"since": (T0 + timedelta(hours=1)).isoformat()}, {"ng"}),
        ]
        for params, expected in cases:
            with self.subTest(params=params):
                self.assertEqual(await self.ids_of(KEVIN, **params), self.names(*expected))
        friend_soon = await self.ids_of(FRIEND, closing_within=30)
        self.assertEqual(friend_soon, self.names("ib"))

    async def test_cursor_pagination_walks_newest_first_without_repeats(self):
        seen, cursor = [], None
        while True:
            params = {"include": "all", "limit": 1, **({"cursor": cursor} if cursor else {})}
            page = (await self.get("/api/opportunities", KEVIN, **params)).json()
            seen += [o["id"] for o in page["items"]]
            cursor = page["next_cursor"]
            if not cursor:
                break
        self.assertEqual(seen, [self.ids[e] for e in ("tax", "ng", "swe")])


class FeedAndAlertsAgreeTests(unittest.IsolatedAsyncioTestCase):
    """Every opportunity the phone is alerted on is in that user's feed."""

    async def test_alerted_opportunities_are_exactly_the_feed_matches(self):
        store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(store.close)
        sent = {uid: [] for uid in PROFILES}

        class Channel:
            def __init__(self, uid):
                self.name, self.uid = f"ntfy:{uid}", uid

            def send(self, opp, reasons, latency):
                sent[self.uid].append(opp["id"])

        alerter = MultiUserAlertDispatcher(
            {uid: AlertDispatcher(store, profile=p, channels=[Channel(uid)]) for uid, p in PROFILES.items()}, OWNED)
        for source, eid, title, company, hours, _ in SEED:
            it = Item(source=source, external_id=eid, url=f"https://x.example/{eid}", title=title, company=company,
                      seen_at=T0 + timedelta(hours=hours))
            opp_id, _ = store.upsert_item(it)
            await alerter.dispatch(it, opp_id)
        for uid, profile in PROFILES.items():
            feed = {o["id"] for o in store.list_opportunities()
                    if visible_to(store.get_opportunity(o["id"]), profile, OWNED[uid])[1]}
            self.assertEqual(set(sent[uid]), feed, uid)


class ConfigApiTests(unittest.IsolatedAsyncioTestCase):
    """Each user edits only their own watchlist/profile; edits are checked by the
    same rules as startup and go live without a restart."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        files = {
            "users.yaml": "users:\n  - {id: kevin, watchlist: kevin/w.yaml, profile: kevin/p.yaml}\n"
                          "  - {id: friend, watchlist: friend/w.yaml, profile: friend/p.yaml}\n",
            "kevin/w.yaml": "companies: [{name: Stripe, ats: greenhouse, slug: stripe}]\n"
                            "instagram: [{username: a1}, {username: a2}, {username: a3}]\n",
            "kevin/p.yaml": "roles: [software engineer]\n",
            "friend/w.yaml": "companies: [{name: Point72, ats: greenhouse, slug: point72}]\n",
            "friend/p.yaml": "roles: [investment banking]\n",
        }
        for rel, text in files.items():
            (self.dir / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.dir / rel).write_text(text)
        self.store = Store(self.dir / "radar.db")
        self.addCleanup(self.store.close)
        self.runtime = Runtime(self.store, settings=load_settings({}), users_path=self.dir / "users.yaml", env={})
        app = create_app(self.store, self.runtime, tokens=TOKENS)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def put(self, kind, body, token=FRIEND):
        return await self.client.put(f"/api/config/{kind}", headers=auth(token), json=body)

    async def test_get_returns_only_your_own_config(self):
        r = await self.client.get("/api/config/watchlist", headers=auth(FRIEND))
        self.assertEqual([c["slug"] for c in r.json()["companies"]], ["point72"])
        r = await self.client.get("/api/config/profile", headers=auth(KEVIN))
        self.assertEqual(r.json()["roles"], ["software engineer"])
        self.assertEqual((await self.client.get("/api/config/profile")).status_code, 401)

    async def test_a_valid_edit_is_written_and_goes_live_and_nobody_elses_changes(self):
        kevin_before = (self.dir / "kevin/w.yaml").read_text()
        body = {"companies": [{"name": "Point72", "ats": "greenhouse", "slug": "point72"},
                              {"name": "AQR", "ats": "greenhouse", "slug": "aqr", "tier": "A"}]}
        r = await self.put("watchlist", body)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.runtime.owned["friend"], {"ats.greenhouse.point72", "ats.greenhouse.aqr"})
        self.assertIn("ats.greenhouse.aqr", self.runtime.scheduler.sources)
        self.assertIn("aqr", (self.dir / "friend/w.yaml").read_text())
        self.assertEqual((self.dir / "kevin/w.yaml").read_text(), kevin_before)

    async def test_an_invalid_edit_is_a_422_naming_the_field_and_changes_nothing(self):
        before = (self.dir / "friend/w.yaml").read_text()
        r = await self.put("watchlist", {"companies": [{"name": "X", "ats": "nope", "slug": "x"}]})
        self.assertEqual(r.status_code, 422)
        self.assertIn("companies[0]", r.text)
        self.assertIn("'ats'", r.text)
        self.assertEqual((self.dir / "friend/w.yaml").read_text(), before)
        self.assertEqual(self.runtime.owned["friend"], {"ats.greenhouse.point72"})
        r = await self.put("profile", {"grad_year": 1999})
        self.assertEqual(r.status_code, 422)
        self.assertIn("grad_year", r.text)

    async def test_an_edit_valid_alone_but_not_with_the_other_users_config_is_rolled_back(self):
        """kevin has 3 Instagram accounts; the friend adding 3 more breaks the
        shared 5-account cap only when both files are taken together."""
        before = (self.dir / "friend/w.yaml").read_text()
        r = await self.put("watchlist", {"instagram": [{"username": f"b{i}"} for i in range(3)]})
        self.assertEqual(r.status_code, 422)
        self.assertIn("instagram", r.text)
        self.assertEqual((self.dir / "friend/w.yaml").read_text(), before)
        self.assertEqual(self.runtime.owned["friend"], {"ats.greenhouse.point72"})

    async def test_a_profile_edit_changes_what_matches_immediately(self):
        r = await self.put("profile", {"roles": ["private equity"], "keywords": ["summer analyst"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.runtime.users["friend"].profile.roles, ("private equity",))
        dispatcher = self.runtime.pipeline.alerter.dispatchers["friend"]
        self.assertEqual(dispatcher.profile.roles, ("private equity",))


if __name__ == "__main__":
    unittest.main()
