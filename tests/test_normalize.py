import tempfile
import unittest
from pathlib import Path

from radar.models import Item, utcnow
from radar.pipeline.normalize import canonical_url
from radar.store import Store


class AtsLinkShapeTests(unittest.TestCase):
    """A board's own posting URL and a community list's link to the same posting
    must canonicalize alike, or URL dedupe mints a permanent duplicate (and a
    second push hours later). Real pairs, board API vs SimplifyJobs, 2026-10-02."""

    def same(self, board, community):
        self.assertEqual(canonical_url(board), canonical_url(community))

    def test_lever_apply_page(self):
        self.same("https://jobs.lever.co/tri/07910a65-9ab3-4d48-85a8-44cd187afafd",
                  "https://jobs.lever.co/tri/07910a65-9ab3-4d48-85a8-44cd187afafd/apply")

    def test_ashby_embedded_application(self):
        self.same("https://jobs.ashbyhq.com/dandy/52bcfe21-dfa6-4669-8b58-b995c6e97b31",
                  "https://jobs.ashbyhq.com/dandy/52bcfe21-dfa6-4669-8b58-b995c6e97b31/application?embed=true")

    def test_greenhouse_gh_jid_and_old_host(self):
        self.same("https://boards.greenhouse.io/neuralink/jobs/6083322003?gh_jid=6083322003",
                  "https://job-boards.greenhouse.io/neuralink/jobs/6083322003")

    def test_greenhouse_embed_form(self):
        self.same("https://boards.greenhouse.io/acme/jobs/123",
                  "https://boards.greenhouse.io/embed/job_app?for=acme&token=123")

    def test_workday_locale(self):
        self.same("https://bah.wd1.myworkdayjobs.com/BAH_Jobs/job/McLean-VA/Intern_R0221234",
                  "https://bah.wd1.myworkdayjobs.com/en-US/BAH_Jobs/job/McLean-VA/Intern_R0221234")

    def test_smartrecruiters_title_suffix(self):
        self.same("https://jobs.smartrecruiters.com/Visa/744000016293725",
                  "https://jobs.smartrecruiters.com/Visa/744000016293725-software-engineer-intern")

    def test_gh_jid_kept_off_greenhouse(self):
        """On a company's own careers page gh_jid IS the posting's identity."""
        self.assertNotEqual(canonical_url("https://stripe.com/jobs/search?gh_jid=1"),
                            canonical_url("https://stripe.com/jobs/search?gh_jid=2"))


class RecanonicalizeTests(unittest.TestCase):
    def test_rows_stored_under_an_older_rule_match_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp) / "radar.db")
            old = "https://jobs.lever.co/tri/abc/apply"  # stored before the /apply rule existed
            item = Item(source="github_repo.x", external_id="1", url=old, title="SWE Intern", seen_at=utcnow())
            opp_id, _ = store.upsert_item(item)
            self.assertEqual(store.recanonicalize_urls(canonical_url), 1)
            self.assertEqual(store.opportunity_id_for_url(canonical_url(old)), opp_id)
            self.assertEqual(store.recanonicalize_urls(canonical_url), 0)  # idempotent
            store.close()


if __name__ == "__main__":
    unittest.main()
