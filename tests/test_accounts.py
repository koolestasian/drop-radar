import tempfile
import unittest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path

import httpx

from radar.api.app import create_app
from radar.api.runtime import Runtime
from radar.config import load_settings
from radar.models import Item
from radar.store import Store

KEVIN = "k" * 24
PASSWORD = "correct horse battery"


class AccountTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        d = Path(tempfile.mkdtemp())
        (d / "users.yaml").write_text("users:\n  - {id: kevin, watchlist: w.yaml, profile: p.yaml}\n"
                                      "  - {id: friend, watchlist: w.yaml, profile: p.yaml}\n")
        (d / "w.yaml").write_text("companies: [{name: Stripe, ats: greenhouse, slug: stripe}]")
        (d / "p.yaml").write_text("roles: [software engineer]\nkeywords: [intern]")
        self.store = Store(d / "radar.db")
        self.addCleanup(self.store.close)
        self.opp, _ = self.store.upsert_item(Item(source="ats.greenhouse.stripe", external_id="swe", url="https://x.example/swe",
                                                  title="Software Engineer Intern", company="Stripe", location="New York, NY",
                                                  seen_at=datetime(2026, 9, 20, tzinfo=timezone.utc)))
        self.runtime = Runtime(self.store, settings=load_settings({}), users_path=d / "users.yaml", env={})
        self.app = create_app(self.store, self.runtime, tokens={KEVIN: "kevin"})
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://t")

    async def asyncTearDown(self):
        await self.client.aclose()

    async def signup(self, username="sam_smith", password=PASSWORD):
        return await self.client.post("/api/auth/signup", json={"username": username, "password": password})

    async def login(self, username, password):
        return await self.client.post("/api/auth/login", json={"username": username, "password": password})

    def bearer(self, token):
        return {"Authorization": f"Bearer {token}"}

    async def test_sign_up_then_the_session_token_works_and_the_password_is_never_stored(self):
        r = await self.signup()
        self.assertEqual(r.status_code, 201, r.text)
        token, me = r.json()["token"], r.json()["me"]
        self.assertTrue(me["user"].startswith("u_"))
        self.assertEqual((me["username"], me["guest"]), ("sam_smith", False))
        again = await self.client.get("/api/me", headers=self.bearer(token))
        self.assertEqual(again.json()["user"], me["user"])
        creds = self.store.get_credentials("sam_smith")
        self.assertTrue(creds["pw_hash"].startswith("scrypt$"))
        dump = "".join(self.store.conn.iterdump())
        self.assertNotIn(PASSWORD, dump)
        self.assertNotIn(token, dump)  # only the token's hash is stored

    async def test_login_works_and_unknown_user_and_wrong_password_look_the_same(self):
        await self.signup()
        ok = await self.login("SAM_Smith", PASSWORD)  # names are not case sensitive
        self.assertEqual(ok.status_code, 200, ok.text)
        wrong = await self.login("sam_smith", "not the password")
        unknown = await self.login("nobody_here", PASSWORD)
        self.assertEqual((wrong.status_code, unknown.status_code), (401, 401))
        self.assertEqual(wrong.json(), unknown.json())

    async def test_bad_usernames_and_passwords_are_refused_with_a_reason(self):
        for username, password, status in (("ab", PASSWORD, 422), ("has space", PASSWORD, 422), ("sam_smith", "short", 422),
                                           ("guest", PASSWORD, 422), ("kevin", PASSWORD, 409), ("friend", PASSWORD, 409),
                                           ("sam_smith", "x" * 129, 422)):
            with self.subTest(username=username, password=password[:6]):
                r = await self.signup(username, password)
                self.assertEqual(r.status_code, status, r.text)
        self.assertEqual(self.store.count_accounts(), 0)

    async def test_a_taken_username_is_a_409(self):
        self.assertEqual((await self.signup()).status_code, 201)
        self.assertEqual((await self.signup("Sam_Smith")).status_code, 409)

    async def test_logout_revokes_the_session(self):
        token = (await self.signup()).json()["token"]
        self.assertEqual((await self.client.post("/api/auth/logout", headers=self.bearer(token))).status_code, 204)
        self.assertEqual((await self.client.get("/api/config/profile", headers=self.bearer(token))).status_code, 401)

    async def test_accounts_have_private_statuses_and_see_the_shared_sources(self):
        a = (await self.signup("anna_a")).json()
        b = (await self.signup("ben_b")).json()
        self.assertEqual(a["me"]["sources"], 1)  # the shared set
        patch = await self.client.patch(f"/api/opportunities/{self.opp}", headers=self.bearer(a["token"]),
                                        json={"status": "saved", "notes": "anna only"})
        self.assertEqual(patch.status_code, 200, patch.text)
        theirs = await self.client.get(f"/api/opportunities/{self.opp}", headers=self.bearer(b["token"]))
        self.assertIsNone(theirs.json()["action"])
        self.assertNotIn("anna only", theirs.text)
        self.assertEqual(self.store.get_opportunity(self.opp, user_id=a["me"]["user"])["action"]["notes"], "anna only")

    async def test_an_account_edits_its_own_profile_in_the_database(self):
        token = (await self.signup()).json()["token"]
        body = {"roles": ["investment banking"], "keywords": ["intern"], "exclude": [], "locations": [], "company_tiers": {}}
        r = await self.client.put("/api/config/profile", headers=self.bearer(token), json=body)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["roles"], ["investment banking"])
        again = await self.client.get("/api/config/profile", headers=self.bearer(token))
        self.assertEqual(again.json()["roles"], ["investment banking"])
        bad = await self.client.put("/api/config/profile", headers=self.bearer(token), json={**body, "grad_year": 1800})
        self.assertEqual(bad.status_code, 422)

    async def test_the_first_user_stays_first_and_configured_tokens_still_work(self):
        await self.signup()
        self.assertEqual(next(iter(self.runtime.users)), "kevin")
        self.assertEqual((await self.client.get("/api/me", headers=self.bearer(KEVIN))).json()["user"], "kevin")

    async def test_a_configured_user_can_add_a_username_and_password_to_their_own_user(self):
        r = await self.client.put("/api/auth/credentials", headers=self.bearer(KEVIN),
                                  json={"username": "Kevin", "password": PASSWORD})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["me"]["user"], "kevin")
        again = await self.login("kevin", PASSWORD)
        self.assertEqual(again.json()["me"]["user"], "kevin")
        other = await self.client.put("/api/auth/credentials", headers=self.bearer(KEVIN),
                                      json={"username": "friend", "password": PASSWORD})
        self.assertEqual(other.status_code, 409)  # someone else's user id

    async def test_changing_a_password_signs_the_other_sessions_out(self):
        old = (await self.signup()).json()["token"]
        fresh = await self.client.put("/api/auth/credentials", headers=self.bearer(old),
                                      json={"username": "sam_smith", "password": "a brand new passphrase"})
        self.assertEqual(fresh.status_code, 200, fresh.text)
        self.assertEqual((await self.client.get("/api/config/profile", headers=self.bearer(old))).status_code, 401)
        self.assertEqual((await self.client.get("/api/config/profile", headers=self.bearer(fresh.json()["token"]))).status_code, 200)
        self.assertEqual((await self.login("sam_smith", PASSWORD)).status_code, 401)

    async def test_sign_up_and_login_are_rate_limited(self):
        for i in range(5):
            self.assertEqual((await self.signup(f"user_{i}")).status_code, 201)
        self.assertEqual((await self.signup("user_x")).status_code, 429)
        for _ in range(10):
            await self.login("sam_smith", "nope")
        self.assertEqual((await self.login("sam_smith", "nope")).status_code, 429)

    async def test_the_account_cap_closes_sign_up(self):
        import radar.api.app as app_module
        original, app_module.MAX_ACCOUNTS = app_module.MAX_ACCOUNTS, 1
        self.addCleanup(setattr, app_module, "MAX_ACCOUNTS", original)
        self.assertEqual((await self.signup("first_one")).status_code, 201)
        r = await self.signup("second_one")
        self.assertEqual(r.status_code, 503)

    async def test_the_reset_command_sets_a_new_password_and_signs_everyone_out(self):
        import contextlib
        import io
        from radar.__main__ import main
        token = (await self.signup()).json()["token"]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["reset-password", "Sam_Smith", "--db", str(self.store.conn.execute("PRAGMA database_list").fetchone()[2])])
        new = out.getvalue().split("new password ")[1].split(" ")[0]
        self.assertEqual((await self.client.get("/api/config/profile", headers=self.bearer(token))).status_code, 401)
        self.assertEqual((await self.login("sam_smith", new)).status_code, 200)
        self.assertEqual((await self.login("sam_smith", PASSWORD)).status_code, 401)

    async def test_an_account_turns_on_its_own_private_alerts_and_can_send_itself_a_test(self):
        a = (await self.signup("anna_a")).json()
        b = (await self.signup("ben_b")).json()
        self.assertFalse(a["me"]["alerts_enabled"])
        on = await self.client.post("/api/alerts/enable", headers=self.bearer(a["token"]))
        self.assertEqual(on.status_code, 200, on.text)
        topic_a = on.json()["notification_url"].rsplit("/", 1)[1]
        self.assertTrue(on.json()["alerts_enabled"])
        self.assertGreaterEqual(len(topic_a), 20)
        again = await self.client.post("/api/alerts/enable", headers=self.bearer(a["token"]))
        self.assertEqual(again.json()["notification_url"], on.json()["notification_url"])  # enabling twice keeps the topic
        other = await self.client.post("/api/alerts/enable", headers=self.bearer(b["token"]))
        self.assertNotEqual(other.json()["notification_url"], on.json()["notification_url"])
        self.assertNotIn(topic_a, other.text)
        with mock.patch("radar.alerts.requests.post") as post:
            post.return_value.status_code = 200
            r = await self.client.post("/api/alerts/test", headers=self.bearer(a["token"]))
        self.assertEqual(r.status_code, 204)
        self.assertEqual(post.call_args.kwargs["json"]["topic"], topic_a)
        off = await self.client.post("/api/alerts/disable", headers=self.bearer(a["token"]))
        self.assertFalse(off.json()["alerts_enabled"])
        self.assertEqual((await self.client.post("/api/alerts/test", headers=self.bearer(a["token"]))).status_code, 409)

    async def test_configured_users_keep_their_env_alerts_and_cannot_use_account_alert_routes(self):
        for path in ("/api/alerts/enable", "/api/alerts/disable"):
            r = await self.client.post(path, headers=self.bearer(KEVIN))
            self.assertEqual(r.status_code, 409, path)
        for path in ("/api/alerts/enable", "/api/alerts/test"):
            self.assertEqual((await self.client.post(path)).status_code, 401)  # no guests

    async def test_turning_alerts_on_never_pushes_postings_that_already_matched(self):
        token = (await self.signup()).json()["token"]
        self.assertTrue(self.store.get_opportunity(self.opp)["items"])  # a matching posting exists from before
        with mock.patch("radar.alerts.requests.post") as post:
            post.return_value.status_code = 200
            await self.client.post("/api/alerts/enable", headers=self.bearer(token))
            await self.runtime.pipeline.alerter.retry_pending()
            self.assertEqual(post.call_count, 0, "an old posting must not be pushed to a new channel")
            fresh = Item(source="ats.greenhouse.stripe", external_id="swe2", url="https://x.example/swe2", title="Software Engineer Intern, Payments",
                         company="Stripe", location="New York, NY", seen_at=datetime(2026, 9, 21, tzinfo=timezone.utc))
            await self.runtime.pipeline(self.runtime.scheduler.sources["ats.greenhouse.stripe"], [fresh])
        self.assertEqual(post.call_count, 1)  # only the new one, only to this account (kevin has no topic here)

    async def test_the_daily_caps_stop_account_pushes_but_not_the_feed(self):
        import radar.alerts as alerts
        token = (await self.signup()).json()["token"]
        original = alerts.ACCOUNT_DAILY_PUSHES
        alerts.ACCOUNT_DAILY_PUSHES = 1
        self.addCleanup(setattr, alerts, "ACCOUNT_DAILY_PUSHES", original)
        with mock.patch("radar.alerts.requests.post") as post:
            post.return_value.status_code = 200
            await self.client.post("/api/alerts/enable", headers=self.bearer(token))
            source = self.runtime.scheduler.sources["ats.greenhouse.stripe"]
            for n in range(3):
                item = Item(source="ats.greenhouse.stripe", external_id=f"cap{n}", url=f"https://x.example/cap{n}",
                            title=f"Software Engineer Intern {n}", company="Stripe", location="New York, NY",
                            seen_at=datetime(2026, 9, 21, tzinfo=timezone.utc))
                await self.runtime.pipeline(source, [item])
        self.assertEqual(post.call_count, 1)

    async def test_expired_sessions_stop_working(self):
        token = (await self.signup()).json()["token"]
        self.store.conn.execute("UPDATE sessions SET created_at = '2000-01-01T00:00:00+00:00'")
        self.store.conn.commit()
        self.assertEqual((await self.client.get("/api/config/profile", headers=self.bearer(token))).status_code, 401)


if __name__ == "__main__":
    unittest.main()
