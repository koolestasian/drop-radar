import asyncio
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from radar.config import Company
from radar.models import Item
from radar.scheduler import Scheduler
from radar.sources.ats import AtsSource
from radar.sources.cadence import active_hours, interval_for
from radar.store import Store


def at(hour, day=1):
    return datetime(2026, 10, day, hour, 30, tzinfo=timezone.utc)


class CadenceTests(unittest.TestCase):
    def test_too_little_history_keeps_tier(self):
        self.assertIsNone(active_hours([at(14)] * 9))
        self.assertEqual(interval_for(300.0, None, at(14)), 300.0)

    def test_posting_hours_found(self):
        times = [at(14)] * 12 + [at(15)] * 7 + [at(3)]
        self.assertEqual(active_hours(times), frozenset({14, 15}))

    def test_faster_in_active_hours_slower_outside(self):
        hours = frozenset({14})
        self.assertEqual(interval_for(300.0, hours, at(14)), 150.0)
        self.assertEqual(interval_for(300.0, hours, at(2)), 900.0)

    def test_interval_is_clamped(self):
        hours = frozenset({14})
        self.assertEqual(interval_for(120.0, hours, at(14)), 60.0)
        self.assertEqual(interval_for(900.0, hours, at(2)), 1800.0)


class StoreHistoryTests(unittest.TestCase):
    def test_seed_items_are_not_posting_times(self):
        store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(store.close)
        store.upsert_item(Item(source="s", external_id="1", url="https://x/1", title="Intern", company="X",
                               seen_at=at(9), raw={"seed": True}))
        store.upsert_item(Item(source="s", external_id="2", url="https://x/2", title="Intern", company="X",
                               seen_at=at(14)))
        store.upsert_item(Item(source="other", external_id="3", url="https://x/3", title="Intern", company="X",
                               seen_at=at(16)))
        self.assertEqual([t.hour for t in store.first_seen_times("s")], [14])


class SchedulerUsesCadenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_next_run_follows_the_hour(self):
        store = Store(Path(tempfile.mkdtemp()) / "radar.db")
        self.addCleanup(store.close)
        source = AtsSource(Company(name="Acme", ats="greenhouse", slug="acme", tier="B"))
        source.active_hours = frozenset({14})

        async def no_items(ctx):
            return []
        source.fetch = no_items

        class Clock:
            t = at(14)

            def now(self):
                return self.t
        clock = Clock()
        sched = Scheduler([source], store, clock=clock, jitter=0, http=None)
        sched.launch_due()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        await sched.drain()
        self.assertEqual((sched.next_run[source.name] - clock.t).total_seconds(), 150.0)
        self.assertEqual(sched._interval(source), 150.0)
        clock.t = at(2)
        self.assertEqual(sched._interval(source), 900.0)
        self.assertEqual(source.interval_s, 300.0)  # the tier interval itself is unchanged


if __name__ == "__main__":
    unittest.main()
