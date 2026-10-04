"""T18: answer the Jobs list and its counts from in-memory bitsets, not a sort and a scan per request.

Postings are numbered oldest first by (posted key, id), so the newest has the highest bit and no read ever sorts.
Each attribute is one Python int used as a bitset: a filter is an AND, a page is the 30 highest set bits, a count is
a popcount. Results must equal the SQL path in app.py exactly: same twin copy, same order, same cursor.

Freshness: a read-only connection polls PRAGMA data_version (it moves when any other connection commits, and this
one never writes). The poller commits all day (items.last_seen_at), so data_version is always moving and a refresh,
which diffs a per-row signature and recomputes only the rows that changed, costs about 0.6 s on the box. So it runs
rarely: when a new posting is stored (`nudge`, at most every MIN_GAP seconds) and every `every` seconds as the safety
net for writes made by other processes (fix-pages and the like). A nudge is a promise: until a refresh that started
after it has finished and the user's view has caught up (`wanted` and `gen`), lists read SQL, so a drop is never
missing from a list opened right after its push. A user's hidden postings are read per request (see `hidden`), so a
hide shows at once.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
from bisect import bisect_left
from datetime import datetime

from radar.alerts import DEAD_STATUSES, visible_to
from radar.pipeline import roles
from radar.pipeline.filter import is_us_location
from radar.store import SORT_KEYS, Store

HIDDEN = "ignored"
MIN_GAP = 5.0  # seconds between refreshes however many postings arrive
_COLUMNS = "id, title, company, location, status, deadline, published_at, first_seen, fields"
_PRESTIGE_CURSOR = re.compile(r"([0-3])\|(.*)", re.S)
log = logging.getLogger(__name__)


def sql_lower(text):
    """SQLite's lower(): ASCII only. The prestige sort ranks by it, so the index must too."""
    return "".join(c.lower() if c < "\x80" else c for c in text)


def nap(n, every=400):
    """Let other threads (requests, the poller) run now and then inside a long loop that holds the GIL."""
    if n % every == every - 1:
        time.sleep(0.001)


def _bits(mask):
    while mask:
        i = mask.bit_length() - 1
        yield i
        mask ^= 1 << i


class Snapshot:
    """Every posting in sort order plus what does not depend on a user. Never changed once built."""

    def __init__(self, recs):
        recs.sort(key=lambda r: (r["key"], r["id"]))
        self.recs = recs
        self.keys = [(r["key"], r["id"]) for r in recs]
        self.pos = {r["id"]: i for i, r in enumerate(recs)}
        self.level, self.track, self.us = {}, {}, 0
        for i, r in enumerate(recs):
            nap(i)
            bit = 1 << i
            self.level[r["level"]] = self.level.get(r["level"], 0) | bit
            self.track[r["track"]] = self.track.get(r["track"], 0) | bit
            if r["us"]:
                self.us |= bit


class UserView:
    """One user's feed, derived from a Snapshot, their profile and the sources they own."""

    def __init__(self, snap, mine, ok):
        self.snap, self.mine = snap, mine
        self.owned = self.dead = self.you = self.drops = 0
        self.shown = {None: 0, False: 0, True: 0}  # per backfill filter: one copy of each twin among the rows it keeps
        seen = {None: set(), False: set(), True: set()}
        for i in range(len(snap.recs) - 1, -1, -1):  # newest first, so the first copy of a twin is the one shown
            r = snap.recs[i]
            nap(i)
            if not any(s in mine for s, _ in r["items"]):
                continue
            bit, drop = 1 << i, self.is_drop(r)
            self.owned |= bit
            self.drops |= bit if drop else 0
            self.dead |= bit if r["status"] in DEAD_STATUSES else 0
            self.you |= bit if ok[r["id"]] else 0
            twin = (r["company"].lower(), r["title"].lower().strip(), r["location"].lower().strip())
            for flag in (None, not drop):  # the filter backfill=False keeps drops, backfill=True keeps the rest
                if twin not in seen[flag]:
                    seen[flag].add(twin)
                    self.shown[flag] |= bit
        self._since, self._tiers = {}, {}

    def is_drop(self, r):
        """Some source of the user's saw it as a new drop, not already open on a first poll."""
        return any(not seed for s, seed in r["items"] if s in self.mine)

    def posted_since(self, day):
        """Rows posted on or after `day` the way the list tests it: the posting's own date, else (a live drop only)
        the day it was first seen; undated backfill never matches."""
        if day not in self._since:
            mask = 0
            for i, r in enumerate(self.snap.recs):
                nap(i)
                posted = r["posted_day"] if r["published_at"] else (r["found_day"] if self.is_drop(r) else None)
                mask |= 1 << i if posted is not None and posted >= day else 0
            self._since[day] = mask
        return self._since[day]

    def tiers(self, ranks):
        key = tuple(sorted(ranks.items()))
        if key not in self._tiers:
            tiers = dict.fromkeys(range(4), 0)
            for i, r in enumerate(self.snap.recs):
                nap(i)
                tiers[ranks.get(sql_lower(r["company"]), 1)] |= 1 << i
            self._tiers = {key: tiers}  # one ranking per user is ever in use
        return self._tiers[key]

    def positions(self, mask, sort, ranks, after):
        """Positions of the rows in `mask` in list order, resuming after the cursor (sort_key, id)."""
        keys = self.snap.keys
        if sort != "prestige":
            yield from _bits(mask & ((1 << bisect_left(keys, after)) - 1) if after else mask)
            return
        cursor = _PRESTIGE_CURSOR.fullmatch(after[0]) if after else None
        if after and not cursor:
            return
        for tier, tmask in sorted(self.tiers(ranks).items(), reverse=True):
            if cursor and tier > int(cursor[1]):
                continue
            m = mask & tmask
            if cursor and tier == int(cursor[1]):
                m &= (1 << bisect_left(keys, (cursor[2], after[1]))) - 1
            yield from _bits(m)

    def sort_key(self, i, sort, ranks):
        r = self.snap.recs[i]
        return f"{ranks.get(sql_lower(r['company']), 1)}|{r['key']}" if sort == "prestige" else r["key"]


