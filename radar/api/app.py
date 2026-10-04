"""FastAPI app over the store (T8b).

create_app(store, runtime): `runtime` provides `.users` and `.owned` (user id ->
their own source names) and, in production, a `.scheduler` the app's lifespan
runs for as long as the server is up -- one process, as 00-overview.md says.
Tests pass a plain namespace with no scheduler, so nothing polls.

Every user sees only what their own sources found ("fully separate profiles");
what's in their feed and what alerts their phone are decided by the same
radar.alerts.visible_to. Another user's opportunity is a 404, not a 403, so its
existence doesn't leak.

Handlers that touch the store are `async def`: its sqlite3 connection belongs
to the event loop's thread, and FastAPI runs a plain `def` handler in a pool.
"""
import asyncio
import base64
import dataclasses
import hmac
import json
import logging
import os
import re
import secrets
import signal
import sqlite3
import tempfile
import time
from collections import Counter
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from urllib.parse import quote

import yaml
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse

from radar.alerts import DEAD_STATUSES, NtfyChannel, visible_to
from radar.pipeline import roles
from radar.pipeline.pay_estimate import estimate_pay
from radar.api import auth, events
from radar.api.models import (Action, ActionPatch, AuthResult, Counts, Credentials, InstagramRelay, Login, Match, Me, Metrics, Opportunity, Page, ProfileConfig,
                              SourceHealth, SourceLatency, Summary, WatchlistConfig)
from radar.config import GUEST_ID, User, Watchlist, load_guest_profile, load_settings, parse_profile, parse_watchlist
from radar.errors import ConfigError
from radar.sources.registry import build_sources
from radar.store import Store
from radar.logos import LogoResolver
from radar.models import utcnow
from radar.pipeline.filter import is_us_location
from radar.pipeline.normalize import canonical_company
from radar.pipeline.places import format_location
from radar.pipeline.enrich import DEFAULT_DAILY_TOKEN_BUDGET
from radar.sources.instagram import story_id
from radar.stats import latency_by_source

log = logging.getLogger(__name__)
TIER_RANK = {"S": 3, "A": 2, "B": 1, "C": 0}
HIDDEN_BY_DEFAULT = "ignored"  # a user's own ignored opportunities leave their feed unless asked for
WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


def _encode_cursor(key):
    """key: (sort_key, id) of the last item on the page."""
    return base64.urlsafe_b64encode(json.dumps(list(key)).encode()).decode()


def _decode_cursor(cursor):
    try:
        sort_key, opp_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return str(sort_key), str(opp_id)
    except Exception:
        raise HTTPException(400, "bad cursor") from None


