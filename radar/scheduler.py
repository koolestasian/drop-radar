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
                 max_concurrency=20, per_host_per_second=1.0, jitter=0.1, rng=None):
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
        now = self.clock.now()
        self.next_run = {
            name: _parse((store.get_source_state(name) or {}).get("next_run")) or now for name in self.sources
        }

    # ---- running ----------------------------------------------------------

    def launch_due(self):
        """Start a task for every enabled source that is due and not already running."""
        now = self.clock.now()
        for name, at in self.next_run.items():
            if at <= now and name not in self.disabled and name not in self.running:
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
                await self.clock.sleep(self._idle_s())
            await self.drain()
        finally:
            if own_http:
                await self.http.aclose()
                self.http = None

    def _idle_s(self):
        now = self.clock.now()
        waits = [
            (at - now).total_seconds() for name, at in self.next_run.items()
            if name not in self.disabled and name not in self.running
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
            self._schedule(name, source.interval_s)
            self.store.save_source_state(
                name, last_ok=self.clock.now(), fail_count=0, last_error=None,
                next_run=self.next_run[name], **ctx.pending,
            )
            log.info("source %s: %d item(s)", name, len(items))
        finally:
            self.running.pop(name, None)

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
            delay = max(source.interval_s, min(source.interval_s * 2 ** fails, BACKOFF_CAP_S))
        self._schedule(name, delay)
        self.store.save_source_state(name, fail_count=fails, last_error=error[:500], next_run=self.next_run[name])
        log.warning("source %s failed (%d in a row): %s", name, fails, error)

    def _schedule(self, name, delay_s):
        spread = 1 + self.rng.uniform(-self.jitter, self.jitter) if self.jitter else 1
        self.next_run[name] = self.clock.now() + timedelta(seconds=delay_s * spread)

    def _store_items(self, source, items):
        for item in items:
            self.store.upsert_item(item)

    # ---- control and health ---------------------------------------------

    def enable(self, name):
        """Re-enable a source disabled by an auth error and poll it now."""
        self.disabled.pop(name, None)
        self.next_run[name] = self.clock.now()

    def health(self):
        """Per source: disabled, running, next_run, last_ok, fail_count, last_error, items_24h."""
        since = self.clock.now() - timedelta(hours=24)
        snapshot = []
        for name in self.sources:
            state = self.store.get_source_state(name) or {}
            snapshot.append({
                "name": name,
                "disabled": name in self.disabled,
                "running": name in self.running,
                "next_run": self.next_run[name].isoformat(),
                "last_ok": state.get("last_ok"),
                "fail_count": state.get("fail_count") or 0,
                "last_error": state.get("last_error"),
                "items_24h": self.store.count_items(name, since),
            })
        return snapshot
