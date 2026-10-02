"""Nightly SQLite backup (T10): the stdlib backup API copies a live WAL database
page by page through SQLite itself, so it's safe against a writer that's still
running (unlike copying the .db file, which can miss rows still only in -wal)."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

STAMP = "%Y%m%dT%H%M%SZ"
PATTERN = "radar-*.db"


def backup_once(db_path, backup_dir=None, keep=14, now=lambda: datetime.now(timezone.utc)) -> Path:
    db_path = Path(db_path)
    if not db_path.exists():
        # sqlite3.connect() silently creates a fresh, empty db otherwise -- a wrong
        # RADAR_DB_PATH would then "back up" nothing every night and look healthy.
        raise FileNotFoundError(f"no database at {db_path}")
    backup_dir = Path(backup_dir) if backup_dir else db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = now().strftime(STAMP)
    dest = backup_dir / f"radar-{stamp}.db"
    src = sqlite3.connect(db_path)
    try:
        out = sqlite3.connect(dest)
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    _prune(backup_dir, keep)
    return dest


def _prune(backup_dir: Path, keep: int):
    stale = sorted(backup_dir.glob(PATTERN))[:-keep] if keep > 0 else sorted(backup_dir.glob(PATTERN))
    for path in stale:
        path.unlink()
