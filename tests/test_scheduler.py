import asyncio
import random
import tempfile
import time
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from radar.config import Company, InstagramAccount, Watchlist
from radar.errors import ConfigError, SourceError
from radar.models import Item, utcnow
from radar.scheduler import BACKOFF_CAP_S, BLOCKED_COOLDOWN_S, Scheduler
from radar.sources import registry
from radar.store import Store


class FakeClock:
    """Virtual time: sleep advances it instantly, so tests run in milliseconds."""

    def __init__(self):
        self.t = utcnow()
        self.slept = []

    def now(self):
        return self.t

    async def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += timedelta(seconds=seconds)
        await asyncio.sleep(0)

    def advance(self, seconds):
        self.t += timedelta(seconds=seconds)


class FakeSource:
    def __init__(self, name, interval_s=60.0, results=None, gate=None):
        self.name, self.interval_s = name, interval_s
        self.results = list(results or [])  # each: list of Items or an exception; empty -> []
        self.gate = gate                    # asyncio.Event the fetch waits on
        self.calls = 0
        self.in_flight = 0
        self.max_in_flight = 0

    async def fetch(self, ctx):
        self.calls += 1
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.gate:
                await self.gate.wait()
            result = self.results.pop(0) if self.results else []
            if isinstance(result, Exception):
                raise result
            if callable(result):
                result = result(ctx)
                return await result if asyncio.iscoroutine(result) else result
            return result
        finally:
            self.in_flight -= 1


class Http:
    def __init__(self, gate=None):
        self.gate, self.urls, self.in_flight, self.max_in_flight = gate, [], 0, 0

    async def get(self, url, **kw):
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            if self.gate:
                await self.gate.wait()
            await asyncio.sleep(0)
            self.urls.append(url)
            return "ok"
        finally:
            self.in_flight -= 1


class ScaledClock:
    """Real time running 100x fast: concurrent sleeps overlap like they do in production."""

    def __init__(self):
        self.start, self.m0 = utcnow(), time.monotonic()

    def now(self):
        return self.start + timedelta(seconds=(time.monotonic() - self.m0) * 100)

    async def sleep(self, seconds):
        await asyncio.sleep(seconds / 100)


def get_once(url):
    async def fetch(ctx):
        await ctx.get(url)
        return []
    return fetch