def _deadline(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


EDITED_HEADER = "# Edited through the API (radar.api); validated by radar.config. Hand-written comments are not kept.\n"


def _has_terms(text, terms):
    """Every term starts a word somewhere: "ny" finds "New York, NY", not "Sunnyvale"."""
    return all(re.search(rf"(?<![a-z0-9]){re.escape(t)}", text, re.I) for t in terms)


def _ranks(user):
    """Prestige per company for this user: watchlist tiers, overridden by profile.company_tiers.
    B (the default rank) is left out unless an override says so."""
    tiers = {canonical_company(c.name).lower(): c.tier for c in user.watchlist.companies if c.tier != "B"}
    tiers.update({canonical_company(n).lower(): t for n, t in user.profile.company_tiers.items()})
    return {name: TIER_RANK[t] for name, t in tiers.items()}


def _atomic_write(path, text):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


MAX_ACCOUNTS = 300  # accounts people made themselves; the box is small
SESSION_DAYS = 90
# What an account may add to the shared set. Only boards whose host is fixed by the kind (the slug becomes a path
# or a fixed-domain subdomain), so a stranger's input can never make the box fetch an arbitrary address.
ACCOUNT_ATS = ("greenhouse", "lever", "ashby", "smartrecruiters", "workday")
MAX_EXTRA_COMPANIES = 10        # per account
MAX_EXTRA_COMPANIES_TOTAL = 200  # across all accounts: each is one more board the single poller must visit
_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_WORKDAY_SLUG = re.compile(r"^[A-Za-z0-9_-]{1,40}\.wd\d{1,2}/[A-Za-z0-9_-]{1,80}$")


async def probe_company(company):
    """None if the board answers with open postings, else a sentence saying what is wrong."""
    import httpx

    from radar.sources.discover import _check_one
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            _, _, status = await asyncio.wait_for(_check_one(client, company), 25)
    except Exception:
        return "didn't answer in time"
    if status.startswith("200 OK"):
        return None
    if "404" in status:
        return "no board with that name was found"
    if "EMPTY" in status:
        return "has no postings (a wrong name, or nothing open right now)"
    return "couldn't be read right now"


def create_app(store, runtime=None, tokens=None, now=utcnow, web_dist=WEB_DIST, crash_exit=None):
    tokens = load_settings().api_tokens if tokens is None else tokens
    bus = getattr(runtime, "events", None) or events.EventBus()
    if runtime is not None and not tokens:
        log.warning("API_TOKENS is empty: every /api request will be refused")
    # A crashed scheduler must take the process down with it, or systemd's Restart=always
    # never fires -- uvicorn would otherwise keep serving a process that stopped polling.
    crash_exit = crash_exit or (lambda: os.kill(os.getpid(), signal.SIGTERM))
    logos = LogoResolver(store)

    def _log_crash(task):
        if task.cancelled() or task.exception() is None:
            return
        log.error("scheduler stopped", exc_info=task.exception())
        crash_exit()

    @asynccontextmanager
    async def lifespan(app):
        stop, task, logo_task = asyncio.Event(), None, None
        if getattr(runtime, "scheduler", None) is not None:
            task = asyncio.create_task(runtime.scheduler.run(stop))
            task.add_done_callback(_log_crash)
            logo_task = asyncio.create_task(logos.run(stop))  # production only: tests stay offline
        try:
            yield
        finally:
            if task is not None:
                stop.set()  # Scheduler.run drains in-flight fetches before returning
                await asyncio.gather(task, logo_task, return_exceptions=True)

    app = FastAPI(title="Drop Radar", lifespan=lifespan)
    app.state.store, app.state.runtime = store, runtime

    def _session_cutoff():
        return (now() - timedelta(days=SESSION_DAYS)).isoformat()

    async def current_user(authorization: str = Header(default="")) -> User:
        scheme, _, given = authorization.partition(" ")
        given = given.strip().encode()
        user_id = None
        if scheme.lower() == "bearer" and given:
            # every secret is compared, in constant time, so timing doesn't say how close a guess was
            for secret, uid in tokens.items():
                if hmac.compare_digest(secret.encode(), given):
                    user_id = uid
            if user_id is None:  # not a configured secret: a login session (only its hash is stored)
                user_id = store.session_user(auth.hash_token(given.decode(errors="replace")), _session_cutoff())
        user = getattr(runtime, "users", {}).get(user_id) if user_id else None
        if user is None:
            raise HTTPException(401, "missing or invalid bearer token", headers={"WWW-Authenticate": "Bearer"})
        return user

    guest = User(id=GUEST_ID, watchlist=Watchlist(), profile=load_guest_profile())
    summaries = {}  # user id -> (time, Summary), 5 min: a scan takes seconds
    hits, cached = {}, {}  # guest rate limit (ip -> request times) and 60s response cache (query -> (time, page))

    def _client_ip(request):
        # the app listens on localhost behind Caddy, which appends the address it saw: the last entry is its own
        return request.headers.get("x-forwarded-for", "").split(",")[-1].strip() or (request.client.host if request.client else "?")

    def throttle(key, limit, window_s, message="too many attempts; try again later"):
        """At most `limit` hits per `window_s` for this key, else 429."""
        now_s = time.monotonic()
        recent = [t for t in hits.get(key, ()) if now_s - t < window_s]
        if len(recent) >= limit:
            raise HTTPException(429, message, headers={"Retry-After": str(window_s)})
        hits[key] = recent + [now_s]
        if len(hits) > 4000:  # a flood of fresh keys can't grow this without bound
            for k in [k for k, v in hits.items() if not v or now_s - v[-1] >= 3600]:
                del hits[k]

    async def viewer(request: Request, authorization: str = Header(default="")) -> User:
        """The logged-in user, or the read-only guest when no token is sent. A token that is sent
        and wrong is still a 401, so a signed-out or stale device is told to sign in again."""
        if authorization.strip():
            return await current_user(authorization)
        throttle(("guest", _client_ip(request)), 60, 60, "too many requests; sign in or slow down")
        return guest

    def owned(user):
        if user.id == GUEST_ID:  # visitors see everything any user's sources found
            return frozenset().union(*getattr(runtime, "owned", {}).values())
        return runtime.owned.get(user.id, frozenset())

    def serialize(opp, user):
        mine = owned(user)
        _, ok, reasons = visible_to(opp, user.profile, mine)
        fields, action = opp["fields"], opp.get("action")
        pay = fields.get("Pay", "")
        pay_estimate, pay_estimate_basis = estimate_pay(opp["title"], opp["location"]) if not pay else ("", "")
        seen_by_me = [i for i in opp["items"] if i["source"] in mine]
        return Opportunity(
            id=opp["id"], title=opp["title"], company=opp["company"], location=format_location(opp["location"]),
            location_raw=opp["location"], url=opp["url"],
            deadline=opp["deadline"], status=opp["status"], first_seen=opp["first_seen"],
            published_at=opp["published_at"], category=fields.get("Category", ""),
            role_track=fields.get("Role / Track", ""), level=roles.level(opp["title"], fields.get("Category", "")),
            track=roles.track(opp["title"], fields.get("Role / Track", "")), season=fields.get("Season / Year", ""), pay=pay,
            pay_estimate=pay_estimate, pay_estimate_basis=pay_estimate_basis,
            sources=sorted({i["source"] for i in seen_by_me}),
            backfill=bool(seen_by_me) and all(json.loads(i["raw"] or "{}").get("seed") for i in seen_by_me),
            match=Match(ok=ok, reasons=reasons),
            action=Action(status=action["status"], notes=action["notes"]) if action else None,
            company_domain=logos.domain(opp["company"]),
        )

    def visible_opportunity(opp_id, user):
        opp = store.get_opportunity(opp_id, user_id=user.id)
        if opp is None or not visible_to(opp, user.profile, owned(user))[0]:
            raise HTTPException(404, "no such opportunity")
        return opp

    @app.get("/healthz")
    async def healthz():
        """Liveness only -- no data, no auth."""
        return {"ok": True}

    def me_for(user):
        if user.id == GUEST_ID:
            return Me(user=GUEST_ID, sources=len(owned(user)), alerts_enabled=False, notification_url=None, guest=True)
        creds = store.credentials_for(user.id)
        pipeline = getattr(runtime, "pipeline", None)
        dispatchers = getattr(getattr(pipeline, "alerter", None), "dispatchers", {})
        channels = getattr(dispatchers.get(user.id), "channels", [])
        url = next((f"{c.server}/{quote(c.topic, safe='')}" for c in channels if isinstance(c, NtfyChannel)), None)
        return Me(user=user.id, sources=len(owned(user)), alerts_enabled=bool(channels), notification_url=url,
                  username=creds["username"] if creds else None, account=store.is_account(user.id))

    @app.get("/api/me", response_model=Me)
    async def me(user: User = Depends(viewer)):
        return me_for(user)

    def _session_for(user):
        token, digest = auth.new_session_token()
        store.add_session(digest, user.id)
        return AuthResult(token=token, me=me_for(user))

    def _check_new_credentials(body, own_id=None):
        username = auth.normalize_username(body.username)
        problem = auth.username_problem(username) or auth.password_problem(body.password)
        if problem:
            raise HTTPException(422, problem)
        taken = getattr(runtime, "users", {})
        if username in taken and username != own_id:  # users.yaml ids are only theirs to claim
            raise HTTPException(409, "That username is taken.")
        return username

    @app.post("/api/auth/signup", response_model=AuthResult, status_code=201)
    async def signup(body: Credentials, request: Request):
        if not hasattr(runtime, "reload"):
            raise HTTPException(503, "accounts can only be created on the running server")
        username = _check_new_credentials(body)  # typos are free; only an attempt that would create an account counts
        if store.count_accounts() >= MAX_ACCOUNTS:
            raise HTTPException(503, "Sign-up is full right now.")
        throttle(("signup", _client_ip(request)), 5, 3600, "Too many sign-ups from here; try again in an hour.")
        pw_hash = await auth.hash_password_async(body.password)
        account_id = "u_" + secrets.token_hex(5)
        try:
            store.create_account(account_id, {}, username, pw_hash)
        except sqlite3.IntegrityError:
            raise HTTPException(409, "That username is taken.") from None
        runtime.reload()
        return _session_for(runtime.users[account_id])

    @app.post("/api/auth/login", response_model=AuthResult)
    async def login(body: Login, request: Request):
        username = auth.normalize_username(body.username)
        throttle(("login-ip", _client_ip(request)), 20, 600)
        throttle(("login-user", username), 10, 600)
        creds = store.get_credentials(username)
        ok = await auth.check_password_async(body.password, creds["pw_hash"] if creds else auth.DUMMY_HASH)
        user = getattr(runtime, "users", {}).get(creds["user_id"]) if creds and ok else None
        if user is None:  # unknown name, wrong password and a removed user all look the same
            raise HTTPException(401, "Wrong username or password.")
        return _session_for(user)

    @app.post("/api/auth/logout", status_code=204)
    async def logout(authorization: str = Header(default=""), user: User = Depends(current_user)):
        store.delete_session(auth.hash_token(authorization.partition(" ")[2].strip()))  # a configured token has no session

    @app.put("/api/auth/credentials", response_model=AuthResult)
    async def set_credentials(body: Credentials, request: Request, user: User = Depends(current_user)):
        """Set or change your own username and password; your other sessions are signed out."""
        throttle(("credentials", user.id), 10, 3600)
        username = _check_new_credentials(body, own_id=user.id)
        pw_hash = await auth.hash_password_async(body.password)
        try:
            store.set_credentials(user.id, username, pw_hash)
        except sqlite3.IntegrityError:
            raise HTTPException(409, "That username is taken.") from None
        store.delete_user_sessions(user.id)
        return _session_for(user)

    def _account_only(user):
        if not store.is_account(user.id):
            raise HTTPException(409, "Your alerts are set up by whoever runs this radar.")

    @app.post("/api/alerts/enable", response_model=Me)
    async def alerts_enable(user: User = Depends(current_user)):
        """Give this account its own private ntfy topic (unguessable; the link in Settings is the subscription)."""
        _account_only(user)
        topic = next((r["ntfy_topic"] for r in store.list_accounts() if r["id"] == user.id), None)
        if not topic:
            store.save_account(user.id, ntfy_topic="dr-" + secrets.token_urlsafe(18))
            runtime.reload()
        return me_for(runtime.users[user.id])

    @app.post("/api/alerts/disable", response_model=Me)
    async def alerts_disable(user: User = Depends(current_user)):
        _account_only(user)
        store.save_account(user.id, ntfy_topic=None)
        runtime.reload()
        return me_for(runtime.users[user.id])

    @app.post("/api/alerts/test", status_code=204)
    async def alerts_test(user: User = Depends(current_user)):
        """One real push to your own topic, so you can see that your phone receives them."""
        throttle(("alert-test", user.id), 3, 3600, "Three test pushes an hour is plenty; try again later.")
        dispatchers = getattr(getattr(getattr(runtime, "pipeline", None), "alerter", None), "dispatchers", {})
        channels = getattr(dispatchers.get(user.id), "channels", [])
        if not channels:
            raise HTTPException(409, "Turn on phone alerts first.")
        sample = {"company": "Drop Radar", "title": "Test notification", "location": "If you can read this, alerts work.",
                  "deadline": "", "items": [], "url": ""}
        try:
            await asyncio.to_thread(channels[0].send, sample, [], None)
        except Exception:
            log.warning("test push failed for %s", user.id, exc_info=True)
            raise HTTPException(502, "The push service didn't accept it. Try again in a minute.") from None

    @app.post("/api/instagram/relay")
    async def relay_instagram(body: InstagramRelay, user: User = Depends(current_user)):
        from dataclasses import replace

        if user.id != next(iter(runtime.users)):
            raise HTTPException(403, "only the owner may relay Instagram")
        scheduler = getattr(runtime, "scheduler", None)
        source = scheduler.sources.get(f"instagram.{body.username}") if scheduler else None
        if source is None or not getattr(source, "external", False):
            raise HTTPException(409, "this account is not configured for Instagram relay")
        if any(not isinstance(raw.get("pk") or raw.get("id"), (str, int))
               or not str(raw.get("pk") or raw.get("id") or "").strip() for raw in body.stories):
            raise HTTPException(422, "every Story needs a stable id")
        state = store.get_source_state(source.name) or {}
        fresh = 0
        for raw in body.stories:
            if store.item_opportunity_id(source.name, story_id(raw)) is not None:
                continue  # stored already: skip its OCR (the text cache is empty after a restart)
            items = await source._to_items([raw], scheduler.context(source.name))
            for item in items:
                if store.item_opportunity_id(item.source, item.external_id) is not None:
                    continue
                if not state.get("last_ok"):
                    item = replace(item, raw={**item.raw, "seed": True})
                await runtime.pipeline(source, [item])
                fresh += 1
        at = now()
        store.save_source_state(source.name, last_ok=at, fail_count=0, last_error=None,
                                next_run=at + timedelta(seconds=source.interval_s))
        return {"received": len(body.stories), "new": fresh, "backfill": not bool(state.get("last_ok"))}

    @app.get("/api/opportunities", response_model=Page)
    async def list_opportunities(
        request: Request,
        user: User = Depends(viewer),
        include: str = Query("matches", pattern="^(matches|all)$",
                             description="matches: what would alert you; all: everything your sources found"),
        q: str | None = Query(None, description="words that each start a word in the title or company"),
        location: str | None = Query(None, description="words that each start a word in the location ('seattle', 'ny')"),
        us_only: bool = Query(False, description="only postings whose location is confirmed US (blank and "
                                                  "location-less 'Remote' are left out)"),
        company: str | None = None,
        source: str | None = None,
        action: str | None = Query(None, description="your status; 'ignored' ones are hidden unless asked for"),
        status: str | None = Query(None, description="the posting's own status (New, Open, Closed...); "
                                                      "Closed/Expired/Not actionable are hidden unless asked for"),
        since: datetime | None = Query(None, description="first seen at or after"),
        closing_within: int | None = Query(None, ge=0, description="deadline within this many days"),
        sort: str = Query("posted", pattern="^(posted|found|prestige)$",
                          description="newest first by when it was posted (date-only postings count as that "
                                      "day; none at all falls back to found), by when your sources found it, "
                                      "or by company prestige (S > A > B > C tiers), newest posted within a tier"),
        backfill: bool | None = Query(None, description="false: only new drops; true: only postings that were "
                                                         "already open when your sources first looked"),
        level: str | None = Query(None, pattern="^(intern|new_grad)$", description="internships or new-grad roles"),
        track: str | None = Query(None, description="one of: " + ", ".join(roles.TRACK_NAMES)),
        posted_within: int | None = Query(None, ge=0, description="posted this many days back or less (the posting "
                                                                  "date, else a live drop's found time; undated "
                                                                  "backfill never matches)"),
        cursor: str | None = None,
        limit: int = Query(50, ge=1, le=200),
    ):
        # ponytail: scores every candidate in Python per request (one row fetch each);
        # fine for two users and thousands of rows -- precompute per-user matches if it slows.
        if track is not None and track not in roles.TRACK_NAMES:
            raise HTTPException(422, f"track must be one of {roles.TRACK_NAMES}")
        is_guest = user.id == GUEST_ID
        if is_guest:  # every visitor's page is the same: cap it, ignore personal filters, reuse it for a minute
            limit, action = min(limit, 50), None
            hit = cached.get(request.url.query)
            if hit and time.monotonic() - hit[0] < 60:
                return hit[1]
        after = _decode_cursor(cursor) if cursor else None
        today = now().date()
        items, keys, more, seen = [], [], None, set()
        terms, places = (q or "").split(), (location or "").split()
        for row in store.list_opportunities(status=status, since=since, source_names=owned(user),
                                              backfill=backfill, sort=sort, ranks=_ranks(user)):
            # one card per job: Invesco posts the same "Business Trainee, Hyderabad" as five requisitions.
            # Checked before the cursor so every page agrees on which copy is the one shown.
            twin = (row["company"].lower(), row["title"].lower().strip(), row["location"].lower().strip())
            if twin in seen:
                continue
            seen.add(twin)
            if after and (row["sort_key"], row["id"]) >= after:
                continue
            # filters the row alone can answer run before the per-row fetch below
            if terms and not _has_terms(f"{row['title']} {row['company']}", terms):
                continue
            if places and not _has_terms(row["location"], places):
                continue
            if company and company.lower() not in row["company"].lower():
                continue
            if us_only and is_us_location(row["location"]) is not True:
                continue
            opp = store.get_opportunity(row["id"], user_id=user.id)
            mine = opp.get("action") or {}
            if action is not None and mine.get("status") != action:
                continue
            if action is None and mine.get("status") == HIDDEN_BY_DEFAULT:
                continue
            if action is None and status is None and opp["status"] in DEAD_STATUSES:
                continue
            if source and source not in {i["source"] for i in opp["items"]}:
                continue
            if closing_within is not None:
                due = _deadline(opp["deadline"])
                if due is None or not today <= due <= today + timedelta(days=closing_within):
                    continue
            out = serialize(opp, user)
            if not out.sources:  # belt and braces: never rely on the SQL pre-filter alone
                continue
            if include == "matches" and not out.match.ok:
                continue
            if (level and out.level != level) or (track and out.track != track):
                continue
            if posted_within is not None:
                posted = out.published_at or ("" if out.backfill else out.first_seen)
                if not posted or datetime.fromisoformat(posted).date() < today - timedelta(days=posted_within):
                    continue
            if len(items) == limit:
                more = keys[-1]
                break
            items.append(out)
            keys.append((row["sort_key"], row["id"]))
        next_cursor = _encode_cursor(more) if more else None
        page = Page(items=items, next_cursor=next_cursor)
        if is_guest:
            if len(cached) >= 256:
                cached.clear()
            cached[request.url.query] = (time.monotonic(), page)
        return page

    @app.get("/api/opportunities/summary", response_model=Summary)
    async def summary(user: User = Depends(viewer)):
        """The numbers behind the Jobs header and filter pills, over everything the list would show."""
        hit = summaries.get(user.id)
        if hit and time.monotonic() - hit[0] < 300:
            return await asyncio.shield(hit[1])  # one scan at a time per user; a burst of visitors shares it
        mine, path = owned(user), store.conn.execute("PRAGMA database_list").fetchone()["file"]

        def scan():  # its own connection on a worker thread: ~6 s of reading must not stall live updates
            you, everything, seen = Counter(), Counter(), set()
            with Store(path) as db:
                # the list's order, so the same copy of a twin is the one counted
                for row in db.list_opportunities(source_names=mine, sort="posted"):
                    twin = (row["company"].lower(), row["title"].lower().strip(), row["location"].lower().strip())
                    if twin in seen:
                        continue
                    seen.add(twin)
                    opp = db.get_opportunity(row["id"], user_id=user.id)
                    if (opp.get("action") or {}).get("status") == HIDDEN_BY_DEFAULT or opp["status"] in DEAD_STATUSES:
                        continue
                    if not any(i["source"] in mine for i in opp["items"]):
                        continue
                    ok = visible_to(opp, user.profile, mine)[1]
                    lvl, trk = roles.level(opp["title"], opp["fields"].get("Category", "")), roles.track(opp["title"], opp["fields"].get("Role / Track", ""))
                    for scope in (everything, you) if ok else (everything,):
                        scope["total"] += 1
                        if lvl:
                            scope["level:" + lvl] += 1
                        scope["track:" + trk] += 1
            return you, everything

        def counts(c):
            return Counts(total=c["total"], level={k[6:]: n for k, n in c.items() if k.startswith("level:")},
                          track={k[6:]: n for k, n in c.items() if k.startswith("track:")})

        async def build():
            you, everything = await asyncio.to_thread(scan)
            return Summary(you=counts(you), everything=counts(everything))

        task = asyncio.ensure_future(build())
        summaries[user.id] = (time.monotonic(), task)
        try:
            return await asyncio.shield(task)
        except Exception:
            summaries.pop(user.id, None)  # a failed scan is not cached
            raise

    @app.get("/api/opportunities/{opp_id}", response_model=Opportunity)
    async def get_opportunity(opp_id: str, user: User = Depends(viewer)):
        return serialize(visible_opportunity(opp_id, user), user)

    @app.patch("/api/opportunities/{opp_id}", response_model=Opportunity)
    async def update_opportunity(opp_id: str, patch: ActionPatch, user: User = Depends(current_user)):
        visible_opportunity(opp_id, user)
        if patch.status is not None or patch.notes is not None:
            store.set_action(opp_id, user.id, status=patch.status, notes=patch.notes)
            bus.publish("action", opp_id, user.id)
        return serialize(store.get_opportunity(opp_id, user_id=user.id), user)

    def replace_config(user, kind, data, parse, path):
        """Validate alone, write, reload; if the reload fails (the edit clashes with
        another user's config, e.g. the shared Instagram cap) put the file back.
        Nothing here awaits, so no other request sees the half-done state."""
        try:
            parse(data, f"{user.id}'s {kind}")
        except ConfigError as exc:
            raise HTTPException(422, str(exc)) from None
        if path is None or not hasattr(runtime, "reload"):
            raise HTTPException(503, "config can only be edited on the running server")
        before = path.read_text(encoding="utf-8")
        _atomic_write(path, EDITED_HEADER + yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
        try:
            runtime.reload()
        except (ConfigError, ValueError) as exc:
            _atomic_write(path, before)
            raise HTTPException(422, str(exc)) from None
        except Exception:
            _atomic_write(path, before)
            raise

    def watchlist_out(user):
        return WatchlistConfig(**dataclasses.asdict(user.watchlist))

    @app.get("/api/config/watchlist", response_model=WatchlistConfig)
    async def get_watchlist(user: User = Depends(current_user)):
        return watchlist_out(user)

    async def put_account_watchlist(body, user):
        """An account's extra companies, kept in the database. Companies only, on the allowed boards, capped,
        and each board not already polled is probed once so a typo can't become a source polled forever."""
        throttle(("watchlist", user.id), 20, 3600, "That's a lot of edits; try again in a while.")
        if body.instagram or body.feeds or body.repos:
            raise HTTPException(422, "Accounts can add companies only.")
        if len(body.companies) > MAX_EXTRA_COMPANIES:
            raise HTTPException(422, f"You can add up to {MAX_EXTRA_COMPANIES} extra companies.")
        seen = set()
        for c in body.companies:
            where = f"{c.name or 'a company'} ({c.ats})"
            if c.ats not in ACCOUNT_ATS:
                raise HTTPException(422, f"{where}: boards of that kind can't be added. Use one of: {', '.join(ACCOUNT_ATS)}.")
            if not (_WORKDAY_SLUG if c.ats == "workday" else _SLUG).match(c.slug):
                raise HTTPException(422, f"{where}: the slug looks wrong. Copy just the board name from its address, not the whole link.")
            if not c.name.strip() or len(c.name) > 60 or not c.name.isprintable():
                raise HTTPException(422, f"{where}: give the company a short name.")
            if (c.ats, c.slug.lower()) in seen:
                raise HTTPException(422, f"{where}: listed twice.")
            seen.add((c.ats, c.slug.lower()))
        try:
            parse_watchlist(body.model_dump(), f"{user.id}'s watchlist")
        except ConfigError as exc:
            raise HTTPException(422, str(exc)) from None
        others = sum(len(json.loads(r["watchlist"] or "{}").get("companies") or [])
                     for r in store.list_accounts() if r["id"] != user.id)
        if others + len(body.companies) > MAX_EXTRA_COMPANIES_TOTAL:
            raise HTTPException(503, "Extra companies are full right now.")
        polled = set(getattr(getattr(runtime, "scheduler", None), "sources", {}))
        for c in body.companies:
            names = {s.name for s in build_sources(Watchlist(companies=(c,)))[0]}
            if names <= polled:
                continue  # somebody already watches this board: nothing new to poll, nothing to probe
            problem = await probe_company(c)
            if problem:
                raise HTTPException(422, f"{c.name} ({c.ats}, '{c.slug}'): {problem}. Check the slug in the board's address.")
        store.save_account(user.id, watchlist={"companies": [c.model_dump() for c in body.companies]})
        runtime.reload()
        return watchlist_out(runtime.users[user.id])

    @app.put("/api/config/watchlist", response_model=WatchlistConfig)
    async def put_watchlist(body: WatchlistConfig, user: User = Depends(current_user)):
        if store.is_account(user.id):
            return await put_account_watchlist(body, user)
        replace_config(user, "watchlist", body.model_dump(), parse_watchlist, user.watchlist_path)
        return watchlist_out(runtime.users[user.id])

    @app.get("/api/config/profile", response_model=ProfileConfig)
    async def get_profile(user: User = Depends(current_user)):
        return ProfileConfig(**dataclasses.asdict(user.profile))

    @app.put("/api/config/profile", response_model=ProfileConfig)
    async def put_profile(body: ProfileConfig, user: User = Depends(current_user)):
        if store.is_account(user.id):  # accounts live in the database, not in a config file
            try:
                parse_profile(body.model_dump(), f"{user.id}'s profile")
            except ConfigError as exc:
                raise HTTPException(422, str(exc)) from None
            store.save_account(user.id, profile=body.model_dump())
            runtime.reload()
        else:
            replace_config(user, "profile", body.model_dump(), parse_profile, user.profile_path)
        return ProfileConfig(**dataclasses.asdict(runtime.users[user.id].profile))

    @app.get("/api/stream", response_class=StreamingResponse,
             responses={200: {"content": {"text/event-stream": {}},
                              "description": "SSE: `opportunity` (a new one in your feed) and `action` (yours changed)"}})
    async def stream(request: Request, user: User = Depends(current_user)):
        def render(kind, opp_id):
            opp = store.get_opportunity(opp_id, user_id=user.id)
            if opp is None:
                return None
            owned_it, matches, _ = visible_to(opp, user.profile, owned(user))
            if not owned_it or (kind == "opportunity" and not matches):
                return None
            return serialize(opp, user).model_dump()

        queue = bus.subscribe()

        async def frames():
            try:
                async for frame in events.stream(queue, user.id, render, request.is_disconnected):
                    yield frame
            finally:
                bus.unsubscribe(queue)

        return StreamingResponse(frames(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/api/sources/health", response_model=list[SourceHealth])
    async def sources_health(user: User = Depends(current_user)):
        scheduler = getattr(runtime, "scheduler", None)
        mine = owned(user)
        return [h for h in (scheduler.health() if scheduler else []) if h["name"] in mine]

    @app.get("/api/metrics", response_model=Metrics)
    async def metrics(user: User = Depends(current_user)):
        mine = sorted(owned(user))
        channel = "ntfy" if user.id == next(iter(runtime.users)) else f"ntfy:{user.id}"
        latency = [SourceLatency(source=source, **s) for source, s in latency_by_source(store, channel=channel).items()
                   if source in owned(user)]
        since = (now() - timedelta(days=7)).date().isoformat()
        rows = store.conn.execute(
            f"SELECT substr(seen_at, 1, 10), count(*) FROM items WHERE seen_at >= ? "
            f"AND source IN ({', '.join('?' * len(mine)) or 'NULL'}) GROUP BY 1 ORDER BY 1",
            [since, *mine],
        ).fetchall()
        spent = (store.get_enrichment(f"llm_budget:{now().date().isoformat()}") or {}).get("tokens", 0)
        return Metrics(latency=latency, items_per_day={d: n for d, n in rows},
                       llm_tokens_today=spent, llm_daily_budget=DEFAULT_DAILY_TOKEN_BUDGET)

    if Path(web_dist, "index.html").is_file():
        root = Path(web_dist).resolve()

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            """The built web app (T9): a real file if there is one, else index.html for client routes."""
            if path.startswith("api/"):
                raise HTTPException(404)
            candidate = (root / path).resolve()
            if path and candidate.is_file() and candidate.is_relative_to(root):  # no ../ escapes
                # assets/ files are named by content hash, so they never go stale; everything else (index.html,
                # sw.js, the manifest) must be re-checked, or a browser keeps the old app for hours after a release
                return FileResponse(candidate, headers={} if path.startswith("assets/") else {"Cache-Control": "no-cache"})
            return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})

    return app
