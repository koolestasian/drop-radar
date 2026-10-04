import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from radar.sources import aggregator_boards as ab
from radar.sources import yc_boards as yc


class AggregatorBoardsTests(unittest.TestCase):
    def test_slugs_cannot_inject_hosts_paths_or_queries_and_duplicates_are_skipped(self):
        slugs = ["Acme", "acme", "watched", "../private", "x?redirect=http://127.0.0.1",
                 "x%2F..", "https://evil.example", "@evil.example", "", "x" * 101, None]
        rows = list(ab.candidates("ashby", slugs, {("ashby", "watched")}))
        self.assertEqual(rows, [{"name": "", "website": "https://jobs.ashbyhq.com/Acme", "isHiring": True}])
        for ats in ab.BOARDS:
            row = next(ab.candidates(ats, ["Acme"], set()))
            self.assertEqual(yc.board_from_url(row["website"]), (ats, "Acme"))

    def test_uses_guarded_real_parser_and_records_pinned_attribution_without_inventing_names(self):
        source = ab.BASE + "/ashby_companies.json"
        def fetch(url, **kwargs):
            if url == source:
                self.assertTrue(kwargs["robots"])
                data = ["acme", "empty", "broken"]
            elif url.endswith("/acme"):
                data = {"jobs": [{"id": "1", "title": "Intern", "jobUrl": "https://jobs.ashbyhq.com/acme/1"}]}
            elif url.endswith("/empty"):
                data = {"jobs": []}
            else:
                data = {"wrong": "schema"}
            return SimpleNamespace(status_code=200, json=lambda: data)
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "queue.jsonl"
            with patch.object(ab.pagefacts, "_get", side_effect=fetch), patch.object(ab, "load_users", return_value=[]):
                ab.main(["--out", str(out)])
                first = out.read_text()
                ab.main(["--out", str(out)])
            self.assertEqual(out.read_text(), first)
            row = json.loads(first)
        self.assertEqual((row["slug"], row["postings"], row["company"]), ("acme", 1, ""))
        self.assertTrue(row["verified"])
        self.assertFalse(row["company_verified"])
        self.assertEqual(row["source"], source)
        self.assertEqual(row["dataset_commit"], ab.COMMIT)
        self.assertEqual(row["license"], ab.LICENSE)
        self.assertEqual(row["attribution"], ab.ATTRIBUTION)
        self.assertTrue(row["checked_at"])

    def test_failed_or_malformed_dataset_preserves_review_file(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "queue.jsonl"
            out.write_text("previous results\n")
            for response in (None, SimpleNamespace(status_code=403),
                             SimpleNamespace(status_code=200, json=lambda: {}),
                             SimpleNamespace(status_code=200, json=lambda: [None])):
                with self.subTest(response=response), patch.object(ab.pagefacts, "_get", return_value=response), \
                        self.assertRaises(SystemExit):
                    ab.main(["--out", str(out)])
                self.assertEqual(out.read_text(), "previous results\n")

    def test_offsets_do_not_move_when_previous_batch_is_queued(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "queue.jsonl"
            watched = Path(directory) / "watched.json"
            watched.write_text(json.dumps([["ashby", "watched"]]))
            out.write_text(json.dumps({"ats": "ashby", "slug": "one"}) + "\n")
            response = SimpleNamespace(status_code=200, json=lambda: ["one", "watched", "three"])
            with patch.object(ab.pagefacts, "_get", return_value=response), patch.object(ab, "load_users", return_value=[]), \
                    patch.object(ab, "discover", return_value=[]) as discover:
                ab.main(["--offset", "1", "--limit", "2", "--out", str(out), "--watched", str(watched)])
            self.assertEqual([r["website"] for r in discover.call_args.args[0]], ["https://jobs.ashbyhq.com/three"])


if __name__ == "__main__":
    unittest.main()
