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
SOURCE_STATE_COLUMNS = ("etag", "cursor", "last_ok", "fail_count", "next_run", "last_error")
# MIGRATIONS[i] upgrades PRAGMA user_version i -> i + 1, atomically. Append only.
MIGRATIONS = (
    "ALTER TABLE source_state ADD COLUMN last_error TEXT",  # 1: scheduler health (T2)
    "ALTER TABLE alerts ADD COLUMN drop_latency_s REAL",     # 2: alerts latency metric (T7)
)


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
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        for number, sql in enumerate(MIGRATIONS[version:], start=version + 1):
            self.conn.executescript(f"BEGIN; {sql}; PRAGMA user_version = {number}; COMMIT;")

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

        A (source, external_id) already on file keeps the opportunity_id it was
        first stored under (e.g. a migrated row's kept legacy id) rather than
        recomputing one from this Item's url: otherwise re-polling an
        already-migrated, still-open posting would mint a second, orphaned
        opportunities row that no item points to. item.opportunity_id (the
        url-hash dedupe key) is only used the first time this (source,
        external_id) pair is seen.
        """
        if opportunity_id is None:
            existing = self.conn.execute(
                "SELECT opportunity_id FROM items WHERE source = ? AND external_id = ?",
                (item.source, item.external_id),
            ).fetchone()
            opportunity_id = existing[0] if existing else item.opportunity_id
        opp_id = opportunity_id
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

    def item_opportunity_id(self, source, external_id):
        """The opportunity a (source, external_id) is already filed under, or None."""
        row = self.conn.execute(
            "SELECT opportunity_id FROM items WHERE source = ? AND external_id = ?", (source, external_id)
        ).fetchone()
        return row[0] if row else None

    def opportunity_id_for_url(self, url):
        """An existing opportunity with this exact (already-canonicalized) url, or None."""
        row = self.conn.execute("SELECT id FROM opportunities WHERE url = ? LIMIT 1", (url,)).fetchone()
        return row[0] if row else None

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

    # ---- source state (scheduler) ------------------------------------------

    def get_source_state(self, name):
        row = self.conn.execute("SELECT * FROM source_state WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None

    def save_source_state(self, name, **columns):
        unknown = set(columns) - set(SOURCE_STATE_COLUMNS)
        if unknown:
            raise ValueError(f"unknown source_state columns: {sorted(unknown)}")
        columns = {"name": name, **{k: _iso(v) for k, v in columns.items()}}
        updates = ", ".join(f"{k} = excluded.{k}" for k in columns if k != "name")
        with self.conn:
            self.conn.execute(
                f"INSERT INTO source_state ({', '.join(columns)}) VALUES ({', '.join(':' + k for k in columns)}) "
                f"ON CONFLICT(name) DO " + (f"UPDATE SET {updates}" if updates else "NOTHING"),
                columns,
            )

    def count_items(self, source, since):
        return self.conn.execute(
            "SELECT count(*) FROM items WHERE source = ? AND seen_at >= ?", (source, _iso(since))
        ).fetchone()[0]

    # ---- alerts, actions, enrichment -------------------------------------

    def record_alert(self, opportunity_id, channel, sent_at=None):
        """Claim the (opportunity, channel) alert slot. True only the first time."""
        with self.conn:
            cursor = self.conn.execute(
                "INSERT OR IGNORE INTO alerts (opportunity_id, channel, sent_at) VALUES (?, ?, ?)",
                (opportunity_id, channel, _iso(sent_at)),
            )
        return cursor.rowcount == 1

    def get_alert(self, opportunity_id, channel):
        """The claimed/sent row for (opportunity, channel), or None if never claimed.

        sent_at is None while claimed-but-not-sent: a crash between record_alert
        and mark_alert_sent leaves it pending, safe to retry, never a duplicate.
        """
        row = self.conn.execute(
            "SELECT sent_at, drop_latency_s FROM alerts WHERE opportunity_id = ? AND channel = ?",
            (opportunity_id, channel),
        ).fetchone()
        return dict(row) if row else None

    def pending_alerts(self):
        """[{"opportunity_id", "channel"}] claimed but never sent -- safe to retry."""
        rows = self.conn.execute("SELECT opportunity_id, channel FROM alerts WHERE sent_at IS NULL").fetchall()
        return [dict(r) for r in rows]

    def mark_alert_sent(self, opportunity_id, channel, sent_at, drop_latency_s=None):
        with self.conn:
            self.conn.execute(
                "UPDATE alerts SET sent_at = ?, drop_latency_s = ? WHERE opportunity_id = ? AND channel = ?",
                (_iso(sent_at), drop_latency_s, opportunity_id, channel),
            )

    def alert_latencies(self):
        """[{"source", "channel", "drop_latency_s"}] for every sent alert, earliest item's source."""
        rows = self.conn.execute(
            """SELECT a.channel, a.drop_latency_s,
                      (SELECT i.source FROM items i WHERE i.opportunity_id = a.opportunity_id
                       ORDER BY i.seen_at LIMIT 1) AS source
               FROM alerts a WHERE a.sent_at IS NOT NULL AND a.drop_latency_s IS NOT NULL"""
        ).fetchall()
        return [dict(r) for r in rows]

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
