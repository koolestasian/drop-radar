import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from radar.config import Repo
from radar.errors import SourceError
from radar.sources import github_repo, registry

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "community"


class FakeResponse:
    def __init__(self, status_code=200, text=None, headers=None):
        self.status_code = status_code
        self._text = text
        self.headers = headers or {}

    @property
    def text(self):
        if self._text is None:
            raise AssertionError("response body should not be read when there is nothing to parse")
        return self._text


class FakeCtx:
    """Minimal stand-in for radar.scheduler.FetchContext: only what a Source touches."""

    def __init__(self, responses, etag=None, cursor=None, now=None):
        self.responses = list(responses)
        self.etag, self.cursor = etag, cursor
        self.pending = {}
        self.calls = []
        self._now = now or datetime(2026, 9, 30, tzinfo=timezone.utc)

    def now(self):
        return self._now

    def remember(self, etag=None, cursor=None):
        if etag is not None:
            self.pending["etag"] = etag
        if cursor is not None:
            self.pending["cursor"] = cursor

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def make_table(rows, header=True):
    """rows: list of (company, role, location, url, age). company == '↳'
    (the real "same as above" marker) to exercise continuation rows."""
    body = "".join(
        f'<tr><td><strong><a href="{url}">{company}</a></strong></td><td>{role}</td>'
        f'<td>{location}</td><td><div align="center"><a href="{url}">Apply</a></div></td>'
        f"<td>{age}</td></tr>"
        for company, role, location, url, age in rows
    )
    head = (
        "<thead><tr><th>Company</th><th>Role</th><th>Location</th>"
        "<th>Application</th><th>Age</th></tr></thead>" if header else ""
    )
    return f"<table>{head}<tbody>{body}</tbody></table>"


def contents_response(text, etag='"abc"'):
    return FakeResponse(200, text=text, headers={"ETag": etag})


ROWS_3 = [
    ("Stripe", "SWE Intern", "SF", "https://stripe.com/jobs/1", "5d"),
    ("Dandy", "SWE Intern", "NYC", "https://dandy.com/jobs/2", "2d"),
    ("Waymo", "SWE Intern", "Mountain View", "https://waymo.com/jobs/3", "0d"),
]
ROWS_4 = ROWS_3 + [("Ramp", "New Grad SWE", "NYC", "https://ramp.com/jobs/4", "1d")]


def repo(path="README.md"):
    return Repo(name="SimplifyJobs/Summer2027-Internships", path=path)


async def seed_then_refetch(source, first_text, second_text):
    """Returns the Items from fetching second_text right after seeding on first_text."""
    seed_ctx = FakeCtx([contents_response(first_text)])
    await source.fetch(seed_ctx)
    next_ctx = FakeCtx([contents_response(second_text)], etag=seed_ctx.pending["etag"], cursor="[]")
    return await source.fetch(next_ctx)


