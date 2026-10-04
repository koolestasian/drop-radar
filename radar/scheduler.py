"""Per-source polling: one asyncio loop, every source at its own pace, failures isolated.

Each due source runs as its own task, so a slow source never delays a fast one.
After a run the source's next_run is set from its result:
  ok         -> interval_s (+-jitter)
  transient  -> interval_s * 2**fail_count, capped at 15 min (schema errors and
                unexpected exceptions count as transient)
  blocked    -> 30 min cool-down
  auth       -> disabled until enable(); on_health_alert is called once
next_run, fail_count, last_error and a source's ETag/cursor persist in source_state.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol
from urllib.parse import urlparse

from radar.errors import SourceError
from radar.models import Item, utcnow

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; drop-radar; +https://github.com)"
BACKOFF_CAP_S = 900.0
BLOCKED_COOLDOWN_S = 1800.0
TICK_S = 1.0  # ponytail: loop wakes at least every second; event-driven wakeups if 1s latency ever matters
HEARTBEAT_INTERVAL_S = 60.0  # dead-man switch (T10): don't hit HEARTBEAT_URL every TICK_S, debounce to this
HEARTBEAT_TIMEOUT_S = 5.0    # bounds a hung heartbeat GET; it must never stall the poll loop


class Source(Protocol):
    name: str          # unique; Items it emits should use it as Item.source
    interval_s: float  # base poll interval

    async def fetch(self, ctx: FetchContext) -> list[Item]: ...


class Clock:
    def now(self) -> datetime:
        return utcnow()

    async def sleep(self, seconds: float):
        await asyncio.sleep(seconds)


class HostLimiter:
    """At most `per_second` request starts per host. Slots are reserved before
    sleeping, so concurrent callers queue up without a lock."""

    def __init__(self, clock, per_second=1.0):
        self.clock, self.gap, self.next_free = clock, 1.0 / per_second, {}

    async def wait(self, host):
        now = self.clock.now().timestamp()
        slot = max(now, self.next_free.get(host, now))
        self.next_free[host] = slot + self.gap
        if slot > now:
            await self.clock.sleep(slot - now)


@dataclass
class FetchContext:
    name: str
    http: object  # httpx.AsyncClient shared by all sources
    clock: Clock
    limiter: HostLimiter
    requests: asyncio.Semaphore  # global cap on HTTP requests in flight
    etag: str | None = None    # what this source remembered last successful run
    cursor: str | None = None
    pending: dict = field(default_factory=dict)

    def now(self) -> datetime:
        return self.clock.now()

    def remember(self, etag=None, cursor=None):
        """Keep an ETag/cursor for the next fetch. Saved only once this fetch's items are stored."""
        if etag is not None:
            self.pending["etag"] = etag
        if cursor is not None:
            self.pending["cursor"] = cursor

    async def get(self, url, **kwargs):
        """http.get behind the per-host rate limit and global request cap. Sources use this, not http.

        The cap is taken only after the host's turn comes, so requests queued
        for one busy host never hold slots other hosts could use.
        """
        await self.limiter.wait(urlparse(url).hostname or "")
        async with self.requests:
            return await self.http.get(url, **kwargs)

    async def post(self, url, **kwargs):
        """Same limits as get(), for search APIs that only take POST (Workday)."""
        await self.limiter.wait(urlparse(url).hostname or "")
        async with self.requests:
            return await self.http.post(url, **kwargs)


def _parse(value):
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


