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
    # 3: actions become per-user (T8a). SQLite can't ALTER a primary key, so rebuild;
    # every action recorded before multi-user support belonged to the one user there was.
    """CREATE TABLE actions_new (
           opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
           user_id        TEXT NOT NULL,
           status         TEXT NOT NULL DEFAULT '',
           notes          TEXT NOT NULL DEFAULT '',
           updated_at     TEXT NOT NULL,
           PRIMARY KEY (opportunity_id, user_id)
       );
       INSERT INTO actions_new (opportunity_id, user_id, status, notes, updated_at)
           SELECT opportunity_id, 'kevin', status, notes, updated_at FROM actions;
       DROP TABLE actions;
       ALTER TABLE actions_new RENAME TO actions""",
    "ALTER TABLE accounts ADD COLUMN ntfy_topic TEXT",  # 4: an account's own phone-alert topic (NULL = alerts off)
)


# Stored timestamps carry mixed offsets ("-04:00", "+00:00"), so compare them as UTC.
_FOUND = "strftime('%Y-%m-%dT%H:%M:%f', first_seen)"
SORT_KEYS = {
    "found": _FOUND,
    # Date-only postings are stored as midnight UTC; they count as late that day as the
    # sighting allows, so "posted Oct 2" doesn't sink below "posted Oct 2, 01:29".
    # No posting date: a live drop's found time is a fair stand-in (it was caught soon after
    # posting); a first-poll backfill's says nothing (it can be months old), so it sorts last.
    "posted": f"""CASE WHEN published_at IS NULL THEN CASE WHEN EXISTS (SELECT 1 FROM items i
            WHERE i.opportunity_id = opportunities.id AND coalesce(json_extract(i.raw, '$.seed'), 0) = 0)
            THEN {_FOUND} ELSE '' END
        WHEN published_at LIKE '%T00:00:00+00:00' THEN min({_FOUND}, date(published_at) || 'T23:59:59.999')
        ELSE strftime('%Y-%m-%dT%H:%M:%f', published_at) END""",
}


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

    def recanonicalize_urls(self, canonical):
        """Rewrite opportunities.url through `canonical` where it differs, so URL dedupe
        still matches rows stored before a canonical_url rule existed. Ids never change.
        Returns how many rows changed; a second call returns 0."""
        rows = self.conn.execute("SELECT id, url FROM opportunities WHERE url != ''").fetchall()
        changed = [(new, row["id"]) for row in rows if (new := canonical(row["url"])) != row["url"]]
        with self.conn:
            self.conn.executemany("UPDATE opportunities SET url = ? WHERE id = ?", changed)
        return len(changed)

    def mark_seen(self, source, external_id, at=None):
        """Bump an item's last_seen_at (a source still lists it). False if unknown."""
        with self.conn:
            cursor = self.conn.execute(
                "UPDATE items SET last_seen_at = max(last_seen_at, ?) WHERE source = ? AND external_id = ?",
                (_iso(at or utcnow()), source, external_id),
            )
        return cursor.rowcount == 1

    def get_opportunity(self, id, user_id=None):
        """With user_id, opp["action"] is that user's status/notes (or None).
        Without it there is no "action" key at all: one user's private notes
        are never in a dict that isn't explicitly theirs."""
        row = self.conn.execute("SELECT * FROM opportunities WHERE id = ?", (id,)).fetchone()
        if row is None:
            return None
        opp = dict(row)
        opp["fields"] = json.loads(opp["fields"])
        opp["items"] = [dict(r) for r in self.conn.execute(
            "SELECT * FROM items WHERE opportunity_id = ? ORDER BY seen_at", (id,))]
        if user_id is not None:
            action = self.conn.execute(
                "SELECT * FROM actions WHERE opportunity_id = ? AND user_id = ?", (id, user_id)
            ).fetchone()
            opp["action"] = dict(action) if action else None
        return opp

    def list_opportunities(self, *args, **kwargs):
        return list(self.iter_opportunities(*args, **kwargs))

    def iter_opportunities(self, status=None, company=None, since=None, limit=None, source_names=None,
                           backfill=None, sort="found", ranks=None):
        """Newest first by `sort_key` (ties by id, so a cursor can page through): when we first
        saw it ("found") or when it was posted ("posted", see SORT_KEYS). `since` filters on
        first_seen; `source_names` keeps opportunities at least one of those sources saw.
        `backfill` (needs `source_names`): False keeps only what one of them saw as a new
        drop, True only what all of them saw already open on a first poll (raw.seed).
        sort="prestige": `ranks` ({lowercased company: 0-3}, default 1) first, then newest posted."""
        where, params = [], []
        for clause, value in (("status = ?", status), ("company = ?", company), ("first_seen >= ?", _iso(since))):
            if value is not None:
                where.append(clause)
                params.append(value)
        if source_names is not None:
            names = sorted(source_names)
            where.append("EXISTS (SELECT 1 FROM items i WHERE i.opportunity_id = opportunities.id "
                         f"AND i.source IN ({', '.join('?' * len(names)) or 'NULL'}))")
            params.extend(names)
            if backfill is not None:
                where.append(("NOT " if backfill else "") + "EXISTS (SELECT 1 FROM items i WHERE "
                             "i.opportunity_id = opportunities.id AND coalesce(json_extract(i.raw, '$.seed'), 0) = 0 "
                             f"AND i.source IN ({', '.join('?' * len(names)) or 'NULL'}))")
                params.extend(names)
        key, key_params = SORT_KEYS["posted" if sort == "prestige" else sort], []
        if sort == "prestige":
            ranks = ranks or {}
            case = ("CASE lower(company) " + " ".join("WHEN ? THEN ?" for _ in ranks) + " ELSE 1 END") if ranks else "1"
            key = f"({case}) || '|' || ({key})"
            key_params = [x for name, rank in ranks.items() for x in (name, rank)]
        params = key_params + params
        sql = f"SELECT *, {key} AS sort_key FROM opportunities" + (" WHERE " + " AND ".join(where) if where else "")
        sql += " ORDER BY sort_key DESC, id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        # rows are read as the caller asks for them: a page of 30 never pays for 12,000
        return (dict(r) for r in self.conn.execute(sql, params))

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

    def count_alerts_sent(self, channel_like, since):
        """How many pushes went out on channels matching this LIKE pattern (use \\ to escape) since `since`."""
        return self.conn.execute(
            "SELECT count(*) FROM alerts WHERE channel LIKE ? ESCAPE '\\' AND sent_at >= ?",
            (channel_like, _iso(since))).fetchone()[0]

    def alert_latencies(self):
        """[{"source", "channel", "drop_latency_s"}] for every sent alert, earliest item's source."""
        rows = self.conn.execute(
            """SELECT a.channel, a.drop_latency_s,
                      (SELECT i.source FROM items i WHERE i.opportunity_id = a.opportunity_id
                       ORDER BY i.seen_at LIMIT 1) AS source
               FROM alerts a WHERE a.sent_at IS NOT NULL AND a.drop_latency_s IS NOT NULL"""
        ).fetchall()
        return [dict(r) for r in rows]

    def set_action(self, opportunity_id, user_id, status=None, notes=None):
        """Set one user's status and/or notes; None leaves that field as it is.
        user_id has no default, so no caller can write to someone else's row by omission."""
        with self.conn:
            self.conn.execute(
                """INSERT INTO actions (opportunity_id, user_id, status, notes, updated_at)
                   VALUES (:id, :user_id, coalesce(:status, ''), coalesce(:notes, ''), :now)
                   ON CONFLICT(opportunity_id, user_id) DO UPDATE SET
                     status = coalesce(:status, status), notes = coalesce(:notes, notes), updated_at = :now""",
                {"id": opportunity_id, "user_id": user_id, "status": status, "notes": notes,
                 "now": _iso(utcnow())},
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

    # ---- accounts, credentials, sessions ------------------------------------

    def create_account(self, account_id, profile, username, pw_hash):
        """One transaction: the account and its credentials exist together or not at all.
        Raises sqlite3.IntegrityError when the username is taken."""
        now = _iso(utcnow())
        with self.conn:
            self.conn.execute("INSERT INTO accounts (id, created_at, profile) VALUES (?, ?, ?)",
                              (account_id, now, json.dumps(profile, ensure_ascii=False)))
            self.conn.execute("INSERT INTO credentials (username, user_id, pw_hash, created_at) VALUES (?, ?, ?, ?)",
                              (username, account_id, pw_hash, now))

    def count_accounts(self):
        return self.conn.execute("SELECT count(*) FROM accounts").fetchone()[0]

    def list_accounts(self):
        return [dict(r) for r in self.conn.execute(
            "SELECT id, profile, watchlist, ntfy_topic FROM accounts ORDER BY created_at, id")]

    def save_account(self, account_id, profile=None, watchlist=None, ntfy_topic=...):
        """Update the given parts; ntfy_topic=None switches phone alerts off, leaving it out changes nothing."""
        with self.conn:
            if ntfy_topic is not ...:
                self.conn.execute("UPDATE accounts SET ntfy_topic = ? WHERE id = ?", (ntfy_topic, account_id))
            if profile is not None:
                self.conn.execute("UPDATE accounts SET profile = ? WHERE id = ?",
                                  (json.dumps(profile, ensure_ascii=False), account_id))
            if watchlist is not None:
                self.conn.execute("UPDATE accounts SET watchlist = ? WHERE id = ?",
                                  (json.dumps(watchlist, ensure_ascii=False), account_id))

    def get_credentials(self, username):
        row = self.conn.execute("SELECT username, user_id, pw_hash FROM credentials WHERE username = ?",
                                (username,)).fetchone()
        return dict(row) if row else None

    def credentials_for(self, user_id):
        row = self.conn.execute("SELECT username, user_id, pw_hash FROM credentials WHERE user_id = ?",
                                (user_id,)).fetchone()
        return dict(row) if row else None

    def set_credentials(self, user_id, username, pw_hash):
        """Give a user (or change) their username and password. Raises sqlite3.IntegrityError when
        the username belongs to someone else."""
        with self.conn:
            self.conn.execute("DELETE FROM credentials WHERE user_id = ?", (user_id,))
            self.conn.execute("INSERT INTO credentials (username, user_id, pw_hash, created_at) VALUES (?, ?, ?, ?)",
                              (username, user_id, pw_hash, _iso(utcnow())))

    def add_session(self, token_hash, user_id):
        now = _iso(utcnow())
        with self.conn:
            self.conn.execute("INSERT INTO sessions (token_hash, user_id, created_at, last_used) VALUES (?, ?, ?, ?)",
                              (token_hash, user_id, now, now))

    def session_user(self, token_hash, since=None):
        """Who a login session belongs to; sessions created before `since` (ISO) no longer count."""
        row = self.conn.execute("SELECT user_id FROM sessions WHERE token_hash = ? AND created_at >= ?",
                                (token_hash, since or "")).fetchone()
        return row[0] if row else None

    def is_account(self, user_id):
        return self.conn.execute("SELECT 1 FROM accounts WHERE id = ?", (user_id,)).fetchone() is not None

    def delete_session(self, token_hash):
        with self.conn:
            self.conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))

    def delete_user_sessions(self, user_id):
        with self.conn:
            self.conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