class GithubRepoSourceTests(unittest.IsolatedAsyncioTestCase):
    def test_registered_and_named(self):
        source = registry.FACTORIES["github_repo"](repo(), settings=None)
        self.assertEqual(source.name, "github_repo.SimplifyJobs/Summer2027-Internships")
        self.assertEqual(source.interval_s, 60.0)

    async def test_first_poll_seeds_silently(self):
        source = github_repo.GithubRepoSource(repo())
        ctx = FakeCtx([contents_response(make_table(ROWS_3))])
        items = await source.fetch(ctx)
        self.assertEqual(items, [])  # backlog is not flooded as Items on first sight
        self.assertEqual(len(json.loads(ctx.pending["cursor"])), 3)
        self.assertEqual(ctx.pending["etag"], '"abc"')

    async def test_new_row_after_seeding_is_the_only_item(self):
        source = github_repo.GithubRepoSource(repo())
        seed_ctx = FakeCtx([contents_response(make_table(ROWS_3))])
        await source.fetch(seed_ctx)

        next_ctx = FakeCtx(
            [contents_response(make_table(ROWS_4))],
            etag=seed_ctx.pending["etag"], cursor=seed_ctx.pending["cursor"],
        )
        items = await source.fetch(next_ctx)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].company, "Ramp")
        self.assertEqual(items[0].title, "New Grad SWE")
        self.assertEqual(items[0].url, "https://ramp.com/jobs/4")
        self.assertEqual(items[0].source, "github_repo.SimplifyJobs/Summer2027-Internships")

    async def test_304_emits_nothing_and_never_parses_body(self):
        source = github_repo.GithubRepoSource(repo())
        ctx = FakeCtx([FakeResponse(304)], etag='"abc"', cursor=json.dumps(["x"]))
        items = await source.fetch(ctx)
        self.assertEqual(items, [])
        self.assertNotIn("cursor", ctx.pending)  # unchanged: no diff work attempted
        url, kwargs = ctx.calls[0]
        self.assertIn("api.github.com/repos/SimplifyJobs/Summer2027-Internships/contents/README.md", url)
        self.assertEqual(kwargs["headers"]["If-None-Match"], '"abc"')
        self.assertEqual(kwargs["headers"]["Accept"], "application/vnd.github.raw+json")

    async def test_published_at_parsed_when_present_and_none_when_absent(self):
        source = github_repo.GithubRepoSource(repo())
        rows = [
            ("Stripe", "SWE Intern", "SF", "https://stripe.com/jobs/1", "5d"),
            ("Dandy", "SWE Intern", "NYC", "https://dandy.com/jobs/2", ""),
        ]
        items = await seed_then_refetch(source, make_table(rows), make_table(rows))
        by_company = {item.company: item for item in items}
        now = datetime(2026, 9, 30, tzinfo=timezone.utc)
        self.assertEqual(by_company["Stripe"].published_at, now - timedelta(days=5))
        self.assertIsNone(by_company["Dandy"].published_at)

    async def test_json_listing_is_parsed_best_effort(self):
        source = github_repo.GithubRepoSource(repo(path="listing.json"))
        payload = json.dumps([
            {"company": "Stripe", "title": "SWE Intern", "url": "https://stripe.com/jobs/1",
             "date_posted": "2026-09-15"},
            {"company": "Dandy", "role": "SWE Intern", "link": "https://dandy.com/jobs/2"},
        ])
        items = await seed_then_refetch(source, payload, payload)
        by_company = {item.company: item for item in items}
        self.assertEqual(by_company["Stripe"].published_at, datetime(2026, 9, 15, tzinfo=timezone.utc))
        self.assertIsNone(by_company["Dandy"].published_at)

    async def test_emoji_prefix_is_stripped_from_company_name(self):
        source = github_repo.GithubRepoSource(repo())
        rows = [("\U0001f525 Waymo", "SWE Intern", "SF", "https://waymo.com/jobs/1", "0d")]
        items = await seed_then_refetch(source, make_table(rows), make_table(rows))
        self.assertEqual(items[0].company, "Waymo")

    async def test_continuation_row_inherits_company_above(self):
        source = github_repo.GithubRepoSource(repo())
        rows = [
            ("Northrop Grumman", "SWE Intern", "Rolling Meadows, IL", "https://ngc.example/1", "1d"),
            ("↳", "Software Engineer Co-op", "Remote", "https://ngc.example/2", "1d"),
        ]
        items = await seed_then_refetch(source, make_table(rows), make_table(rows))
        self.assertEqual({i.company for i in items}, {"Northrop Grumman"})

    async def test_header_rows_in_every_table_are_skipped(self):
        source = github_repo.GithubRepoSource(repo())
        text = make_table(ROWS_3[:2]) + make_table(ROWS_3[2:])  # two category tables, each with its own <thead>
        items = await seed_then_refetch(source, text, text)
        self.assertEqual(len(items), 3)
        self.assertNotIn("Company", {i.company for i in items})  # a header row was never mistaken for data

    async def test_no_rows_parsed_is_a_schema_error(self):
        source = github_repo.GithubRepoSource(repo())
        ctx = FakeCtx([contents_response("just some plain prose, not a table or JSON array")])
        with self.assertRaises(SourceError) as cm:
            await source.fetch(ctx)
        self.assertEqual(cm.exception.kind, "schema")
        self.assertEqual(ctx.pending, {})  # nothing remembered: next poll retries, doesn't flood

    async def test_invalid_json_listing_is_a_schema_error(self):
        source = github_repo.GithubRepoSource(repo(path="listing.json"))
        ctx = FakeCtx([contents_response("[not valid json")])
        with self.assertRaises(SourceError) as cm:
            await source.fetch(ctx)
        self.assertEqual(cm.exception.kind, "schema")

    async def test_404_is_a_schema_error(self):
        source = github_repo.GithubRepoSource(repo())
        ctx = FakeCtx([FakeResponse(404)])
        with self.assertRaises(SourceError) as cm:
            await source.fetch(ctx)
        self.assertEqual(cm.exception.kind, "schema")

    async def test_5xx_is_transient(self):
        source = github_repo.GithubRepoSource(repo())
        ctx = FakeCtx([FakeResponse(503)])
        with self.assertRaises(SourceError) as cm:
            await source.fetch(ctx)
        self.assertEqual(cm.exception.kind, "transient")

    async def test_rate_limited_is_blocked(self):
        source = github_repo.GithubRepoSource(repo())
        ctx = FakeCtx([FakeResponse(403)])
        with self.assertRaises(SourceError) as cm:
            await source.fetch(ctx)
        self.assertEqual(cm.exception.kind, "blocked")

    async def test_unrecognizable_row_is_skipped_but_siblings_are_kept(self):
        source = github_repo.GithubRepoSource(repo())
        rows = ROWS_3 + [("", "", "somewhere with no company or role", "", "2d")]
        text = make_table(rows)
        items = await seed_then_refetch(source, text, text)
        self.assertEqual(len(items), 3)  # the 4th row has neither company nor role: skipped, not a crash

    async def test_sends_authorization_header_when_token_set(self):
        source = github_repo.GithubRepoSource(repo())
        ctx = FakeCtx([contents_response(make_table(ROWS_3))])
        old = github_repo.GITHUB_TOKEN
        github_repo.GITHUB_TOKEN = "tok123"
        try:
            await source.fetch(ctx)
        finally:
            github_repo.GITHUB_TOKEN = old
        self.assertEqual(ctx.calls[0][1]["headers"]["Authorization"], "Bearer tok123")

    async def test_closed_row_with_no_apply_link_is_skipped(self):
        # Live data: SimplifyJobs/New-Grad-Positions keeps closed roles inline with a
        # bare "🔒" Application cell (no <a> at all) instead of removing them.
        source = github_repo.GithubRepoSource(repo())
        rows = ROWS_3 + [("RTX", "Closed Role", "UT", "", "6d")]
        text = make_table(rows).replace(
            '<td><div align="center"><a href="">Apply</a></div></td><td>6d</td>', "<td>\U0001f512</td><td>6d</td>",
        )
        self.assertIn("\U0001f512", text)  # sanity: the replace actually matched
        items = await seed_then_refetch(source, text, text)
        self.assertEqual({i.company for i in items}, {"Stripe", "Dandy", "Waymo"})

    async def test_401_is_an_auth_error(self):
        source = github_repo.GithubRepoSource(repo())
        ctx = FakeCtx([FakeResponse(401)])
        with self.assertRaises(SourceError) as cm:
            await source.fetch(ctx)
        self.assertEqual(cm.exception.kind, "auth")

    async def test_year_qualified_text_date_is_parsed(self):
        self.assertEqual(
            github_repo._parse_published_at("Sep 15 2026", datetime(2026, 9, 30, tzinfo=timezone.utc)),
            datetime(2026, 9, 15, tzinfo=timezone.utc),
        )

    async def test_real_readme_fixture(self):
        """Exercises the module against a trimmed excerpt reproducing the real
        SimplifyJobs README structure (see tests/fixtures/community/README note
        in the fixture file itself), not synthetic rows built by make_table."""
        text = (FIXTURE_DIR / "simplify_readme.html").read_text(encoding="utf-8")
        source = github_repo.GithubRepoSource(repo())
        items = await seed_then_refetch(source, text, text)
        by_company = {item.company: item for item in items}

        self.assertEqual(set(by_company), {"Waymo", "MetLife", "Northrop Grumman", "Stripe"})
        self.assertNotIn("RTX", by_company)  # closed (🔒, no link): not surfaced as a drop

        self.assertEqual(by_company["Waymo"].company, "Waymo")  # leading "🔥 " stripped
        self.assertEqual(by_company["Waymo"].url, "https://careers.withwaymo.com/jobs?gh_jid=8238525")
        self.assertNotIn("simplify.jobs/p", by_company["Waymo"].url)  # ATS link wins over the Simplify co-link

        self.assertEqual(by_company["MetLife"].location, "4 locations | Tampa, FL | Hanover, NJ | Cary, NC | NYC")

        # the "↳" row inherited "Northrop Grumman" (the row directly above it),
        # not "MetLife" (two rows above) or "RTX" (the row after, itself skipped)
        ngc_urls = {i.url for i in items if i.company == "Northrop Grumman"}
        self.assertEqual(ngc_urls, {
            "https://ngc.wd1.myworkdayjobs.com/job/1", "https://ngc.wd1.myworkdayjobs.com/job/2",
        })

        self.assertEqual(by_company["Stripe"].company, "Stripe")  # table 2's own <thead> wasn't parsed as a row


if __name__ == "__main__":
    unittest.main()
