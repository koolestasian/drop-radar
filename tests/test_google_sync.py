import unittest

import google_sheets_sync as sync


class FakeWorksheet:
    def __init__(self, values=None):
        self.values = values or []
        self.updated = None
        self.cleared = []

    def get_all_values(self):
        return self.values

    def update(self, range_name, values, value_input_option):
        self.updated = values
        self.values = values

    def batch_clear(self, ranges):
        self.cleared.extend(ranges)

    def freeze(self, rows):
        self.frozen = rows

    def set_basic_filter(self, value):
        self.filter = value

    def get(self, value):
        return [[row[0]] for row in self.values[1:]]


class FakeSpreadsheet:
    def __init__(self, opportunities):
        self.sheets = {
            "Opportunities": opportunities,
            "Dashboard": FakeWorksheet(),
        }

    def worksheet(self, title):
        return self.sheets[title]

    def add_worksheet(self, title, rows, cols):
        sheet = FakeWorksheet()
        self.sheets[title] = sheet
        return sheet


class GoogleSyncTests(unittest.TestCase):
    def test_sync_preserves_manual_fields(self):
        headers = ["ID", "Opportunity", "Actioned?", "Notes"]
        existing = FakeWorksheet([
            headers,
            ["one", "Old title", "Yes", "Keep this"],
        ])
        spreadsheet = FakeSpreadsheet(existing)
        original = sync.open_spreadsheet
        sync.open_spreadsheet = lambda *_: spreadsheet
        self.addCleanup(setattr, sync, "open_spreadsheet", original)
        merged = sync.sync_records(
            "{}", "sheet", headers,
            [{"ID": "one", "Opportunity": "New title", "Actioned?": "No", "Notes": ""}],
        )
        self.assertEqual(merged[0]["Actioned?"], "Yes")
        self.assertEqual(merged[0]["Notes"], "Keep this")
        self.assertEqual(existing.updated[1], ["one", "New title", "Yes", "Keep this"])


if __name__ == "__main__":
    unittest.main()
