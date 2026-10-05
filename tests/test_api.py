import asyncio
import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx

from radar.alerts import AlertDispatcher, MultiUserAlertDispatcher, NtfyChannel, visible_to
from radar.api.app import create_app
from radar.api.events import EventBus
from radar.api.runtime import Runtime
from radar.pipeline.places import format_location
from radar.config import load_settings
from radar.config import Profile, User, Watchlist
from radar.models import Item
from radar.pipeline import Pipeline
from radar.pipeline.enrich import Enricher
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


class CrashingScheduler:
    """run() raises as soon as it starts, simulating a scheduler bug uvicorn's
    lifespan can't otherwise detect (it just logs and keeps serving)."""

    async def run(self, stop):
        raise RuntimeError("boom")


class CrashingRuntime:
    def __init__(self):
        self.scheduler = CrashingScheduler()


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

    async def test_a_crashed_scheduler_takes_the_process_down_with_it(self):
        """Without this, uvicorn just logs Scheduler.run()'s exception and keeps
        serving a process that stopped polling -- Restart=always never fires."""
        calls = []
        app = create_app(self.store, CrashingRuntime(), crash_exit=lambda: calls.append(1))
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0.05)
        self.assertEqual(calls, [1])

    async def test_a_clean_shutdown_never_calls_crash_exit(self):
        calls = []
        runtime = FakeRuntime()
        app = create_app(self.store, runtime, crash_exit=lambda: calls.append(1))
        async with app.router.lifespan_context(app):
            await asyncio.wait_for(runtime.scheduler.started.wait(), 1)
        self.assertEqual(calls, [])

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

    async def test_a_wrong_token_is_always_refused_and_only_reading_works_without_one(self):
        for headers in ({"Authorization": "Bearer nope"}, {"Authorization": KEVIN}):
            for path in ("/api/opportunities", "/api/me", "/api/config/profile"):
                with self.subTest(headers=headers, path=path):
                    self.assertEqual((await self.client.get(path, headers=headers)).status_code, 401)
        self.assertEqual((await self.get("/api/me")).json()["user"], "kevin")

    async def guest_get(self, path, **params):
        return await self.client.get(path, params=params)

    async def test_a_visitor_without_a_token_reads_everything_found_with_the_default_profile(self):
        r = await self.guest_get("/api/opportunities", include="all")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual({o["id"] for o in r.json()["items"]}, self.names("swe", "ib", "ng", "tax"))
        feed = {o["id"] for o in (await self.guest_get("/api/opportunities")).json()["items"]}
        self.assertEqual(feed, self.names("swe", "ib", "ng"))  # default profile: tech and business, not "Tax Intern"
        me = (await self.guest_get("/api/me")).json()
        self.assertEqual((me["user"], me["guest"], me["alerts_enabled"], me["sources"]), ("guest", True, False, 3))
        self.assertEqual((await self.guest_get(f"/api/opportunities/{self.ids['ib']}")).status_code, 200)

    async def test_a_visitor_never_sees_anyones_status_or_notes(self):
        swe = self.ids["swe"]
        await self.client.patch(f"/api/opportunities/{swe}", headers=auth(KEVIN),
                                json={"status": "saved", "notes": "recruiter said call Tuesday"})
        r = await self.guest_get("/api/opportunities", include="all", action="saved")
        self.assertNotIn("Tuesday", r.text)
        self.assertTrue(all(o["action"] is None for o in r.json()["items"]))
        self.assertIsNone((await self.guest_get(f"/api/opportunities/{swe}")).json()["action"])

    async def test_a_visitor_cannot_write_or_read_account_routes(self):
        swe = self.ids["swe"]
        checks = [
            self.client.patch(f"/api/opportunities/{swe}", json={"status": "saved"}),
            self.client.put("/api/config/profile", json={"roles": ["x"], "keywords": ["y"]}),
            self.client.put("/api/config/watchlist", json={}),
            self.client.get("/api/config/profile"), self.client.get("/api/config/watchlist"),
            self.client.post("/api/instagram/relay", json={"username": "zero2sudo", "stories": []}),
            self.client.get("/api/sources/health"), self.client.get("/api/metrics"), self.client.get("/api/stream"),
        ]
        for response in checks:
            r = await response
            self.assertEqual(r.status_code, 401, r.request.url)
        self.assertIsNone((await self.get(f"/api/opportunities/{swe}", KEVIN)).json()["action"])  # nothing was saved

    async def test_visitors_are_rate_limited_and_get_small_cached_pages(self):
        r = await self.guest_get("/api/opportunities", include="all", limit=200)
        self.assertEqual(r.status_code, 200)
        for _ in range(60):
            r = await self.guest_get("/api/me")
        self.assertEqual(r.status_code, 429)
        self.assertEqual((await self.get("/api/me")).status_code, 200)  # logged-in users are not limited

    async def test_the_place_is_shown_as_city_state_or_city_country_and_the_original_is_kept(self):
        body = (await self.get(f"/api/opportunities/{self.ids['swe']}", KEVIN)).json()
        self.assertEqual(body["location"], "New York, NY")  # displayed "City, ST" in the US
        self.assertEqual(format_location("Barcelona"), "Barcelona, Spain")
        self.assertEqual(body["location_raw"], "New York, NY")

    async def test_each_user_sees_matches_from_their_own_sources_only(self):
        self.assertEqual(await self.ids_of(KEVIN), self.names("swe", "ng"))
        self.assertEqual(await self.ids_of(FRIEND), self.names("ib"))

    async def test_market_estimate_only_appears_when_employer_pay_is_blank(self):
        first = (await self.get(f"/api/opportunities/{self.ids['swe']}")).json()
        self.assertEqual(first["pay"], "")
        self.assertTrue(first["pay_estimate"])
        self.assertIn("BLS", first["pay_estimate_basis"])
        self.store.save_opportunity(self.ids["swe"], first_seen=T0, fields={"Pay": "$30–$40/hr"})
        second = (await self.get(f"/api/opportunities/{self.ids['swe']}")).json()
        self.assertEqual(second["pay"], "$30–$40/hr")
        self.assertEqual(second["pay_estimate"], "")

    async def test_include_all_widens_to_everything_their_sources_found_never_the_other_users(self):
        self.assertEqual(await self.ids_of(KEVIN, include="all"), self.names("swe", "ng", "tax"))
        self.assertEqual(await self.ids_of(FRIEND, include="all"), self.names("swe", "ib", "tax"))

    async def test_level_and_track_filter_on_the_server_and_come_back_on_each_item(self):
        self.assertEqual(await self.ids_of(KEVIN, include="all", level="intern"), self.names("swe", "tax"))
        self.assertEqual(await self.ids_of(KEVIN, include="all", level="new_grad"), self.names("ng"))
        self.assertEqual(await self.ids_of(KEVIN, include="all", track="Finance"), self.names("tax"))
        self.assertEqual(await self.ids_of(KEVIN, level="intern", track="Software"), self.names("swe"))
        items = (await self.get("/api/opportunities", include="all")).json()["items"]
        self.assertEqual({o["id"]: (o["level"], o["track"]) for o in items},
                         {self.ids["swe"]: ("intern", "Software"), self.ids["ng"]: ("new_grad", "Software"),
                          self.ids["tax"]: ("intern", "Finance")})
        for bad in ({"level": "senior"}, {"track": "Plumbing"}):
            self.assertEqual((await self.get("/api/opportunities", **bad)).status_code, 422)

    async def test_posted_within_counts_days_back_from_the_posting_date_or_the_live_drop_time(self):
        # now is 2026-10-01; nothing has a posting date, so the live drops' found time (Sep 20) stands in
        self.assertEqual(await self.ids_of(KEVIN, include="all", posted_within=7), set())
        self.assertEqual(await self.ids_of(KEVIN, include="all", posted_within=30), self.names("swe", "ng", "tax"))
        self.store.save_opportunity(self.ids["swe"], first_seen=T0, published_at=datetime(2026, 9, 30, tzinfo=timezone.utc))
        self.assertEqual(await self.ids_of(KEVIN, include="all", posted_within=1), self.names("swe"))  # date-only: Sep 30 is 1 day back

    async def counted(self, token):
        for _ in range(100):
            r = await self.get("/api/opportunities/summary", token)
            if r.status_code == 200:
                return r.json()
            await asyncio.sleep(0.05)
        self.fail(r.text)

    async def test_the_summary_counts_exactly_what_the_list_shows(self):
        for token, who in ((KEVIN, "kevin"), (FRIEND, "friend")):
            body = await self.counted(token)
            for scope, include in (("you", "matches"), ("everything", "all")):
                with self.subTest(who=who, scope=scope):
                    shown = (await self.get("/api/opportunities", token, include=include)).json()["items"]
                    counts = body[scope]
                    self.assertEqual(counts["total"], len(shown))
                    for lvl in ("intern", "new_grad"):
                        self.assertEqual(counts["level"].get(lvl, 0), sum(o["level"] == lvl for o in shown))
                    for name in {o["track"] for o in shown}:
                        self.assertEqual(counts["track"][name], sum(o["track"] == name for o in shown))
        for _ in range(100):  # the first request starts the count and is told to retry
            r = await self.guest_get("/api/opportunities/summary")
            if r.status_code == 200:
                break
            self.assertEqual((r.status_code, r.headers["retry-after"]), (503, "5"))
            await asyncio.sleep(0.05)
        self.assertEqual(r.json()["everything"]["total"], 4)

    async def test_phone_configuration_exposes_only_this_users_subscription(self):
        runtime = directory()
        runtime.pipeline = SimpleNamespace(alerter=MultiUserAlertDispatcher({
            "kevin": AlertDispatcher(self.store, channels=[NtfyChannel("private-k", server="https://ntfy.sh", token="never-expose")]),
            "friend": AlertDispatcher(self.store, channels=[NtfyChannel("private-f", server="https://ntfy.sh", name="ntfy:friend")]),
        }, OWNED))
        app = create_app(self.store, runtime, tokens=TOKENS)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            for token, topic, other in ((KEVIN, "private-k", "private-f"), (FRIEND, "private-f", "private-k")):
                r = await client.get("/api/me", headers=auth(token))
                self.assertTrue(r.json()["alerts_enabled"])
                self.assertEqual(r.json()["notification_url"], f"https://ntfy.sh/{topic}")
                self.assertNotIn(other, r.text)
                self.assertNotIn("never-expose", r.text)
            guest = (await client.get("/api/me")).json()
            self.assertTrue(guest["guest"])
            self.assertIsNone(guest["notification_url"])
            self.assertNotIn("private-", json.dumps(guest))

    async def test_missing_phone_channel_is_explicitly_disabled(self):
        body = (await self.get("/api/me")).json()
        self.assertFalse(body["alerts_enabled"])
        self.assertIsNone(body["notification_url"])

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
        self.assertEqual(r.json()["action"], {"status": "saved", "notes": "ask Kevin about this", "hide_term": None, "hide_term_at": None})
        mine = (await self.get(f"/api/opportunities/{swe}", KEVIN)).json()
        self.assertIsNone(mine["action"])
        await self.client.patch(f"/api/opportunities/{swe}", headers=auth(FRIEND), json={"status": "applied"})
        theirs = (await self.get(f"/api/opportunities/{swe}", FRIEND)).json()["action"]
        self.assertEqual(theirs, {"status": "applied", "notes": "ask Kevin about this", "hide_term": None, "hide_term_at": None}, "omitted notes are kept")

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

    async def test_dead_postings_leave_the_feed_but_stay_findable_and_on_your_board(self):
        ng = self.ids["ng"]
        self.store.save_opportunity(ng, first_seen=T0, status="Expired")
        self.assertEqual(await self.ids_of(KEVIN), self.names("swe"))
        self.assertEqual(await self.ids_of(KEVIN, status="Expired"), self.names("ng"))
        await self.client.patch(f"/api/opportunities/{ng}", headers=auth(KEVIN), json={"status": "applied"})
        self.assertEqual(await self.ids_of(KEVIN, action="applied"), self.names("ng"))

    async def test_backfilled_postings_are_flagged_so_they_are_not_mistaken_for_drops(self):
        seed = Item(source="ats.greenhouse.airbnb", external_id="old", url="https://x.example/old",
                    title="Software Engineer Intern", company="Airbnb", raw={"seed": True}, seen_at=T0)
        old_id, _ = self.store.upsert_item(seed)
        by_id = {o["id"]: o for o in (await self.get("/api/opportunities", KEVIN, include="all")).json()["items"]}
        self.assertTrue(by_id[old_id]["backfill"])
        self.assertFalse(by_id[self.ids["ng"]]["backfill"])

    async def test_backfill_uses_only_the_users_own_sightings(self):
        url = "https://x.example/shared"
        opp_id, _ = self.store.upsert_item(Item(
            source="ats.greenhouse.airbnb", external_id="shared", url=url,
            title="Software Engineer Intern", raw={"seed": True}, seen_at=T0))
        self.store.upsert_item(Item(source="ats.greenhouse.point72", external_id="shared", url=url,
                                   title="Software Engineer Intern", seen_at=T0))
        for token, expected in ((KEVIN, True), (FRIEND, False)):
            out = (await self.get(f"/api/opportunities/{opp_id}", token)).json()
            self.assertEqual(out["backfill"], expected)
        self.store.upsert_item(Item(source="ats.greenhouse.stripe", external_id="shared", url=url,
                                   title="Software Engineer Intern", seen_at=T0))
        out = (await self.get(f"/api/opportunities/{opp_id}", KEVIN)).json()
        self.assertFalse(out["backfill"], "one live sighting among my own sources makes it a drop")

    async def test_backfill_filter_agrees_with_each_users_flag(self):
        url = "https://x.example/shared"
        opp_id, _ = self.store.upsert_item(Item(
            source="ats.greenhouse.airbnb", external_id="shared", url=url,
            title="Software Engineer Intern", raw={"seed": True}, seen_at=T0))
        self.store.upsert_item(Item(source="ats.greenhouse.point72", external_id="shared", url=url,
                                   title="Software Engineer Intern", seen_at=T0))
        for token, seeded in ((KEVIN, True), (FRIEND, False)):
            for backfill in ("true", "false"):
                with self.subTest(token=token, backfill=backfill):
                    page = (await self.get("/api/opportunities", token, include="all", backfill=backfill)).json()
                    self.assertEqual(opp_id in {o["id"] for o in page["items"]}, (backfill == "true") == seeded)
                    self.assertTrue(all(o["backfill"] == (backfill == "true") for o in page["items"]))

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

    async def test_the_same_job_posted_as_several_requisitions_is_one_card(self):
        for n in range(3):  # Invesco: five "Business Trainee, Hyderabad" requisitions, one job
            self.store.upsert_item(Item(source="ats.greenhouse.airbnb", external_id=f"twin{n}", company="Invesco",
                                        url=f"https://x.example/twin{n}", title="Business Trainee",
                                        location="Hyderabad, Telangana", seen_at=T0))
        page = (await self.get("/api/opportunities", KEVIN, include="all")).json()
        self.assertEqual(sum(o["title"] == "Business Trainee" for o in page["items"]), 1)

    async def test_sort_by_posted_or_found_pages_in_utc_order(self):
        ny = timezone(timedelta(hours=-4))
        rows = {  # eid: (found, posted)
            "timed": (T0 + timedelta(hours=10.5), (T0 + timedelta(hours=9)).astimezone(ny)),  # 21:00Z, stored -04:00
            "dateonly": (T0 + timedelta(hours=10), datetime(2026, 9, 20, tzinfo=timezone.utc)),  # "posted Sep 20"
            "undated": (T0 + timedelta(hours=5), None),
            "old": (T0 + timedelta(hours=11), T0 - timedelta(hours=48)),
            "undated-backfill": (T0 + timedelta(hours=12), None),  # found on a first poll: age unknown
        }
        for eid, (found, posted) in rows.items():
            self.ids[eid], _ = self.store.upsert_item(Item(
                source="ats.greenhouse.airbnb", external_id=eid, url=f"https://x.example/{eid}",
                title=f"Software Engineer Intern Sortcheck {eid}", seen_at=found, published_at=posted,
                raw={"seed": True} if eid == "undated-backfill" else {}))

        async def walk(sort):
            seen, cursor = [], None
            while True:
                params = {"include": "all", "q": "Sortcheck", "sort": sort, "limit": 1, **({"cursor": cursor} if cursor else {})}
                page = (await self.get("/api/opportunities", KEVIN, **params)).json()
                seen += [o["id"] for o in page["items"]]
                if not (cursor := page["next_cursor"]):
                    return seen

        # date-only counts as late that day as its sighting allows (22:00), above 21:00Z
        self.assertEqual(await walk("posted"),
                         [self.ids[e] for e in ("dateonly", "timed", "undated", "old", "undated-backfill")])
        self.assertEqual(await walk("found"),
                         [self.ids[e] for e in ("undated-backfill", "old", "timed", "dateonly", "undated")])


    async def test_search_and_location_terms_and_us_only_needs_a_confirmed_us_place(self):
        for eid, location in (("sv", "Sunnyvale, CA"), ("to", "Toronto, ON, Canada"), ("blank", "")):
            self.ids[eid], _ = self.store.upsert_item(Item(
                source="ats.greenhouse.airbnb", external_id=eid, url=f"https://x.example/{eid}",
                title="Software Engineer Intern", company="Airbnb", location=location, seen_at=T0))
        # every word must start a word: "ny" is New York's NY, not Sunnyvale's "nny"
        self.assertEqual(await self.ids_of(KEVIN, include="all", q="intern", location="ny"), self.names("swe", "tax"))
        self.assertEqual(await self.ids_of(KEVIN, include="all", q="airbnb", location="toronto"), self.names("to"))
        self.assertEqual(await self.ids_of(KEVIN, include="all", q="toronto"), set())  # search is role/company only
        self.assertEqual(await self.ids_of(KEVIN, include="all", us_only="true"), self.names("swe", "tax", "ng", "sv"))

    async def test_prestige_sorts_by_tier_then_newest_posted_across_pages(self):
        users = directory().users
        for company, tier in {"Airbnb": "S", "Stripe": "C"}.items():
            self.store.set_enrichment("company_tier:" + company.lower(), {"tier": tier})
        app = create_app(self.store, SimpleNamespace(users=users, owned=OWNED, scheduler=None), tokens=TOKENS)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            seen, cursor = [], None
            while True:
                params = {"include": "all", "sort": "prestige", "limit": 1, **({"cursor": cursor} if cursor else {})}
                page = (await client.get("/api/opportunities", headers=auth(KEVIN), params=params)).json()
                seen += [o["id"] for o in page["items"]]
                if not (cursor := page["next_cursor"]):
                    break
        self.assertEqual(seen, [self.ids[e] for e in ("ng", "tax", "swe")])


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


