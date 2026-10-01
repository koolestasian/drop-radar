"""SQLite (WAL) store: the source of truth. xlsx, LATEST.md and the Sheet are views."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from radar.models import Item, utcnow

SCHEMA = Path(__file__).with_name("schema.sql")
# Columns save_opportunity may set; guards the column names it interpolates into SQL.
OPPORTUNITY_COLUMNS = ("title", "url", "company", "location", "status", "deadline", "published_at", "fields")


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


class Store:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA.read_text())

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ---- opportunities and items ---------------------------------------

    def save_opportunity(self, id, first_seen, **columns):
        """Insert or overwrite the given columns; first_seen only ever moves earlier."""
        unknown = set(columns) - set(OPPORTUNITY_COLUMNS)
        if unknown:
            raise ValueError(f"unknown opportunity columns: {sorted(unknown)}")
        if "fields" in columns:
            columns["fields"] = json.dumps(columns["fields"], ensure_ascii=False, sort_keys=True)
        columns = {"id": id, "first_seen": _iso(first_seen), **{k: _iso(v) for k, v in columns.items()}}
        names = ", ".join(columns)
        updates = ", ".join(f"{k} = excluded.{k}" for k in columns if k not in ("id", "first_seen"))
        with self.conn:
            self.conn.execute(
                f"INSERT INTO opportunities ({names}) VALUES ({', '.join(':' + k for k in columns)}) "
                f"ON CONFLICT(id) DO UPDATE SET first_seen = min(first_seen, excluded.first_seen)"
                + (f", {updates}" if updates else ""),
                columns,
            )

    def upsert_item(self, item: Item, opportunity_id=None):
        """Record a sighting. Returns (opportunity_id, is_new_opportunity); safe to repeat.

        An existing opportunity only gets blanks filled and earlier timestamps,
        so the first source to see it keeps its title and first_seen.
        """
        opp_id = opportunity_id or item.opportunity_id
        values = {
            "id": opp_id, "source": item.source, "external_id": item.external_id, "url": item.url,
            "title": item.title, "company": item.company, "location": item.location,
            "published_at": _iso(item.published_at), "seen_at": _iso(item.seen_at),
            "raw": json.dumps(item.raw, ensure_ascii=False, sort_keys=True, default=str),
        }
        with self.conn:
            new = self.conn.execute("SELECT 1 FROM opportunities WHERE id = ?", (opp_id,)).fetchone() is None
            self.conn.execute(
                """INSERT INTO opportunities (id, title, url, company, location, first_seen, published_at)
                   VALUES (:id, :title, :url, :company, :location, :seen_at, :published_at)
                   ON CONFLICT(id) DO UPDATE SET
                     title = CASE WHEN title = '' THEN excluded.title ELSE title END,
                     url = CASE WHEN url = '' THEN excluded.url ELSE url END,
                     company = CASE WHEN company = '' THEN excluded.company ELSE company END,
                     location = CASE WHEN location = '' THEN excluded.location ELSE location END,
                     first_seen = min(first_seen, excluded.first_seen),
                     published_at = coalesce(min(published_at, excluded.published_at),
                                             published_at, excluded.published_at)""",
                values,
            )
            self.conn.execute(
                """INSERT INTO items (source, external_id, opportunity_id, url, title, published_at,
                                      seen_at, last_seen_at, raw)
                   VALUES (:source, :external_id, :id, :url, :title, :published_at, :seen_at, :seen_at, :raw)
                   ON CONFLICT(source, external_id) DO UPDATE SET
                     last_seen_at = max(last_seen_at, excluded.last_seen_at)""",
                values,
            )
        return opp_id, new

    def mark_seen(self, source, external_id, at=None):
        """Bump an item's last_seen_at (a source still lists it). False if unknown."""
        with self.conn:
            cursor = self.conn.execute(
                "UPDATE items SET last_seen_at = max(last_seen_at, ?) WHERE source = ? AND external_id = ?",
                (_iso(at or utcnow()), source, external_id),
            )
        return cursor.rowcount == 1

    def get_opportunity(self, id):
        row = self.conn.execute("SELECT * FROM opportunities WHERE id = ?", (id,)).fetchone()
        if row is None:
            return None
        opp = dict(row)
        opp["fields"] = json.loads(opp["fields"])
        opp["items"] = [dict(r) for r in self.conn.execute(
            "SELECT * FROM items WHERE opportunity_id = ? ORDER BY seen_at", (id,))]
        action = self.conn.execute("SELECT * FROM actions WHERE opportunity_id = ?", (id,)).fetchone()
        opp["action"] = dict(action) if action else None
        return opp

    def list_opportunities(self, status=None, company=None, since=None, limit=None):
        """Newest first. `since` filters on first_seen."""
        where, params = [], []
        for clause, value in (("status = ?", status), ("company = ?", company), ("first_seen >= ?", _iso(since))):
            if value is not None:
                where.append(clause)
                params.append(value)
        sql = "SELECT * FROM opportunities" + (" WHERE " + " AND ".join(where) if where else "")
        sql += " ORDER BY first_seen DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [dict(r) for r in self.conn.execute(sql, params)]

    # ---- alerts, actions, enrichment -------------------------------------

    def record_alert(self, opportunity_id, channel, sent_at=None):
        """Claim the (opportunity, channel) alert slot. True only the first time."""
        with self.conn:
            cursor = self.conn.execute(
                "INSERT OR IGNORE INTO alerts (opportunity_id, channel, sent_at) VALUES (?, ?, ?)",
                (opportunity_id, channel, _iso(sent_at)),
            )
        return cursor.rowcount == 1

    def set_action(self, opportunity_id, status=None, notes=None):
        """Set the user's status and/or notes; None leaves that field as it is."""
        with self.conn:
            self.conn.execute(
                """INSERT INTO actions (opportunity_id, status, notes, updated_at)
                   VALUES (:id, coalesce(:status, ''), coalesce(:notes, ''), :now)
                   ON CONFLICT(opportunity_id) DO UPDATE SET
                     status = coalesce(:status, status), notes = coalesce(:notes, notes), updated_at = :now""",
                {"id": opportunity_id, "status": status, "notes": notes, "now": _iso(utcnow())},
            )

    def get_enrichment(self, key):
        row = self.conn.execute("SELECT json FROM enrichment WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_enrichment(self, key, value):
        with self.conn:
            self.conn.execute(
                "INSERT INTO enrichment (key, json) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET json = excluded.json",
                (key, json.dumps(value, ensure_ascii=False, sort_keys=True)),
            )