def item(source, external_id):
    return Item(source=source, external_id=external_id, url=f"https://x.com/{source}/{external_id}", title="SWE Intern")


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(self.store.close)
        self.clock = FakeClock()
        self.alerts = []

    def scheduler(self, *sources, **kw):
        kw.setdefault("jitter", 0)
        return Scheduler(list(sources), self.store, clock=self.clock,
                         on_health_alert=lambda name, msg: self.alerts.append((name, msg)), **kw)

    def wait_s(self, sched, name):
        return (sched.next_run[name] - self.clock.now()).total_seconds()

    async def test_slow_source_does_not_delay_fast_one(self):
        gate = asyncio.Event()
        slow, fast = FakeSource("slow", 10, gate=gate), FakeSource("fast", 10)
        sched = self.scheduler(slow, fast)
        for _ in range(3):
            sched.launch_due()
            await settle()
            self.clock.advance(10)
        self.assertEqual((fast.calls, slow.calls), (3, 1))  # slow is never launched twice
        gate.set()
        await sched.drain()
        self.assertEqual(sched.running, {})

    async def test_transient_failures_back_off_exponentially_to_cap_then_reset(self):
        src = FakeSource("s", 120, results=[SourceError("timeout")] * 4 + [[]])
        sched = self.scheduler(src)
        waits = []
        for _ in range(5):
            self.clock.t = sched.next_run["s"]
            sched.launch_due()
            await sched.drain()
            waits.append(self.wait_s(sched, "s"))
        self.assertEqual(waits, [240, 480, BACKOFF_CAP_S, BACKOFF_CAP_S, 120])
        self.assertEqual(sched.health()[0]["fail_count"], 0)

    async def test_unexpected_exception_counts_as_transient(self):
        src = FakeSource("s", 60, results=[KeyError("boom")])
        sched = self.scheduler(src)
        sched.launch_due()
        await sched.drain()
        health = sched.health()[0]
        self.assertEqual((health["fail_count"], self.wait_s(sched, "s")), (1, 120))
        self.assertIn("KeyError", health["last_error"])

    async def test_blocked_cools_down(self):
        sched = self.scheduler(FakeSource("s", 60, results=[SourceError("429", kind="blocked")]))
        sched.launch_due()
        await sched.drain()
        self.assertEqual(self.wait_s(sched, "s"), BLOCKED_COOLDOWN_S)

    async def test_auth_disables_and_alerts_once_until_enabled(self):
        src = FakeSource("ig", 60, results=[SourceError("session expired", kind="auth")])
        sched = self.scheduler(src)
        sched.launch_due()
        await sched.drain()
        self.assertEqual(self.alerts, [("ig", "auth: session expired")])
        self.clock.advance(10_000)
        sched.launch_due()
        await sched.drain()
        self.assertEqual(src.calls, 1)
        health = sched.health()[0]
        self.assertTrue(health["disabled"])
        self.assertEqual(health["last_error"], "auth: session expired")
        sched.enable("ig")
        sched.launch_due()
        await sched.drain()
        self.assertEqual(src.calls, 2)

    async def test_jitter_spreads_next_run_within_ten_percent(self):
        sched = self.scheduler(*[FakeSource(f"s{i}", 100) for i in range(20)], jitter=0.1, rng=random.Random(1))
        sched.launch_due()
        await sched.drain()
        waits = [self.wait_s(sched, f"s{i}") for i in range(20)]
        self.assertTrue(all(90 <= w <= 110 for w in waits))
        self.assertGreater(len(set(waits)), 10)

    async def test_items_are_stored_and_counted_in_health(self):
        src = FakeSource("ats.greenhouse.stripe", 60, results=[[item("ats.greenhouse.stripe", "1"), item("ats.greenhouse.stripe", "2")]])
        sched = self.scheduler(src)
        sched.launch_due()
        await sched.drain()
        self.assertEqual(len(self.store.list_opportunities()), 2)
        health = sched.health()[0]
        self.assertEqual((health["items_24h"], health["last_ok"] is not None), (2, True))

    async def test_sink_failure_is_a_failure_and_keeps_old_etag(self):
        src = FakeSource("s", 60, results=[lambda ctx: ctx.remember(etag="v2") or [item("s", "1")]])
        def sink(source, items):
            raise RuntimeError("db locked")
        sched = self.scheduler(src, sink=sink)
        self.store.save_source_state("s", etag="v1")
        sched.launch_due()
        await sched.drain()
        state = self.store.get_source_state("s")
        self.assertEqual((state["etag"], state["fail_count"]), ("v1", 1))

    async def test_etag_and_cursor_persist_after_success_and_across_restart(self):
        seen = []
        src = FakeSource("s", 60, results=[
            lambda ctx: ctx.remember(etag='"abc"', cursor="42") or [],
            lambda ctx: seen.append((ctx.etag, ctx.cursor)) or [],
        ])
        sched = self.scheduler(src)
        sched.launch_due()
        await sched.drain()
        restarted = self.scheduler(src)  # next_run comes back from the store
        self.assertEqual(restarted.next_run["s"], sched.next_run["s"])
        self.clock.advance(60)
        restarted.launch_due()
        await restarted.drain()
        self.assertEqual(seen, [('"abc"', "42")])

    async def test_global_cap_limits_http_requests_in_flight(self):
        http = Http(gate=asyncio.Event())
        sources = [FakeSource(f"s{i}", 60, results=[get_once(f"https://h{i}.com/")]) for i in range(5)]
        sched = self.scheduler(*sources, http=http, max_concurrency=2)
        sched.launch_due()
        await settle()
        self.assertEqual(http.in_flight, 2)
        http.gate.set()
        await sched.drain()
        self.assertEqual((len(http.urls), http.max_in_flight), (5, 2))

    async def test_requests_waiting_on_a_busy_host_do_not_block_other_hosts(self):
        clock = ScaledClock()
        http = Http()
        sources = [FakeSource(f"a{i}", 60, results=[get_once(f"https://a.com/{i}")]) for i in range(4)]
        sources.append(FakeSource("ig", 60, results=[get_once("https://b.com/stories")]))
        sched = Scheduler(sources, self.store, clock=clock, http=http, max_concurrency=1, jitter=0)
        sched.launch_due()
        await sched.drain()
        self.assertEqual(http.urls[:2], ["https://a.com/0", "https://b.com/stories"])

    async def test_per_host_rate_limit(self):
        class TimedHttp:
            def __init__(self, clock):
                self.clock, self.times = clock, []
            async def get(self, url, **kw):
                self.times.append((url, self.clock.now()))
                return "ok"

        http = TimedHttp(self.clock)
        sched = self.scheduler(FakeSource("s", 60), http=http)
        ctx = sched.context("s")
        start = self.clock.now()
        await asyncio.gather(ctx.get("https://a.com/1"), ctx.get("https://b.com/1"), ctx.get("https://a.com/2"))
        offsets = {url: (t - start).total_seconds() for url, t in http.times}
        self.assertEqual(offsets, {"https://a.com/1": 0, "https://b.com/1": 0, "https://a.com/2": 1})
        self.assertEqual(self.clock.slept, [1.0])  # only the second a.com request waited

    async def test_run_loop_polls_until_stopped(self):
        stop = asyncio.Event()
        src = FakeSource("s", 30, results=[[], [], lambda ctx: stop.set() or []])
        sched = self.scheduler(src, http=object())
        await asyncio.wait_for(sched.run(stop), timeout=2)
        self.assertEqual(src.calls, 3)
        self.assertTrue(all(0 < s <= 1.0 for s in self.clock.slept))

    def test_duplicate_source_names_rejected(self):
        with self.assertRaises(ValueError):
            self.scheduler(FakeSource("s"), FakeSource("s"))