class NoLLM:
    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}

    def extract(self, *a, **kw):
        return None


class StreamTests(unittest.IsolatedAsyncioTestCase):
    """A real server on 127.0.0.1 (ASGITransport buffers whole responses, so it
    can't carry an endless stream). Loopback only -- nothing leaves the machine."""

    async def asyncSetUp(self):
        import uvicorn

        self.store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(self.store.close)
        bus = EventBus()
        no_channels = {uid: AlertDispatcher(self.store, profile=p, channels=[]) for uid, p in PROFILES.items()}
        self.pipeline = Pipeline(self.store, enricher=Enricher(self.store, extractor=NoLLM()),
                                 alerter=MultiUserAlertDispatcher(no_channels, OWNED))
        self.pipeline.on_new = lambda opp_id: bus.publish("opportunity", opp_id)
        runtime = SimpleNamespace(**vars(directory()), events=bus)
        app = create_app(self.store, runtime, tokens=TOKENS)
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning",
                                                    lifespan="off"))
        self.serving = asyncio.create_task(self.server.serve())
        while not self.server.started:
            await asyncio.sleep(0.01)
        port = self.server.servers[0].sockets[0].getsockname()[1]
        self.client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=5)

    async def asyncTearDown(self):
        await self.client.aclose()
        self.server.should_exit = True
        await self.serving

    async def frames(self, token, out, ready):
        async with self.client.stream("GET", "/api/stream", headers=auth(token)) as r:
            event = None
            async for line in r.aiter_lines():
                if line.startswith("retry:"):
                    ready.set()
                elif line.startswith("event: "):
                    event = line[len("event: "):]
                elif line.startswith("data: "):
                    out.append((event, json.loads(line[len("data: "):]), time.monotonic()))

    async def test_a_new_matching_opportunity_reaches_its_users_stream_within_a_second_and_no_one_elses(self):
        kevin, friend = [], []
        ready_k, ready_f = asyncio.Event(), asyncio.Event()
        streams = [asyncio.create_task(self.frames(KEVIN, kevin, ready_k)),
                   asyncio.create_task(self.frames(FRIEND, friend, ready_f))]
        await asyncio.wait_for(asyncio.gather(ready_k.wait(), ready_f.wait()), 5)

        inserted = time.monotonic()
        await self.pipeline(None, [Item(source="ats.greenhouse.airbnb", external_id="ng", url="https://x.example/ng",
                                        title="Software Engineer, New Grad", company="Airbnb")])
        for _ in range(100):
            if kevin:
                break
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.3)  # give the friend's stream every chance to (wrongly) get it
        for task in streams:
            task.cancel()
        await asyncio.gather(*streams, return_exceptions=True)

        [(event, body, at)] = kevin
        self.assertEqual((event, body["title"], body["match"]["ok"]), ("opportunity", "Software Engineer, New Grad", True))
        self.assertLess(at - inserted, 1.0)
        self.assertEqual(friend, [], "airbnb is only on kevin's watchlist")

    async def test_the_stream_needs_a_token(self):
        r = await self.client.get("/api/stream")
        self.assertEqual(r.status_code, 401)

    async def test_friend_gets_a_later_sighting_of_an_already_stored_opportunity(self):
        friend, ready = [], asyncio.Event()
        task = asyncio.create_task(self.frames(FRIEND, friend, ready))
        try:
            await asyncio.wait_for(ready.wait(), 5)
            for source in ("ats.greenhouse.airbnb", "ats.greenhouse.point72"):
                await self.pipeline(None, [Item(source=source, external_id="ib", url="https://x.example/shared-ib",
                                                title="Investment Banking Summer Analyst", company="Point72")])
            for _ in range(100):
                if friend:
                    break
                await asyncio.sleep(0.01)
            self.assertEqual(len(friend), 1)
            self.assertEqual(friend[0][1]["sources"], ["ats.greenhouse.point72"])
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


class HealthAndMetricsTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_user_sees_only_their_own_sources_health_and_latency(self):
        store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(store.close)
        health = [{"name": n, "disabled": False, "running": False, "next_run": T0.isoformat(), "last_ok": None,
                   "fail_count": 0, "last_error": None, "items_24h": 0}
                  for n in ("ats.greenhouse.stripe", "ats.greenhouse.airbnb", "ats.greenhouse.point72")]
        runtime = SimpleNamespace(**vars(directory()))
        runtime.scheduler = SimpleNamespace(health=lambda: health)
        for source, eid in (("ats.greenhouse.airbnb", "a"), ("ats.greenhouse.point72", "p")):
            opp_id, _ = store.upsert_item(Item(source=source, external_id=eid, url=f"https://x.example/{eid}",
                                               title="t", seen_at=T0))
            store.record_alert(opp_id, "ntfy")
            store.mark_alert_sent(opp_id, "ntfy", T0 + timedelta(seconds=30), 30.0)
        app = create_app(store, runtime, tokens=TOKENS, now=lambda: T0 + timedelta(hours=1))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            names = [h["name"] for h in (await client.get("/api/sources/health", headers=auth(FRIEND))).json()]
            self.assertEqual(sorted(names), ["ats.greenhouse.point72", "ats.greenhouse.stripe"])
            m = (await client.get("/api/metrics", headers=auth(KEVIN))).json()
        self.assertEqual([x["source"] for x in m["latency"]], ["ats.greenhouse.airbnb"])
        self.assertEqual(m["items_per_day"], {T0.date().isoformat(): 1})


