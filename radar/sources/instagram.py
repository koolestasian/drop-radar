"""Instagram source: native client first, Apify fallback while native is down.

One InstagramSource per watchlist `instagram:` entry (max 5, enforced in
radar.config.load_watchlist). Only Stories are polled -- that is the fast path
the spec cares about; recent_posts stays out of scope here.

fetch() tries the native InstagramClient (synchronous `requests`, so it runs in
a thread via asyncio.to_thread) and raises SourceError(kind="auth"|"blocked")
on failure so T2's scheduler can disable/cool down the source. Apify is only
tried as a same-call fallback when native fails, never as a parallel or
preferred path, and is itself rate-limited to one run per 15 minutes. If Apify
can't cover (no token, rate-limited, or its own call fails) the native error is
raised so the scheduler sees the real failure instead of a masked one.

Identity (instagram_media_key/normalize_links) and OCR (item_text) are reused
from radar.legacy.opportunity_monitor so native and Apify items of the same
Story dedupe to the same Item.external_id.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from radar.config import load_settings
from radar.errors import SourceError
from radar.legacy import opportunity_monitor as legacy
from radar.legacy.instagram_scraper import BASE, InstagramAuthError, InstagramBlockedError, InstagramClient
from radar.models import Item
from radar.sources.registry import register

log = logging.getLogger(__name__)

APIFY_FALLBACK_COOLDOWN_S = 900.0  # 1 run / 15 min, per spec


def _title(text, username):
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return first_line[:120] or f"Instagram Story: @{username}"


def _parse_posted_at(raw):
    """legacy.posted_at may hand back a raw payload date string with no offset
    (e.g. a "takenAtIso" field); treat it as UTC like radar.sources.ats.parse_date does."""
    value = legacy.posted_at(raw)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def _build_item(username, raw, now, text_cache=None) -> Item | None:
    """One raw story dict (native- or Apify-shaped) -> Item, or None if it carries no stable id.

    external_id is prefixed "media:<id>" to match radar.store.migrate_legacy's
    record_semantic_key (which also prefers instagram_media_key and uses the
    same prefix) -- so a Story already migrated from the legacy tracker and
    still live converges to the same (source, external_id) items row, and
    (via Store.upsert_item reusing that row's opportunity_id) the same
    opportunity, instead of being counted as a new sighting under a freshly
    hashed id. `url` prefers the
    extracted application link over the Story permalink, per Item's contract
    ("canonical link (apply link when known)"), so this source's items can
    still merge with an ATS source that independently sees the same posting;
    the permalink is only a fallback when no application link was found.
    """
    links = legacy.normalize_links(raw)
    media_id = legacy.instagram_media_key(links)
    external_id = f"media:{media_id}" if media_id else str(raw.get("pk") or raw.get("id") or "")
    if not external_id:
        return None  # no stable identity to dedupe on; skip rather than risk a re-alert storm
    if text_cache is not None and external_id in text_cache:
        text = text_cache[external_id]
    else:
        text = await asyncio.to_thread(legacy.item_text, raw)  # OCR shells out to tesseract -> thread
        if text_cache is not None:
            text_cache[external_id] = text
    application_links = legacy.external_links(links)
    permalink = f"{BASE}/stories/{username}/{media_id}/" if media_id else ""
    return Item(
        source=f"instagram.{username}",
        external_id=external_id,
        url=application_links[0] if application_links else permalink,
        title=_title(text, username),
        text=text,
        published_at=_parse_posted_at(raw),
        seen_at=now,
        raw=dict(raw),
    )


class InstagramSource:
    def __init__(self, account, settings, client=None):
        self.account = account
        self.settings = settings
        self.name = f"instagram.{account.username}"
        self.interval_s = account.interval_s
        self._client = client  # lazy singleton; tests inject a fake directly
        # ponytail: instance-level timestamp, not a ctx.remember()/store cursor. This
        # process runs one long-lived Scheduler loop (per 00-overview.md), so an
        # instance attribute already is "the one place the rate limit lives" --
        # a store cursor would only matter across process restarts, which would
        # also drop the native session's in-memory cookies, so there is nothing
        # left to protect. Upgrade to ctx.remember(cursor=...) if sources start
        # running out-of-process or restarting frequently enough for that to bite.
        self._last_apify_run = None
        # ponytail: unbounded dict, fine for one account's Stories (tens/day, 24h
        # life); cap with an LRU if this ever needs to run for months unattended.
        self._text_cache = {}

    def _native_client(self):
        if self._client is None:
            self._client = InstagramClient(self.settings.ig_sessionid)
        return self._client

    async def fetch(self, ctx) -> list[Item]:
        username = self.account.username
        try:
            raw_items = await asyncio.to_thread(self._native_client().stories, username)
        except InstagramAuthError as exc:
            native_error = SourceError(str(exc), kind="auth")
        except InstagramBlockedError as exc:
            native_error = SourceError(str(exc), kind="blocked")
        else:
            return await self._to_items(raw_items, ctx)

        apify_items = await self._try_apify(username, ctx)
        if apify_items is not None:
            return apify_items
        raise native_error

    async def _try_apify(self, username, ctx):
        if not self.settings.apify_token:
            return None
        now = ctx.now()
        if self._last_apify_run is not None and (now - self._last_apify_run).total_seconds() < APIFY_FALLBACK_COOLDOWN_S:
            return None
        self._last_apify_run = now  # reserve the slot before the call, not after
        try:
            raw_items = await asyncio.to_thread(legacy.run_actor, legacy.STORY_ACTOR, {"usernames": [username]})
        except Exception as exc:
            log.warning("instagram.%s: apify fallback failed: %s", username, exc)
            return None
        return await self._to_items(raw_items, ctx)

    async def _to_items(self, raw_items, ctx) -> list[Item]:
        now = ctx.now()
        items = []
        for raw in raw_items:
            item = await _build_item(self.account.username, raw, now, text_cache=self._text_cache)
            if item is not None:
                items.append(item)
        return items


@register("instagram")
def factory(entry, settings):
    return InstagramSource(entry, settings or load_settings())
