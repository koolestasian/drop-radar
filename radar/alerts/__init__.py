"""alerts: channel delivery + the instant-vs-digest rule (00-overview.md, T7-alerts.md).

AlertDispatcher plugs into Pipeline the same way Enricher does: construct it
with the real store and let it default profile/channels, or inject fakes for
tests. Idempotency lives in the store (alerts table, one row per
(opportunity, channel), claimed via record_alert before send): a crash
mid-send leaves sent_at NULL, i.e. pending, picked up by retry_pending()
rather than re-claimed. Pipeline calls retry_pending() unconditionally at the
top of every sink invocation (even an empty item batch -- Scheduler._run_one
calls the sink every poll tick of every source regardless of item count), so
that is the retry timer; dispatch() itself never retries an already-claimed
row, only a fresh one, so a slow in-flight send (awaiting the channel) can't
be raced into a duplicate by a concurrent poll of another source.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

import requests

from radar.config import load_profile
from radar.legacy import opportunity_monitor as legacy
from radar.models import utcnow
from radar.pipeline.filter import matches_profile

log = logging.getLogger(__name__)

__all__ = ["AlertDispatcher", "MultiUserAlertDispatcher", "NtfyChannel", "channels_for", "should_alert"]

ZERO2SUDO_SOURCE = f"instagram.{legacy.USERNAME}"  # same env override migrate_legacy.py uses


def should_alert(source: str, opp: dict, profile) -> tuple[bool, list[str]]:
    """@zero2sudo's own Stories are curated by a human already; alert on sight.
    Everything else only alerts when it matches the profile (T7-alerts.md)."""
    if source == ZERO2SUDO_SOURCE:
        return True, ["insider source: @zero2sudo"]
    return matches_profile(opp, profile, level_implied=source.startswith("github_repo."))


def _drop_latency_s(opp, sent_at):
    """None on any bad input: a malformed timestamp must not break a send
    (retry_pending sweeps every pending row in one pass; one bad row can't
    be allowed to stop the rest, or ingestion for every other source too --
    Pipeline.__call__ runs this sweep unconditionally on every poll tick)."""
    published = opp.get("published_at") or opp.get("first_seen")
    if not published:
        return None
    try:
        if isinstance(published, str):
            published = datetime.fromisoformat(published)
        if published.tzinfo is None:  # a naive timestamp from a source that forgot tz; treat as UTC
            published = published.replace(tzinfo=timezone.utc)
        return (sent_at - published).total_seconds()
    except (ValueError, TypeError):
        return None


def _fmt_seconds(seconds):
    seconds = int(seconds)
    if seconds < 90:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 90:
        return f"{minutes}m"
    return f"{minutes // 60}h"


class NtfyChannel:
    """Reuses radar/legacy's NTFY_* env vars, one push per opportunity (not batched).
    `name` is the alerts.channel key, so it must be unique per user (see channels_for)."""

    def __init__(self, topic, server=None, token=None, name="ntfy"):
        self.name = name
        self.topic = topic
        self.server = (server or os.environ.get("NTFY_SERVER", "").strip() or "https://ntfy.sh").rstrip("/")
        self.token = token if token is not None else os.environ.get("NTFY_TOKEN", "").strip()

    def send(self, opp, reasons, drop_latency_s):
        lines = [x for x in (opp.get("location"), opp.get("deadline") and f"Deadline: {opp['deadline']}") if x]
        if reasons:
            lines.append("Why: " + "; ".join(reasons))
        sources = [i["source"] for i in opp.get("items") or []]
        tail = sources[0] if sources else ""
        if drop_latency_s is not None:
            tail = f"{tail} • seen {_fmt_seconds(drop_latency_s)} after posted".strip(" •")
        if tail:
            lines.append(tail)

        payload = {
            "topic": self.topic,
            "title": f"{opp.get('company') or 'New'} — {opp.get('title') or 'Opportunity'}"[:250],
            "message": "\n".join(lines).strip(),
            "tags": ["briefcase"],
        }
        url = opp.get("url") or ""
        if url:
            payload["click"] = url
            payload["actions"] = [{"action": "view", "label": "Apply", "url": url, "clear": True}]
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}

        response = requests.post(self.server, json=payload, headers=headers, timeout=30)
        if response.status_code >= 300:
            raise RuntimeError(f"ntfy push failed with status {response.status_code}")


def _default_channels():
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    return [NtfyChannel(topic)] if topic else []


def channels_for(user_id, owner, env=None):
    """The owner (first user in users.yaml) keeps NTFY_TOPIC and the channel name
    "ntfy", so alerts rows written before multi-user support still match. Everyone
    else: NTFY_TOPIC_<ID> and "ntfy:<id>". Topics live in env, never users.yaml,
    so reading that file can't subscribe anyone to someone else's pushes."""
    env = os.environ if env is None else env
    if owner:
        topic, name = env.get("NTFY_TOPIC", ""), "ntfy"
    else:
        key = "NTFY_TOPIC_" + "".join(c if c.isalnum() else "_" for c in user_id.upper())
        topic, name = env.get(key, ""), f"ntfy:{user_id}"
    topic = topic.strip()
    return [NtfyChannel(topic, name=name)] if topic else []


class MultiUserAlertDispatcher:
    """Fans each item out to every user's own AlertDispatcher, but only for users
    whose own watchlist includes the item's source: separate profiles means a
    user is alerted on what *their* sources found and their profile matches,
    never on another user's companies just because the keywords overlap."""

    def __init__(self, dispatchers, source_names):
        names = [c.name for d in dispatchers.values() for c in getattr(d, "channels", ())]
        clashes = sorted({n for n in names if names.count(n) > 1})
        if clashes:
            raise ValueError(f"alert channel names must be unique across users: {clashes}")
        self.dispatchers, self.source_names = dispatchers, source_names

    async def dispatch(self, item, opportunity_id):
        for user_id, dispatcher in self.dispatchers.items():
            if item.source not in self.source_names.get(user_id, ()):
                continue
            try:
                await dispatcher.dispatch(item, opportunity_id)
            except Exception:
                log.warning("alert dispatch failed for user %s", user_id, exc_info=True)

    async def retry_pending(self):
        for user_id, dispatcher in self.dispatchers.items():
            try:
                await dispatcher.retry_pending()
            except Exception:
                log.warning("alert retry failed for user %s", user_id, exc_info=True)