class OpenApiAndWebTests(unittest.IsolatedAsyncioTestCase):
    def test_committed_openapi_json_matches_the_app(self):
        """docs/openapi.json is what the web app generates its types from; regenerate
        with `python -m radar openapi > docs/openapi.json` when this fails. Compares
        routes and schema fields, not bytes, so a FastAPI upgrade's cosmetic output
        changes can't fail the hourly CI run this suite gates."""
        def shape(spec):
            routes = {(path, method) for path, ops in spec["paths"].items() for method in ops}
            schemas = {name: (sorted(s.get("properties", {})), sorted(s.get("required", [])))
                       for name, s in spec.get("components", {}).get("schemas", {}).items()}
            return routes, schemas
        committed = json.loads((Path(__file__).resolve().parent.parent / "docs" / "openapi.json").read_text())
        self.assertEqual(shape(committed), shape(create_app(None, tokens={}).openapi()))

    async def test_the_built_web_app_is_served_with_client_side_routes_falling_back_to_index(self):
        dist = Path(tempfile.mkdtemp())
        (dist / "index.html").write_text("<html>radar</html>")
        (dist / "assets").mkdir()
        (dist / "assets" / "app.js").write_text("console.log(1)")
        (dist.parent / "secret.txt").write_text("nope")
        app = create_app(None, tokens={}, web_dist=dist)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as client:
            self.assertEqual((await client.get("/assets/app.js")).text, "console.log(1)")
            self.assertEqual((await client.get("/pipeline")).text, "<html>radar</html>")
            self.assertEqual((await client.get("/")).text, "<html>radar</html>")
            self.assertNotIn("nope", (await client.get("/..%2Fsecret.txt")).text)
            self.assertEqual((await client.get("/api/nope")).status_code, 404)
            self.assertEqual((await client.get("/healthz")).json(), {"ok": True})
            # a release must reach browsers at once: the entry page always revalidates, hashed assets may be cached
            self.assertEqual((await client.get("/")).headers["cache-control"], "no-cache")
            self.assertEqual((await client.get("/pipeline")).headers["cache-control"], "no-cache")
            self.assertNotIn("cache-control", (await client.get("/assets/app.js")).headers)


if __name__ == "__main__":
    unittest.main()