class StoreMigrationTests(unittest.TestCase):
    def test_user_version_migration_runs_once(self):
        path = Path(tempfile.mkdtemp()) / "radar.db"
        with Store(path) as store:
            version = store.conn.execute("PRAGMA user_version").fetchone()[0]
            store.save_source_state("s", last_error="x")
        with Store(path) as store:  # reopening must not re-run ALTER TABLE
            self.assertEqual(store.conn.execute("PRAGMA user_version").fetchone()[0], version)
            self.assertEqual(store.get_source_state("s")["last_error"], "x")
        self.assertGreaterEqual(version, 1)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.saved = dict(registry.FACTORIES)
        self.addCleanup(lambda: (registry.FACTORIES.clear(), registry.FACTORIES.update(self.saved)))
        # Hermetic: build_sources() auto-imports every real module under
        # radar/sources/ (e.g. T5's "instagram"), permanently registering real
        # factories the first time any test anywhere imports them. Block further
        # imports and start from an empty registry so "unknown kind" below means
        # what the test says, regardless of import order or which real source
        # modules exist.
        patcher = patch.object(registry, "_import_source_modules", lambda: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        registry.FACTORIES.clear()

    def test_builds_registered_kinds_and_skips_unknown(self):
        @registry.register("greenhouse")
        def greenhouse(company, settings):
            return FakeSource(f"ats.greenhouse.{company.slug}", 120)

        watchlist = Watchlist(
            companies=(Company("Stripe", "greenhouse", "stripe", "S"), Company("Ramp", "ashby", "ramp")),
            instagram=(InstagramAccount("zero2sudo"),),
        )
        sources, skipped = registry.build_sources(watchlist)
        self.assertEqual([s.name for s in sources], ["ats.greenhouse.stripe"])
        self.assertEqual(skipped, ["ashby", "instagram"])

    def test_duplicate_names_are_a_config_error(self):
        registry.register("greenhouse")(lambda company, settings: FakeSource("same"))
        watchlist = Watchlist(companies=(Company("A", "greenhouse", "a"), Company("B", "greenhouse", "b")))
        with self.assertRaises(ConfigError):
            registry.build_sources(watchlist)


if __name__ == "__main__":
    unittest.main()
