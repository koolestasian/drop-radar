"""Generated views of the store: the tracker workbook and LATEST.md, via the legacy writers."""
from __future__ import annotations

import json
from pathlib import Path

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


def legacy_records(store):
    """Every opportunity as a tracker row, in insertion (= workbook) order."""
    rows = store.conn.execute(
        """SELECT o.*, a.status AS action_status, a.notes AS action_notes
           FROM opportunities o LEFT JOIN actions a ON a.opportunity_id = o.id
           ORDER BY o.rowid"""
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


def write_views(store, tracker=None, latest=None, now=None):
    """Regenerate the workbook and LATEST.md from the store."""
    tracker = Path(tracker or legacy.TRACKER_PATH)
    records = legacy_records(store)
    if not tracker.exists():
        legacy.create_workbook(tracker)
    legacy.save_records(records, tracker)
    legacy.write_live_view(records, now, Path(latest or legacy.LIVE_VIEW_PATH))
    return len(records)
