"""The store as legacy tracker rows (what migrate_legacy imports and the tests round-trip)."""
from __future__ import annotations

import json

from radar.legacy import opportunity_monitor as legacy

# Tracker column -> opportunities column. Every other tracker column lives in
# opportunities.fields, except Actioned?/Notes, which come from actions.
CORE_COLUMNS = {
    "Organization": "company",
    "Opportunity": "title",
    "Application / Registration Link": "url",
    "Location": "location",
    "Status": "status",
    "Deadline": "deadline",
    "Posted At": "published_at",
}
MANUAL_COLUMNS = ("ID", "First Seen", "Actioned?", "Notes")
FIELD_COLUMNS = tuple(h for h in legacy.HEADERS if h not in CORE_COLUMNS and h not in MANUAL_COLUMNS)


def is_actioned(status):
    return bool(status) and status != "new"


def legacy_records(store, user_id):
    """Every opportunity as a tracker row, in insertion (= workbook) order, with
    one user's Actioned?/Notes. The user scope is in the join's ON, not a
    WHERE: a WHERE would drop every opportunity this user never actioned."""
    rows = store.conn.execute(
        """SELECT o.*, a.status AS action_status, a.notes AS action_notes
           FROM opportunities o
           LEFT JOIN actions a ON a.opportunity_id = o.id AND a.user_id = ?
           ORDER BY o.rowid""",
        (user_id,),
    )
    records = []
    for row in rows:
        fields = json.loads(row["fields"])
        record = {
            "ID": row["id"],
            "First Seen": row["first_seen"],
            "Actioned?": "Yes" if is_actioned(row["action_status"]) else "No",
            "Notes": row["action_notes"] or "",
        }
        record.update({header: row[column] or "" for header, column in CORE_COLUMNS.items()})
        record.update({header: fields.get(header, "") for header in FIELD_COLUMNS})
        records.append({header: record[header] for header in legacy.HEADERS})
    return records

