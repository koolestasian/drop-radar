import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from radar.pipeline import pagefacts
from radar.sources import yc_boards as yc


def response(url, text="", data=None):
    return SimpleNamespace(url=url, status_code=200, text=text, json=lambda: data)


class YcBoardsTests(unittest.TestCase):
    def test_only_exact_ats_hosts_and_safe_slugs(self):
        self.assertEqual(yc.board_from_url("https://job-boards.greenhouse.io/Acme"), ("greenhouse", "Acme"))
        self.assertEqual(yc.board_from_url("https://jobs.ashbyhq.com/Acme/123"), ("ashby", "Acme"))
        for url in ("https://evilgreenhouse.io/acme/jobs/1", "https://jobs.lever.co/acme%2F..",
                    "ftp://jobs.lever.co/acme", "http://127.0.0.1/acme", "https://jobs.ashbyhq.com/../x"):
            self.assertIsNone(yc.board_from_url(url), url)

    def test_follows_careers_link_probes_once_and_skips_watched_empty_and_nonhiring(self):
        home, careers = "https://acme.example", "https://acme.example/careers"
        rows = [{"name": "Acme", "website": home, "isHiring": True},
                {"name": "Acme", "website": home, "isHiring": True},
                {"name": "No", "website": "https://no.example", "isHiring": False}]
        pages = {
            home: response(home, '<a href="/careers">Careers</a>'),
            careers: response(careers, '<a href="https://jobs.ashbyhq.com/Acme">Apply</a>'
                              '<a href="https://jobs.lever.co/watched">Apply</a>'
                              '<a href="https://jobs.lever.co/empty">Apply</a>'),
            "https://api.ashbyhq.com/posting-api/job-board/Acme": response("", data={"jobs": [
                {"id": "1", "title": "Engineer", "jobUrl": "https://jobs.ashbyhq.com/Acme/1"}]}),
            "https://api.lever.co/v0/postings/empty?mode=json": response("", data=[]),
        }
        with patch.object(pagefacts, "_robots_allows", return_value=True), \
                patch.object(pagefacts, "_get", side_effect=lambda url, **kwargs: pages[url]) as fetch:
            found = list(yc.discover(rows, {("lever", "watched")}))
        self.assertEqual(len(found), 1)
        row = found[0]
        self.assertEqual((row["ats"], row["slug"], row["company"], row["postings"]), ("ashby", "Acme", "Acme", 1))
        self.assertTrue(row["verified"])
        self.assertEqual(row["source"], yc.DIRECTORY)
        self.assertTrue(row["checked_at"])
        self.assertEqual(sum(c.args[0].startswith("https://api.ashby") for c in fetch.call_args_list), 1)

    def test_robots_block_and_failed_api_never_queue(self):
        with patch.object(pagefacts, "_robots_allows", return_value=False), patch.object(pagefacts, "_get") as fetch:
            self.assertEqual(yc.page_links("https://blocked.example"), [])
            fetch.assert_not_called()
        rows = [{"name": "Acme", "website": "https://jobs.lever.co/acme", "isHiring": True}]
        with patch.object(pagefacts, "_get", return_value=response("", data={"wrong": "schema"})):
            self.assertEqual(list(yc.discover(rows, set())), [])
        with patch.object(pagefacts, "_get", return_value=None):
            self.assertEqual(list(yc.discover(rows, set())), [])

    def test_queue_survives_bad_directory_and_existing_boards_are_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "queue.jsonl"
            previous = json.dumps({"ats": "ashby", "slug": "Acme"}) + "\n"
            out.write_text(previous)
            with patch.object(pagefacts, "_get", return_value=response("", data={})), self.assertRaises(SystemExit):
                yc.main(["--out", str(out)])
            self.assertEqual(out.read_text(), previous)
            with patch.object(pagefacts, "_get", return_value=response("", data=[])), \
                    patch.object(yc, "load_users", return_value=[]), patch.object(yc, "discover", return_value=[]) as discover:
                yc.main(["--out", str(out)])
            self.assertEqual(discover.call_args.args[1], {("ashby", "acme")})
            self.assertEqual(out.read_text(), previous)

    def test_large_directory_limit_does_not_change_default_page_cap(self):
        pagefacts._last_hit.clear()
        def streamed():
            r = Mock(status_code=200, is_redirect=False)
            r.iter_content.return_value = [b"x" * (pagefacts.MAX_BYTES + 1)]
            return r
        with patch.object(pagefacts, "_public", return_value=True), patch.object(pagefacts.time, "sleep"), \
                patch.object(pagefacts.requests, "get", side_effect=lambda *a, **kw: streamed()):
            default = pagefacts._get("https://example.com")
            larger = pagefacts._get("https://example.com", max_bytes=pagefacts.MAX_BYTES + 10)
        self.assertEqual(len(default._content), pagefacts.MAX_BYTES)
        self.assertEqual(len(larger._content), pagefacts.MAX_BYTES + 1)

    def test_redirect_to_robots_blocked_page_is_not_fetched(self):
        redirect = Mock(status_code=302, is_redirect=True, headers={"location": "https://blocked.example/jobs"})
        with patch.object(pagefacts, "_public", return_value=True), \
                patch.object(pagefacts, "_robots_allows", side_effect=lambda url: "blocked" not in url), \
                patch.object(pagefacts.requests, "get", return_value=redirect) as get:
            self.assertIsNone(pagefacts._get("https://allowed.example", robots=True))
        get.assert_called_once()


if __name__ == "__main__":
    unittest.main()
