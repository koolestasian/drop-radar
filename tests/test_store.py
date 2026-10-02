import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import opportunity_monitor as legacy
from radar.models import Item
from radar.store import MIGRATIONS, SCHEMA, Store
from radar.store.migrate_legacy import migrate
from radar.views import legacy_records, write_views

T0 = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)


def item(source="ats.greenhouse", external_id="1", url="https://boards.greenhouse.io/x/jobs/1", **kw):
    return Item(source=source, external_id=external_id, url=url, title=kw.pop("title", "SWE Intern"), **kw)


def row(id_, first_seen, **fields):
    record = {header: "" for header in legacy.HEADERS}
    record.update({"ID": id_, "First Seen": first_seen, "Actioned?": "No", "Status": "New"}, **fields)
    return record


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.store = Store(self.dir / "data" / "radar.db")
        self.addCleanup(self.store.close)

    def test_wal_and_schema(self):
        mode = self.store.conn.execute("PRAGMA journal_mode").fetchone()[0]
        self.assertEqual(mode, "wal")
        tables = {r[0] for r in self.store.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"opportunities", "items", "source_state", "alerts", "actions", "enrichment"} <= tables)

    def test_upsert_item_is_idempotent_and_dedupes_by_url(self):
        first = item(seen_at=T0 + timedelta(minutes=5))
        opp_id, new = self.store.upsert_item(first)
        self.assertTrue(new)
        self.assertEqual(self.store.upsert_item(first), (opp_id, False))
        # Same apply URL from another source, seen earlier: same opportunity, earlier first_seen.
        other = item(source="github.simplify", external_id="row-9", seen_at=T0, published_at=T0 - timedelta(hours=1))
        self.assertEqual(self.store.upsert_item(other), (opp_id, False))
        opp = self.store.get_opportunity(opp_id)
        self.assertEqual(opp["first_seen"], T0.isoformat())
        self.assertEqual(opp["published_at"], (T0 - timedelta(hours=1)).isoformat())
        self.assertEqual(sorted(i["source"] for i in opp["items"]), ["ats.greenhouse", "github.simplify"])

    def test_mark_seen_updates_last_seen(self):
        self.store.upsert_item(item(seen_at=T0))
        later = T0 + timedelta(hours=1)
        self.assertTrue(self.store.mark_seen("ats.greenhouse", "1", later))
        self.assertFalse(self.store.mark_seen("ats.greenhouse", "nope", later))
        last = self.store.conn.execute("SELECT last_seen_at FROM items").fetchone()[0]
        self.assertEqual(last, later.isoformat())

    def test_record_alert_once_per_channel(self):
        opp_id, _ = self.store.upsert_item(item())
        self.assertTrue(self.store.record_alert(opp_id, "ntfy"))
        self.assertFalse(self.store.record_alert(opp_id, "ntfy"))
        self.assertTrue(self.store.record_alert(opp_id, "github"))

    def test_record_alert_claims_a_pending_slot_then_mark_alert_sent_fills_it_in(self):
        opp_id, _ = self.store.upsert_item(item())
        self.store.record_alert(opp_id, "ntfy")
        self.assertEqual(self.store.get_alert(opp_id, "ntfy"), {"sent_at": None, "drop_latency_s": None})
        self.store.mark_alert_sent(opp_id, "ntfy", T0, 12.5)
        alert = self.store.get_alert(opp_id, "ntfy")
        self.assertEqual(alert["sent_at"], T0.isoformat())
        self.assertEqual(alert["drop_latency_s"], 12.5)
        self.assertIsNone(self.store.get_alert(opp_id, "github"))

    def test_alert_latencies_only_counts_sent_alerts_grouped_by_earliest_items_source(self):
        opp_id, _ = self.store.upsert_item(item(seen_at=T0))
        self.store.upsert_item(item(source="github.simplify", external_id="row-9", seen_at=T0 + timedelta(hours=1)))
        self.store.record_alert(opp_id, "ntfy")  # claimed, not yet sent: must not appear
        self.store.mark_alert_sent(opp_id, "ntfy", T0 + timedelta(seconds=5), 5.0)
        self.assertEqual(self.store.alert_latencies(), [{"channel": "ntfy", "drop_latency_s": 5.0,
                                                          "source": "ats.greenhouse"}])

    def test_set_action_only_changes_given_fields(self):
        opp_id, _ = self.store.upsert_item(item())
        self.store.set_action(opp_id, "kevin", status="applied", notes="emailed recruiter")
        self.store.set_action(opp_id, "kevin", status="interview")
        action = self.store.get_opportunity(opp_id, user_id="kevin")["action"]
        self.assertEqual((action["status"], action["notes"]), ("interview", "emailed recruiter"))

    def test_actions_are_per_user_and_never_returned_without_asking_for_one(self):
        opp_id, _ = self.store.upsert_item(item())
        self.store.set_action(opp_id, "kevin", status="applied", notes="kevin's private note")
        self.store.set_action(opp_id, "friend", status="ignored")
        kevin = self.store.get_opportunity(opp_id, user_id="kevin")["action"]
        friend = self.store.get_opportunity(opp_id, user_id="friend")["action"]
        self.assertEqual((kevin["status"], kevin["notes"]), ("applied", "kevin's private note"))
        self.assertEqual((friend["status"], friend["notes"]), ("ignored", ""))
        self.assertIsNone(self.store.get_opportunity(opp_id, user_id="nobody")["action"])
        self.assertNotIn("action", self.store.get_opportunity(opp_id))

    def test_migration_3_backfills_existing_actions_to_kevin(self):
        """A real data/radar.db already holds single-user actions (from
        migrate_legacy); upgrading must keep every one of them, as kevin's."""
        db = self.dir / "v2.db"
        conn = sqlite3.connect(db)
        conn.executescript(SCHEMA.read_text())
        for sql in MIGRATIONS[:2]:
            conn.executescript(sql)
        conn.executescript("""
            PRAGMA user_version = 2;
            INSERT INTO opportunities (id, first_seen) VALUES ('o1', '2026-09-01T00:00:00+00:00');
            INSERT INTO actions (opportunity_id, status, notes, updated_at)
                VALUES ('o1', 'applied', 'applied 9/21', '2026-09-21T00:00:00+00:00');
        """)
        conn.close()
        with Store(db) as store:
            self.assertEqual(store.conn.execute("PRAGMA user_version").fetchone()[0], len(MIGRATIONS))
            action = store.get_opportunity("o1", user_id="kevin")["action"]
            self.assertEqual((action["status"], action["notes"]), ("applied", "applied 9/21"))
            self.assertIsNone(store.get_opportunity("o1", user_id="friend")["action"])

    def test_list_filters(self):
        a, _ = self.store.upsert_item(item(company="Stripe", seen_at=T0))
        self.store.upsert_item(item(external_id="2", url="https://x.com/2", company="Ramp", seen_at=T0 + timedelta(days=2)))
        self.assertEqual([o["id"] for o in self.store.list_opportunities(company="Stripe")], [a])
        self.assertEqual(len(self.store.list_opportunities(since=T0 + timedelta(days=1))), 1)
        self.assertEqual(len(self.store.list_opportunities(status="New")), 2)
        self.assertEqual(len(self.store.list_opportunities(limit=1)), 1)

    def test_get_missing_opportunity(self):
        self.assertIsNone(self.store.get_opportunity("missing"))

    def test_upsert_item_reuses_existing_items_opportunity_id(self):
        """A (source, external_id) already on file (e.g. migrated, keeping a
        legacy id unrelated to sha256(url)) must not get a second, orphaned
        opportunities row the next time a live source upserts it with no
        explicit opportunity_id override."""
        migrated = item(source="instagram.zero2sudo", external_id="media:999",
                         url="https://boards.greenhouse.io/stripe/jobs/1", seen_at=T0)
        self.store.upsert_item(migrated, opportunity_id="legacy123")
        opp_id, is_new = self.store.upsert_item(migrated)  # live source re-seeing it, no override
        self.assertEqual((opp_id, is_new), ("legacy123", False))
        self.assertEqual(len(self.store.list_opportunities()), 1)


class MigrationAndViewTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.tracker = self.dir / "tracker.xlsx"
        self.cache = self.dir / "enrichment_cache.json"
        self.db = self.dir / "radar.db"
        self.rows = [
            row("aaa", "2026-09-20T10:00:00+00:00", **{
                "Organization": "Stripe", "Opportunity": "Stripe — SWE Intern", "Category": "Internship",
                "Application / Registration Link": "https://stripe.com/jobs/1", "Deadline": "2026-10-15",
                "Raw Text": "Stripe SWE intern apply now", "Source Type": "Story",
                "Instagram Source": "https://www.instagram.com/stories/zero2sudo/123/",
                "Actioned?": "Yes", "Notes": "applied 9/21", "Priority": "Medium",
            }),
            row("bbb", "2026-09-29T08:00:00+00:00", **{
                "Opportunity": "Hackathon · Fall 2026", "Category": "Hackathon / Competition",
                "Raw Text": "hackathon register now", "Source Type": "Post / Reel", "Priority": "Normal",
                "Instagram Source": "https://www.instagram.com/p/abc/",  # no apply link: must stay blank
            }),
            row("ccc", "2026-08-01T08:00:00+00:00", Opportunity="Old thing", Status="Expired", **{"Raw Text": "x"}),
        ]
        legacy.create_workbook(self.tracker)
        legacy.save_records(self.rows, self.tracker)
        self.cache.write_text(json.dumps({
            "version": 1,
            "pages": {"https://stripe.com/jobs/1": {"status": "open", "title": "SWE Intern"}},
            "llm": {"abc123": {"is_opportunity": True, "organization": "Stripe"}},
        }))

    def migrate(self):
        with Store(self.db) as store:
            return migrate(store, self.tracker, self.cache, "kevin")

    def test_migrate_twice_is_identical(self):
        first = self.migrate()
        self.assertEqual(first, {"opportunities": 3, "skipped": 0, "actions": 1, "enrichment": 2})
        with Store(self.db) as store:
            ids = [r["ID"] for r in legacy_records(store, "kevin")]
        self.assertEqual(self.migrate(), first)
        with Store(self.db) as store:
            self.assertEqual([r["ID"] for r in legacy_records(store, "kevin")], ids)
            self.assertEqual(ids, ["aaa", "bbb", "ccc"])
            counts = [store.conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                      for t in ("opportunities", "items", "actions", "enrichment")]
        self.assertEqual(counts, [3, 3, 1, 2])

    def test_migration_keeps_manual_fields_and_never_overwrites_db_edits(self):
        self.migrate()
        with Store(self.db) as store:
            self.assertEqual(store.get_opportunity("aaa", user_id="kevin")["action"]["notes"], "applied 9/21")
            store.set_action("aaa", "kevin", notes="interview booked")
            store.set_action("bbb", "kevin", status="ignored")
            self.assertEqual(store.get_enrichment("page:https://stripe.com/jobs/1")["status"], "open")
        self.migrate()
        with Store(self.db) as store:
            self.assertEqual(store.get_opportunity("aaa", user_id="kevin")["action"]["notes"], "interview booked")
            self.assertEqual(store.get_opportunity("bbb", user_id="kevin")["action"]["status"], "ignored")

    def test_legacy_view_shows_only_its_users_actions_and_every_opportunity_once(self):
        """The join must scope by user inside ON, not WHERE: a WHERE would drop
        every opportunity this user hasn't actioned, and no scope at all would
        duplicate a row both users actioned."""
        self.migrate()
        with Store(self.db) as store:
            store.set_action("aaa", "friend", status="applied", notes="friend's note")
            store.set_action("bbb", "friend", status="applied")
            records = {r["ID"]: r for r in legacy_records(store, "kevin")}
        self.assertEqual(sorted(records), ["aaa", "bbb", "ccc"])
        self.assertEqual(records["aaa"]["Notes"], "applied 9/21")
        self.assertEqual(records["bbb"]["Actioned?"], "No")

    def test_imported_rows_are_already_open_not_drops(self):
        self.migrate()
        with Store(self.db) as store:
            mine = {"instagram.zero2sudo"}
            self.assertEqual(len(store.list_opportunities(source_names=mine, backfill=True)), 3)
            self.assertEqual(store.list_opportunities(source_names=mine, backfill=False), [])

    def test_a_link_another_opportunity_already_holds_is_not_imported_twice(self):
        with Store(self.db) as store:
            store.upsert_item(item(source="ats.greenhouse.stripe", external_id="9", url="https://stripe.com/jobs/1"),
                              opportunity_id="board1")
        result = self.migrate()
        self.assertEqual((result["opportunities"], result["skipped"]), (2, 1))
        with Store(self.db) as store:
            self.assertIsNone(store.get_opportunity("aaa"))
            self.assertEqual(store.get_opportunity("board1", user_id="kevin")["action"]["notes"], "applied 9/21",
                             "the skipped row's note follows the job it duplicates")
        self.assertEqual(self.migrate(), result, "re-running changes nothing")

    def test_missing_enrichment_cache_is_fine(self):
        self.cache.unlink()
        self.assertEqual(self.migrate()["enrichment"], 0)

    def test_views_match_legacy_writers_byte_for_byte(self):
        self.migrate()
        now = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
        expected_md = self.dir / "expected.md"
        legacy.write_live_view(legacy.workbook_records(self.tracker), now, expected_md)
        out_xlsx, out_md = self.dir / "out.xlsx", self.dir / "LATEST.md"
        with Store(self.db) as store:
            write_views(store, "kevin", out_xlsx, out_md, now)
        self.assertEqual(out_md.read_bytes(), expected_md.read_bytes())
        self.assertEqual(legacy.workbook_records(out_xlsx), legacy.workbook_records(self.tracker))


if __name__ == "__main__":
    unittest.main()