class Scheduler:
    def __init__(self, sources, store, *, sink=None, on_health_alert=None, http=None, clock=None,
                 max_concurrency=20, per_host_per_second=1.0, jitter=0.1, rng=None,
                 heartbeat_url=None, heartbeat_interval_s=HEARTBEAT_INTERVAL_S,
                 heartbeat_timeout_s=HEARTBEAT_TIMEOUT_S):
        names = [source.name for source in sources]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate source names: {sorted({n for n in names if names.count(n) > 1})}")
        self.sources = {source.name: source for source in sources}
        self.store = store
        self.sink = sink or self._store_items          # (source, items); may be async. T6 swaps in the pipeline.
        self.on_health_alert = on_health_alert or (lambda name, msg: log.error("source %s disabled: %s", name, msg))
        self.http = http
        self.clock = clock or Clock()
        self.limiter = HostLimiter(self.clock, per_host_per_second)
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.jitter, self.rng = jitter, rng or random.Random()
        self.disabled = {}  # name -> reason; in memory, so a restart (e.g. with a new session) re-enables
        self.running = {}   # name -> task
        self.heartbeat_url = heartbeat_url
        self.heartbeat_interval_s = heartbeat_interval_s
        self.heartbeat_timeout_s = heartbeat_timeout_s
        self._last_heartbeat = None
        self._heartbeat_task = None
        now = self.clock.now()
        self.next_run = {
            name: _parse((store.get_source_state(name) or {}).get("next_run")) or now for name in self.sources
        }

    def reload(self, sources):
        """Swap in a new source set while running (config edited through the API).
        An unchanged source (same name and interval) keeps its object, so in-memory
        state like Instagram's Apify cooldown survives; an added one is due now;
        a dropped one whose fetch is in flight finishes and is then forgotten."""
        names = [source.name for source in sources]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate source names: {sorted({n for n in names if names.count(n) > 1})}")
        now = self.clock.now()
        kept = {}
        for source in sources:
            old = self.sources.get(source.name)
            kept[source.name] = old if old is not None and old.interval_s == source.interval_s else source
        self.sources = kept
        self.next_run = {name: self.next_run.get(name, now) for name in kept}
        self.disabled = {name: why for name, why in self.disabled.items() if name in kept}

    # ---- running ----------------------------------------------------------

    def launch_due(self):
        """Start a task for every enabled source that is due and not already running."""
        now = self.clock.now()
        for name, at in self.next_run.items():
            if (at <= now and name not in self.disabled and name not in self.running
                    and not getattr(self.sources[name], "external", False)):
                self.running[name] = asyncio.create_task(self._run_one(self.sources[name]))

    async def drain(self):
        while self.running:
            await asyncio.gather(*self.running.values())

    async def run(self, stop: asyncio.Event | None = None):
        """Poll until `stop` is set, then let in-flight fetches finish."""
        stop = stop or asyncio.Event()
        own_http = self.http is None
        if own_http:
            import httpx

            self.http = httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT})
        try:
            while not stop.is_set():
                self.launch_due()
                self._maybe_heartbeat()
                await self.clock.sleep(self._idle_s())
            await self.drain()
        finally:
            if self._heartbeat_task is not None:
                self._heartbeat_task.cancel()
            if own_http:
                await self.http.aclose()
                self.http = None

    def _maybe_heartbeat(self):
        """Dead-man switch (T10): GET heartbeat_url, debounced to heartbeat_interval_s
        (every scheduler loop would hammer it, since the idle loop wakes every TICK_S).
        Fire-and-forget with its own timeout, never inline: a slow/hung heartbeat
        endpoint must not stall launch_due()."""
        if not self.heartbeat_url:
            return
        now = self.clock.now()
        if self._last_heartbeat is not None and (now - self._last_heartbeat).total_seconds() < self.heartbeat_interval_s:
            return
        if self._heartbeat_task is not None and not self._heartbeat_task.done():
            return
        self._last_heartbeat = now
        self._heartbeat_task = asyncio.create_task(self._ping_heartbeat())

    async def _ping_heartbeat(self):
        try:
            await asyncio.wait_for(self.http.get(self.heartbeat_url), self.heartbeat_timeout_s)
        except Exception as exc:
            log.warning("heartbeat GET to %s failed: %s", self.heartbeat_url, exc)

    def _idle_s(self):
        now = self.clock.now()
        waits = [
            (at - now).total_seconds() for name, at in self.next_run.items()
            if name not in self.disabled and name not in self.running and not getattr(self.sources[name], "external", False)
        ]
        return min([TICK_S] + [max(wait, 0.01) for wait in waits])

    def context(self, name):
        state = self.store.get_source_state(name) or {}
        return FetchContext(
            name, self.http, self.clock, self.limiter, self.semaphore, state.get("etag"), state.get("cursor")
        )

    async def _run_one(self, source):
        name = source.name
        try:
            ctx = self.context(name)
            items = await source.fetch(ctx)
            result = self.sink(source, items)
            if inspect.isawaitable(result):
                await result
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._failed(source, exc)
        else:
            self.store.save_source_state(
                name, last_ok=self.clock.now(), fail_count=0, last_error=None,
                next_run=self._schedule(name, self._interval(source)), **ctx.pending,
            )
            log.info("source %s: %d item(s)", name, len(items))
        finally:
            self.running.pop(name, None)

    def _interval(self, source):
        """The base delay now: a source may vary it by time of day (adaptive polling)."""
        at = getattr(source, "interval_at", None)
        return at(self.clock.now()) if at else source.interval_s

    def _failed(self, source, exc):
        name = source.name
        kind = exc.kind if isinstance(exc, SourceError) else "transient"
        error = f"{kind}: {exc}" if isinstance(exc, SourceError) else f"transient: {type(exc).__name__}: {exc}"
        fails = ((self.store.get_source_state(name) or {}).get("fail_count") or 0) + 1
        if kind == "auth":
            self.disabled[name] = error
            self.on_health_alert(name, error)
            delay = source.interval_s
        elif kind == "blocked":
            delay = BLOCKED_COOLDOWN_S
        else:
            base = self._interval(source)
            delay = max(base, min(base * 2 ** fails, BACKOFF_CAP_S))
        self.store.save_source_state(name, fail_count=fails, last_error=error[:500],
                                     next_run=self._schedule(name, delay))
        log.warning("source %s failed (%d in a row): %s", name, fails, error)

    def _schedule(self, name, delay_s):
        """Sets and returns next_run; None (and nothing set) for a source a reload
        dropped while its fetch was in flight -- the one place both outcomes pass."""
        if name not in self.sources:
            return None
        spread = 1 + self.rng.uniform(-self.jitter, self.jitter) if self.jitter else 1
        self.next_run[name] = self.clock.now() + timedelta(seconds=delay_s * spread)
        return self.next_run[name]

    def _store_items(self, source, items):
        for item in items:
            self.store.upsert_item(item)

    # ---- control and health ---------------------------------------------

    def enable(self, name):
        """Re-enable a source disabled by an auth error and poll it now. False if no such source."""
        self.disabled.pop(name, None)
        if name not in self.sources:
            return False
        self.next_run[name] = self.clock.now()
        return True

    def health(self):
        """Per source: disabled, running, next_run, last_ok, fail_count, last_error, items_24h."""
        since = self.clock.now() - timedelta(hours=24)
        snapshot = []
        for name in self.sources:
            state = self.store.get_source_state(name) or {}
            at = (_parse(state.get("next_run")) or self.next_run[name]) if getattr(self.sources[name], "external", False) else self.next_run[name]
            last_ok = _parse(state.get("last_ok"))
            snapshot.append({
                "name": name,
                "disabled": name in self.disabled,
                "running": name in self.running,
                "next_run": at.isoformat(),
                "stale": bool(last_ok and (self.clock.now() - last_ok).total_seconds() > 2 * self.sources[name].interval_s + 60),
                "last_ok": state.get("last_ok"),
                "fail_count": state.get("fail_count") or 0,
                "last_error": state.get("last_error"),
                "items_24h": self.store.count_items(name, since),
            })
        return snapshot