class AlertDispatcher:
    MIN_BACKOFF_S = 30
    MAX_BACKOFF_S = 3600

    def __init__(self, store, profile=None, channels=None):
        self.store = store
        self.profile = profile or load_profile()
        self.channels = _default_channels() if channels is None else list(channels)
        self._by_name = {c.name: c for c in self.channels}
        # ponytail: backoff/attempt counts are in-memory only, like Scheduler's own
        # disable/backoff (radar/scheduler.py) -- a process restart forgets them and
        # retries every pending alert immediately. Upgrade path: persist next_retry_at
        # on the alerts row if a restart-heavy deploy ever makes that matter.
        self._inflight = set()       # (opportunity_id, channel) currently sending -- guards overlap
        self._attempts = {}          # (opportunity_id, channel) -> consecutive failure count
        self._backoff_until = {}     # (opportunity_id, channel) -> datetime; skip retrying before this

    async def dispatch(self, item, opportunity_id):
        """A freshly processed item: alert now if it's new and it should alert.

        Never touches an (opportunity, channel) that's already claimed -- sent
        or pending -- so this can't race retry_pending() or another dispatch()
        into sending twice. Call retry_pending() separately for the sweep.
        """
        if not self.channels:
            return
        opp = self.store.get_opportunity(opportunity_id)
        if opp is None or opp["status"] == "Closed":
            return
        ok, reasons = should_alert(item.source, opp, self.profile)
        if not ok:
            return
        for channel in self.channels:
            if self.store.get_alert(opportunity_id, channel.name) is not None:
                continue  # already claimed (sent, or pending -- retry_pending's job alone)
            if not self.store.record_alert(opportunity_id, channel.name):
                continue  # lost the claim to a concurrent dispatch of the same opportunity
            await self._attempt_send(channel, opportunity_id, opp, reasons)

    async def retry_pending(self):
        """Resend every claimed-but-not-sent alert whose backoff has elapsed.

        The claim already decided this should alert (dispatch() only claims
        after should_alert() says yes); re-deciding here would be wrong, not
        just redundant -- the item that first matched the profile (often an
        ATS board, which the overview says usually publishes first) may not
        be the only one on this opportunity, and an unrelated later sighting
        that happens to fail matches_profile must never cancel an alert
        already owed. Closed is the only reason left to skip a send.
        """
        if not self.channels:
            return
        now = utcnow()
        for row in self.store.pending_alerts():
            key = (row["opportunity_id"], row["channel"])
            if key in self._inflight or self._backoff_until.get(key, now) > now:
                continue
            # pending_alerts() is a snapshot taken once above; a concurrent sweep or
            # dispatch() can finish sending THIS row while we're still awaiting an
            # earlier one in the list, so re-check right now (no await before
            # _attempt_send's _inflight.add) or we'd send an already-sent alert again.
            current = self.store.get_alert(row["opportunity_id"], row["channel"])
            if current is None or current["sent_at"]:
                continue
            channel = self._by_name.get(row["channel"])
            if channel is None:
                continue  # no longer configured; leave it pending
            opp = self.store.get_opportunity(row["opportunity_id"])
            if opp is None or opp["status"] == "Closed":
                continue
            sources = [i["source"] for i in opp.get("items") or []]
            source = ZERO2SUDO_SOURCE if ZERO2SUDO_SOURCE in sources else (sources[0] if sources else "")
            _, reasons = should_alert(source, opp, self.profile)
            await self._attempt_send(channel, row["opportunity_id"], opp, reasons or ["queued for alert"])

    async def _attempt_send(self, channel, opportunity_id, opp, reasons):
        key = (opportunity_id, channel.name)
        self._inflight.add(key)
        try:
            sent_at = utcnow()
            latency = _drop_latency_s(opp, sent_at)
            try:
                await asyncio.to_thread(channel.send, opp, reasons, latency)
            except Exception:
                log.warning("alert channel %s failed for %s; will retry with backoff",
                            channel.name, opportunity_id, exc_info=True)
                attempts = self._attempts.get(key, 0) + 1
                self._attempts[key] = attempts
                self._backoff_until[key] = sent_at + timedelta(
                    seconds=min(self.MIN_BACKOFF_S * 2 ** (attempts - 1), self.MAX_BACKOFF_S))
                return
            self.store.mark_alert_sent(opportunity_id, channel.name, sent_at, latency)
            self._attempts.pop(key, None)
            self._backoff_until.pop(key, None)
        finally:
            self._inflight.discard(key)