class BitIndex:
    def __init__(self, store, every=60.0):
        # the connection opens on first use; the path is read here, on the thread that owns the store's connection
        self.every, self.conn = every, None
        self.wanted = self.snap_gen = 0  # nudges so far; the nudges the snapshot is known to include
        self.path = store.conn.execute("PRAGMA database_list").fetchone()["file"] if store is not None else None
        self.lock = threading.Lock()  # one refresh or view build at a time; requests meanwhile use what is there
        self.recs, self.snap, self.version, self.at = {}, None, None, 0.0
        self.views = {}  # user id -> (UserView, profile, {id: (signature, matches)}, user, mine)

    # ---- keeping the snapshot current ------------------------------------

    def nudge(self):
        """A posting was just stored: look again soon (called on the pipeline's thread, so it only starts a worker)."""
        self.wanted += 1
        if self.snap is not None and time.monotonic() - self.at >= MIN_GAP and not self.lock.locked():
            threading.Thread(target=self.safely, args=(None, None), daemon=True).start()

    def refresh(self, force=False, min_gap=0.0):
        """Bring the snapshot up to date. Does nothing when no other connection has committed since."""
        with self.lock:
            if self.snap is not None and time.monotonic() - self.at < min_gap:
                return
            gen, started = self.wanted, time.monotonic()  # read before scanning: a commit before a nudge is in the scan
            if self.conn is None:
                self.conn = sqlite3.connect(self.path, check_same_thread=False)
                self.conn.row_factory = sqlite3.Row
            version = self.conn.execute("PRAGMA data_version").fetchone()[0]
            if self.snap is not None and version == self.version and not force:
                self.at, self.snap_gen = time.monotonic(), gen
                return
            items, n = {}, 0
            for oid, source, seed in self.conn.execute(
                    "SELECT opportunity_id, source, coalesce(json_extract(raw, '$.seed'), 0) FROM items ORDER BY seen_at"):
                nap(n := n + 1)
                items.setdefault(oid, []).append((source, int(bool(seed))))
            recs, changed = {}, []
            for row in self.conn.execute(f"SELECT {_COLUMNS} FROM opportunities"):
                nap(n := n + 1)
                sig = (*tuple(row), tuple(items.get(row["id"], ())))
                prev = self.recs.get(row["id"])
                if prev is not None and prev["sig"] == sig:
                    recs[row["id"]] = prev
                else:
                    changed.append((row, sig))
            if changed:  # one scan when much changed (first build), one lookup per row when little
                keys = ({k: v for k, v in self.conn.execute(f"SELECT id, {SORT_KEYS['posted']} FROM opportunities")}
                        if len(changed) > 50 else {})
                for n, (row, sig) in enumerate(changed):
                    nap(n)
                    key = keys[row["id"]] if keys else self.conn.execute(
                        f"SELECT {SORT_KEYS['posted']} FROM opportunities WHERE id = ?", (row["id"],)).fetchone()[0]
                    recs[row["id"]] = self._record(row, sig, key, items.get(row["id"], []))
            if changed or len(recs) != len(self.recs) or self.snap is None:
                self.snap = Snapshot(list(recs.values()))
            self.recs, self.version, self.snap_gen = recs, version, gen
            self.at = time.monotonic()
            log.info("bit index: scanned %d postings, %d changed, in %.0f ms", len(recs), len(changed),
                     (time.monotonic() - started) * 1000)

    @staticmethod
    def _record(row, sig, key, items):
        fields = json.loads(row["fields"] or "{}")
        pub, seen = row["published_at"], row["first_seen"]
        return {
            "id": row["id"], "sig": sig, "key": key, "title": row["title"], "company": row["company"],
            "location": row["location"], "status": row["status"], "published_at": pub, "items": items,
            "level": roles.level(row["title"], fields.get("Category", "")),
            "track": roles.track(row["title"], fields.get("Role / Track", "")),
            "us": is_us_location(row["location"]) is True,
            "posted_day": datetime.fromisoformat(pub).date() if pub else None,
            "found_day": datetime.fromisoformat(seen).date() if seen else None,
        }

    # ---- one user's view -------------------------------------------------

    def view(self, user, mine, background=True):
        """The user's UserView. In the background mode it never waits: a stale snapshot is served while a worker
        thread refreshes it, and None means there is nothing for this user yet (the caller reads SQL meanwhile)."""
        have = self.views.get(user.id)
        usable = have is not None and have[0].mine == mine and have[1] == user.profile
        if not background:
            self.refresh()
            self.update(user, mine)
            return self.views[user.id][0]
        current = usable and have[0].gen >= self.wanted  # a stale view is fine for the 60 s net, not after a nudge
        pending = self.wanted > self.snap_gen
        due = self.snap is None or time.monotonic() - self.at >= (MIN_GAP if pending else self.every)
        if (due or not current or have[0].snap is not self.snap) and not self.lock.locked():
            threading.Thread(target=self.safely, args=(user, mine, due or (usable and not current)), daemon=True).start()
        return have[0] if current else None

    def safely(self, user, mine, refresh=True):
        """A worker thread's entry: refresh (when asked), then bring this user's view up to date, or every existing
        view when no user is given (a nudge: the views that exist are the people who may open Jobs next)."""
        try:
            if refresh:
                self.refresh(min_gap=MIN_GAP)
            # ponytail: every view that exists is rebuilt per nudge burst (about 0.3 s of CPU each); at hundreds of
            # active accounts, rebuild only the ones that ask
            for who, owns in [(user, mine)] if user is not None else [(v[3], v[4]) for v in list(self.views.values())]:
                self.update(who, owns)
        except Exception:
            log.exception("bit index update failed")

    def update(self, user, mine):
        """Bring this user's view up to date with the snapshot (matches recomputed only for changed rows)."""
        if self.snap is None:
            self.refresh()
        with self.lock:
            snap, have = self.snap, self.views.get(user.id)
            same_basis = have is not None and have[0].mine == mine and have[1] == user.profile
            cache = have[2] if same_basis else {}
            todo = [r for r in snap.recs if cache.get(r["id"], (None,))[0] is not r["sig"]]
            if same_basis and not todo and have[0].snap is snap:
                have[0].gen = self.snap_gen
                return
            if todo:
                with Store(self.path) as db:  # visible_to wants the whole opportunity, as the list does
                    for n, r in enumerate(todo):
                        if n % 200 == 199:
                            time.sleep(0.01)  # a first build is seconds of work: let the poller and requests in
                        cache[r["id"]] = (r["sig"], visible_to(db.get_opportunity(r["id"], user_id=user.id),
                                                               user.profile, mine)[1])
            ok, started = {r["id"]: cache[r["id"]][1] for r in snap.recs}, time.monotonic()
            view = UserView(snap, mine, ok)
            view.gen = self.snap_gen
            self.views[user.id] = (view, user.profile, {i: cache[i] for i in ok}, user, mine)
            log.info("bit index: %s's view built (%d matches recomputed, view %.0f ms)", user.id, len(todo),
                     (time.monotonic() - started) * 1000)

    @staticmethod
    def hidden(conn, user_id, snap):
        """The user's own ignored postings, read fresh so a hide shows at once. `conn` is the caller's own."""
        mask = 0
        for (oid,) in conn.execute("SELECT opportunity_id FROM actions WHERE user_id = ? AND status = ?",
                                   (user_id, HIDDEN)):
            mask |= 1 << snap.pos[oid] if oid in snap.pos else 0
        return mask

    def close(self):
        if self.conn is not None:
            self.conn.close()


def pill_counts(snap, scope):
    """{"total", "level:x", "track:y"}: how many of the rows in `scope` have each attribute."""
    counts = {"total": scope.bit_count()}
    counts.update({"level:" + name: n for name, bits in snap.level.items() if name and (n := (scope & bits).bit_count())})
    counts.update({"track:" + name: n for name, bits in snap.track.items() if (n := (scope & bits).bit_count())})
    return counts
