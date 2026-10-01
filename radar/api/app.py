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
import tempfile
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta

import yaml
from fastapi import Depends, FastAPI, Header, HTTPException, Query

from radar.alerts import visible_to
from radar.api.models import Action, ActionPatch, Match, Me, Opportunity, Page, ProfileConfig, WatchlistConfig
from radar.config import User, load_settings, parse_profile, parse_watchlist
from radar.errors import ConfigError
from radar.models import utcnow

log = logging.getLogger(__name__)
HIDDEN_BY_DEFAULT = "ignored"  # a user's own ignored opportunities leave their feed unless asked for


def _log_crash(task):
    if not task.cancelled() and task.exception() is not None:
        log.error("scheduler stopped", exc_info=task.exception())


def _encode_cursor(opp):
    return base64.urlsafe_b64encode(json.dumps([opp["first_seen"], opp["id"]]).encode()).decode()


def _decode_cursor(cursor):
    try:
        first_seen, opp_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return str(first_seen), str(opp_id)
    except Exception:
        raise HTTPException(400, "bad cursor") from None


def _deadline(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


EDITED_HEADER = "# Edited through the API (radar.api); validated by radar.config. Hand-written comments are not kept.\n"


def _atomic_write(path, text):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def create_app(store, runtime=None, tokens=None, now=utcnow):
    tokens = load_settings().api_tokens if tokens is None else tokens
    if runtime is not None and not tokens:
        log.warning("API_TOKENS is empty: every /api request will be refused")

    @asynccontextmanager
    async def lifespan(app):
        stop, task = asyncio.Event(), None
        if getattr(runtime, "scheduler", None) is not None:
            task = asyncio.create_task(runtime.scheduler.run(stop))
            task.add_done_callback(_log_crash)
        try:
            yield
        finally:
            if task is not None:
                stop.set()  # Scheduler.run drains in-flight fetches before returning
                await asyncio.gather(task, return_exceptions=True)

    app = FastAPI(title="Drop Radar", lifespan=lifespan)
    app.state.store, app.state.runtime = store, runtime

    async def current_user(authorization: str = Header(default="")) -> User:
        scheme, _, given = authorization.partition(" ")
        given = given.strip().encode()
        user_id = None
        if scheme.lower() == "bearer" and given:
            # every secret is compared, in constant time, so timing doesn't say how close a guess was
            for secret, uid in tokens.items():
                if hmac.compare_digest(secret.encode(), given):
                    user_id = uid
        user = getattr(runtime, "users", {}).get(user_id) if user_id else None
        if user is None:
            raise HTTPException(401, "missing or invalid bearer token", headers={"WWW-Authenticate": "Bearer"})
        return user

    def owned(user):
        return runtime.owned.get(user.id, frozenset())

    def serialize(opp, user):
        mine = owned(user)
        _, ok, reasons = visible_to(opp, user.profile, mine)
        fields, action = opp["fields"], opp.get("action")
        return Opportunity(
            id=opp["id"], title=opp["title"], company=opp["company"], location=opp["location"], url=opp["url"],
            deadline=opp["deadline"], status=opp["status"], first_seen=opp["first_seen"],
            published_at=opp["published_at"], category=fields.get("Category", ""),
            role_track=fields.get("Role / Track", ""), season=fields.get("Season / Year", ""),
            sources=sorted({i["source"] for i in opp["items"] if i["source"] in mine}),
            match=Match(ok=ok, reasons=reasons),
            action=Action(status=action["status"], notes=action["notes"]) if action else None,
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

    @app.get("/api/me", response_model=Me)
    async def me(user: User = Depends(current_user)):
        return Me(user=user.id, sources=len(owned(user)))

    @app.get("/api/opportunities", response_model=Page)
    async def list_opportunities(
        user: User = Depends(current_user),
        include: str = Query("matches", pattern="^(matches|all)$",
                             description="matches: what would alert you; all: everything your sources found"),
        q: str | None = Query(None, description="substring of title or company"),
        company: str | None = None,
        source: str | None = None,
        action: str | None = Query(None, description="your status; 'ignored' ones are hidden unless asked for"),
        status: str | None = Query(None, description="the posting's own status, e.g. New or Closed"),
        since: datetime | None = Query(None, description="first seen at or after"),
        closing_within: int | None = Query(None, ge=0, description="deadline within this many days"),
        cursor: str | None = None,
        limit: int = Query(50, ge=1, le=200),
    ):
        # ponytail: scores every candidate in Python per request (one row fetch each);
        # fine for two users and thousands of rows -- precompute per-user matches if it slows.
        after = _decode_cursor(cursor) if cursor else None
        today = now().date()
        items, more = [], None
        for row in store.list_opportunities(status=status, since=since, source_names=owned(user)):
            if after and (row["first_seen"], row["id"]) >= after:
                continue
            opp = store.get_opportunity(row["id"], user_id=user.id)
            mine = opp.get("action") or {}
            if action is not None and mine.get("status") != action:
                continue
            if action is None and mine.get("status") == HIDDEN_BY_DEFAULT:
                continue
            if q and q.lower() not in f"{opp['title']} {opp['company']}".lower():
                continue
            if company and company.lower() not in opp["company"].lower():
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
            if len(items) == limit:
                more = items[-1]
                break
            items.append(out)
        next_cursor = _encode_cursor({"first_seen": more.first_seen, "id": more.id}) if more else None
        return Page(items=items, next_cursor=next_cursor)

    @app.get("/api/opportunities/{opp_id}", response_model=Opportunity)
    async def get_opportunity(opp_id: str, user: User = Depends(current_user)):
        return serialize(visible_opportunity(opp_id, user), user)

    @app.patch("/api/opportunities/{opp_id}", response_model=Opportunity)
    async def update_opportunity(opp_id: str, patch: ActionPatch, user: User = Depends(current_user)):
        visible_opportunity(opp_id, user)
        if patch.status is not None or patch.notes is not None:
            store.set_action(opp_id, user.id, status=patch.status, notes=patch.notes)
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

    @app.put("/api/config/watchlist", response_model=WatchlistConfig)
    async def put_watchlist(body: WatchlistConfig, user: User = Depends(current_user)):
        replace_config(user, "watchlist", body.model_dump(), parse_watchlist, user.watchlist_path)
        return watchlist_out(runtime.users[user.id])

    @app.get("/api/config/profile", response_model=ProfileConfig)
    async def get_profile(user: User = Depends(current_user)):
        return ProfileConfig(**dataclasses.asdict(user.profile))

    @app.put("/api/config/profile", response_model=ProfileConfig)
    async def put_profile(body: ProfileConfig, user: User = Depends(current_user)):
        replace_config(user, "profile", body.model_dump(), parse_profile, user.profile_path)
        return ProfileConfig(**dataclasses.asdict(runtime.users[user.id].profile))

    return app
