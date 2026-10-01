"""Import the legacy tracker workbook and enrichment cache into the store.

Idempotent: re-running updates the same rows. Tracker IDs and First Seen are
kept; Actioned?/Notes never overwrite what the store already holds.

    python -m radar.store.migrate_legacy [--tracker X.xlsx] [--cache enrichment_cache.json] [--db data/radar.db]
                                         [--user kevin]

The legacy tracker's Actioned?/Notes belong to one person: --user.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from radar.config import load_settings
from radar.legacy import opportunity_monitor as legacy
from radar.models import Item, utcnow
from radar.store import Store
from radar.views import CORE_COLUMNS, FIELD_COLUMNS, is_actioned

SOURCE = f"instagram.{legacy.USERNAME}"


def _dt(value):
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _import_row(store, row):
    columns = {column: row[header] for header, column in CORE_COLUMNS.items()}
    columns["published_at"] = row["Posted At"] or None
    store.save_opportunity(
        row["ID"], row["First Seen"], fields={header: row[header] for header in FIELD_COLUMNS}, **columns
    )
    # One Instagram sighting per row, keyed like the legacy dedupe (media ID
    # first), so the new Instagram source recognises what is already tracked.
    store.upsert_item(Item(
        source=SOURCE,
        external_id=legacy.record_semantic_key(row),
        url=row["Application / Registration Link"],  # canonical link only; never fill it with the permalink
        title=row["Opportunity"],
        raw={"instagram_source": row["Instagram Source"], "source_type": row["Source Type"]},
        published_at=_dt(row["Posted At"]),
        seen_at=_dt(row["First Seen"]) or utcnow(),
    ), opportunity_id=row["ID"])


def _import_manual_fields(store, row, user_id):
    actioned, notes = legacy.is_yes(row["Actioned?"]), str(row["Notes"]).strip()
    if not actioned and not notes:
        return False
    current = (store.get_opportunity(row["ID"], user_id=user_id) or {}).get("action")
    if current is None:
        store.set_action(row["ID"], user_id, status="actioned" if actioned else "", notes=notes)
    else:
        store.set_action(
            row["ID"], user_id,
            status="actioned" if actioned and not is_actioned(current["status"]) else None,
            notes=notes if notes and not current["notes"] else None,
        )
    return True


def migrate(store, tracker, cache, user_id):
    """Returns counts: opportunities imported, rows carrying manual fields, enrichment entries."""
    rows = [
        {header: "" if record.get(header) is None else record.get(header) for header in legacy.HEADERS}
        for record in legacy.workbook_records(Path(tracker))
    ]
    rows = [row for row in rows if row["ID"]]
    actions = 0
    for row in rows:
        row["First Seen"] = row["First Seen"] or row["Posted At"] or utcnow().isoformat()
        _import_row(store, row)
        actions += _import_manual_fields(store, row, user_id)
    enrichment = 0
    try:
        cached = json.loads(Path(cache).read_text())
    except FileNotFoundError:
        cached = {}
    for prefix, section in (("page:", "pages"), ("llm:", "llm")):
        for key, value in (cached.get(section) or {}).items():
            store.set_enrichment(prefix + key, value)
            enrichment += 1
    return {"opportunities": len(rows), "actions": actions, "enrichment": enrichment}


def main():
    parser = argparse.ArgumentParser(description="Import the legacy tracker into the store.")
    parser.add_argument("--tracker", default=str(legacy.TRACKER_PATH))
    parser.add_argument("--cache", default=str(legacy.ENRICHMENT_PATH))
    parser.add_argument("--db", default=load_settings().db_path)
    parser.add_argument("--user", default="kevin", help="whose Actioned?/Notes these are")
    args = parser.parse_args()
    with Store(args.db) as store:
        print(json.dumps(migrate(store, args.tracker, args.cache, args.user)))


if __name__ == "__main__":
    main()
