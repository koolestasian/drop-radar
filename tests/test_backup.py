import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from radar.backup import backup_once
from radar.models import Item
from radar.store import Store

T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db_path = self.dir / "radar.db"

    def test_backup_captures_rows_still_only_in_the_wal(self):
        """A plain file copy of just radar.db can miss writes still sitting in
        radar.db-wal; the stdlib backup API reads through SQLite so it can't."""
        store = Store(self.db_path)
        self.addCleanup(store.close)
        store.upsert_item(Item(source="s", external_id="1", url="https://x/1", title="SWE Intern"))
        self.assertTrue((self.dir / "radar.db-wal").exists(), "expected WAL-resident, uncheckpointed writes")

        dest = backup_once(self.db_path, now=lambda: T0)
        self.assertEqual(dest, self.dir / "backups" / "radar-20261001T000000Z.db")

        restored = sqlite3.connect(dest)
        try:
            rows = restored.execute("SELECT external_id FROM items").fetchall()
        finally:
            restored.close()
        self.assertEqual(rows, [("1",)])

    def test_restoring_a_backup_through_a_fresh_store_sees_the_same_data(self):
        store = Store(self.db_path)
        self.addCleanup(store.close)
        store.upsert_item(Item(source="s", external_id="1", url="https://x/1", title="SWE Intern"))
        dest = backup_once(self.db_path, now=lambda: T0)

        with Store(dest) as restored:
            self.assertEqual(len(restored.list_opportunities()), 1)

    def test_keeps_only_the_most_recent_n_backups(self):
        Store(self.db_path).close()
        for day in range(20):
            backup_once(self.db_path, keep=14, now=lambda day=day: T0 + timedelta(days=day))
        backups = sorted(p.name for p in (self.dir / "backups").glob("radar-*.db"))
        self.assertEqual(len(backups), 14)
        self.assertEqual(backups[0], "radar-20261007T000000Z.db")  # day 6, oldest kept (0-5 pruned)
        self.assertEqual(backups[-1], "radar-20261020T000000Z.db")  # day 19, newest

    def test_a_missing_db_raises_instead_of_silently_backing_up_nothing(self):
        """sqlite3.connect() would otherwise create an empty db at a wrong
        RADAR_DB_PATH and "back it up" every night, looking healthy."""
        with self.assertRaises(FileNotFoundError):
            backup_once(self.dir / "no-such.db")
        self.assertFalse((self.dir / "backups").exists())

    def test_default_backup_dir_sits_next_to_the_db(self):
        Store(self.db_path).close()
        custom = self.dir / "elsewhere" / "radar.db"
        custom.parent.mkdir()
        Store(custom).close()
        dest = backup_once(custom, now=lambda: T0)
        self.assertEqual(dest.parent, custom.parent / "backups")


if __name__ == "__main__":
    unittest.main()
