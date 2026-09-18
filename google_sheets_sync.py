#!/usr/bin/env python3
import json


def _column_name(number):
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _credentials(value):
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON.") from exc
    if not isinstance(parsed, dict) or not parsed.get("client_email") or not parsed.get("private_key"):
        raise RuntimeError("Google service-account credentials are missing required fields.")
    return parsed


def _worksheet(spreadsheet, title, rows=1000, cols=18):
    try:
        return spreadsheet.worksheet(title)
    except Exception:
        return spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)


def open_spreadsheet(credentials_json, spreadsheet_id):
    if not credentials_json or not spreadsheet_id:
        raise RuntimeError(
            "Google Sheets is not configured. Add GOOGLE_SERVICE_ACCOUNT_JSON "
            "and GOOGLE_SHEET_ID repository secrets."
        )
    import gspread

    client = gspread.service_account_from_dict(_credentials(credentials_json))
    return client.open_by_key(spreadsheet_id)


def fetch_manual_fields(credentials_json, spreadsheet_id):
    spreadsheet = open_spreadsheet(credentials_json, spreadsheet_id)
    worksheet = _worksheet(spreadsheet, "Opportunities")
    values = worksheet.get_all_values()
    if not values:
        return {}
    headers = values[0]
    required = {"ID", "Actioned?", "Notes"}
    if not required.issubset(headers):
        return {}
    positions = {name: headers.index(name) for name in required}
    result = {}
    for row in values[1:]:
        row = row + [""] * (len(headers) - len(row))
        record_id = row[positions["ID"]].strip()
        if record_id:
            result[record_id] = {
                "Actioned?": row[positions["Actioned?"]],
                "Notes": row[positions["Notes"]],
            }
    return result


def sync_records(credentials_json, spreadsheet_id, headers, records):
    spreadsheet = open_spreadsheet(credentials_json, spreadsheet_id)
    worksheet = _worksheet(spreadsheet, "Opportunities", rows=max(len(records) + 100, 1000))
    existing = worksheet.get_all_values()
    manual = {}
    if existing and {"ID", "Actioned?", "Notes"}.issubset(existing[0]):
        positions = {name: existing[0].index(name) for name in ("ID", "Actioned?", "Notes")}
        for row in existing[1:]:
            row = row + [""] * (len(existing[0]) - len(row))
            record_id = row[positions["ID"]].strip()
            if record_id:
                manual[record_id] = {
                    "Actioned?": row[positions["Actioned?"]],
                    "Notes": row[positions["Notes"]],
                }

    merged = []
    for source in records:
        record = dict(source)
        user_values = manual.get(str(record.get("ID", "")), {})
        if user_values.get("Actioned?") not in (None, ""):
            record["Actioned?"] = user_values["Actioned?"]
        if user_values.get("Notes") not in (None, ""):
            record["Notes"] = user_values["Notes"]
        merged.append(record)

    values = [headers] + [[record.get(header, "") for header in headers] for record in merged]
    end_row = max(len(values), 1)
    end_column = _column_name(len(headers))
    worksheet.update(
        range_name=f"A1:{end_column}{end_row}",
        values=values,
        value_input_option="USER_ENTERED",
    )
    if len(existing) > end_row:
        worksheet.batch_clear([f"A{end_row + 1}:{end_column}{len(existing)}"])
    worksheet.freeze(rows=1)
    worksheet.set_basic_filter(f"A1:{end_column}{end_row}")

    dashboard = _worksheet(spreadsheet, "Dashboard", rows=20, cols=4)
    dashboard.update(
        range_name="A1:B8",
        values=[
            ["Zero2Sudo Opportunity Monitor", ""],
            ["Metric", "Value"],
            ["Total opportunities", len(merged)],
            ["Open / reopened", sum(r.get("Status") in {"Open", "Reopened"} for r in merged)],
            ["Not actioned", sum(r.get("Actioned?") == "No" for r in merged)],
            ["Actioned", sum(r.get("Actioned?") == "Yes" for r in merged)],
            ["Internships", sum(r.get("Category") == "Internship" for r in merged)],
            ["Last verified sync", __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()],
        ],
        value_input_option="USER_ENTERED",
    )
    dashboard.freeze(rows=2)

    verified = worksheet.get(f"A2:A{end_row}") if merged else []
    verified_ids = [row[0] for row in verified if row]
    expected_ids = [str(record.get("ID", "")) for record in merged]
    if verified_ids != expected_ids:
        raise RuntimeError("Google Sheets verification failed: IDs differ after sync.")
    return merged
