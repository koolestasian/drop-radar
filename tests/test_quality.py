import unittest
from unittest.mock import patch

from radar.legacy import opportunity_monitor as monitor


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status
        self.text = ""
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)

    def json(self):
        return self.payload


class QualityTests(unittest.TestCase):
    def test_url_extraction_keeps_s_and_query(self):
        links = monitor.normalize_links({
            "caption": "Apply at https://example.com/jobs/123?source=instagram now."
        })
        self.assertEqual(
            links,
            ["https://example.com/jobs/123?source=instagram"],
        )

    def test_media_and_instagram_are_not_external(self):
        links = [
            "https://scontent-lax.cdninstagram.com/a.heic?ig_cache_key=abc",
            "https://www.instagram.com/stories/zero2sudo/",
            "https://example.com/apply",
        ]
        self.assertEqual(monitor.external_links(links), ["https://example.com/apply"])

    def test_same_story_different_cdn_region_has_same_id(self):
        first = {
            "image": "https://scontent-lax.cdninstagram.com/a.heic?ig_cache_key=stable123",
            "text": "Applications are open for an internship",
        }
        second = {
            "image": "https://scontent-dfw.cdninstagram.com/a.heic?ig_cache_key=stable123&sig=changed",
            "text": "Applications are open for an internship",
        }
        with patch.object(monitor, "ocr_image", return_value=""):
            first_record = monitor.normalize_item(first, "Story")
            second_record = monitor.normalize_item(second, "Story")
        self.assertEqual(first_record["ID"], second_record["ID"])

    def test_tracking_parameters_do_not_change_external_link(self):
        a = monitor.clean_url("https://example.com/job/1?utm_source=ig&x=1&fbclid=abc")
        b = monitor.clean_url("https://example.com/job/1?x=1")
        self.assertEqual(a, b)

    def test_distinct_jobs_on_same_careers_page_remain_distinct(self):
        base = {
            "Application / Registration Link": "https://example.com/careers",
            "Posted At": "2026-09-17T12:00:00Z",
            "Organization": "Example",
            "Raw Text": "Applications are open",
        }
        engineering = dict(base, Opportunity="Software Engineering Internship")
        product = dict(base, Opportunity="Product Management Internship")
        self.assertNotEqual(
            monitor.record_semantic_key(engineering),
            monitor.record_semantic_key(product),
        )

    def test_non_list_actor_payload_fails(self):
        with patch.object(monitor.requests, "post", return_value=Response({"error": "schema"})):
            with self.assertRaisesRegex(RuntimeError, "unexpected dict"):
                monitor.run_actor("actor/name", {})

    def test_actor_http_error_explains_cause_without_leaking_token(self):
        with patch.object(monitor, "APIFY_TOKEN", "secret-token"), \
                patch.object(monitor.requests, "post", return_value=Response([], status=402)) as post:
            with self.assertRaisesRegex(RuntimeError, "out of credit") as raised:
                monitor.run_actor("actor/name", {})
        self.assertNotIn("secret-token", str(raised.exception))
        self.assertNotIn("token", post.call_args.kwargs["params"])
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer secret-token")

    def test_non_object_actor_item_fails(self):
        with patch.object(monitor.requests, "post", return_value=Response(["bad"])):
            with self.assertRaisesRegex(RuntimeError, "non-object"):
                monitor.run_actor("actor/name", {})

    def test_negative_offer_discussion_is_not_actionable(self):
        text = "I got a Microsoft SWE intern offer and here is my interview process"
        self.assertFalse(monitor.looks_actionable(text, []))

    def test_valid_linked_internship_is_actionable(self):
        text = "Software engineering internship applications are open"
        self.assertTrue(monitor.looks_actionable(text, ["https://example.com/jobs/1"]))

    def test_unlinked_item_requires_strong_action(self):
        self.assertFalse(monitor.looks_actionable("NVIDIA internship releases soon", []))
        self.assertTrue(monitor.looks_actionable("NVIDIA internship applications are open", []))

    def test_priority_does_not_match_ai_inside_fair(self):
        row = {"Opportunity": "Career fair registration", "Category": "Recruiting / Career Event"}
        self.assertEqual(monitor.priority_for(row), "NORMAL")

    def test_priority_does_not_match_generic_scale(self):
        row = {"Opportunity": "Learn at scale workshop", "Category": "Workshop / Info Session"}
        self.assertEqual(monitor.priority_for(row), "NORMAL")

    def test_scale_ai_organization_is_high(self):
        row = {"Organization": "Scale AI", "Opportunity": "Software Engineering Internship"}
        self.assertEqual(monitor.priority_for(row), "HIGH")

    def test_media_fallback_leaves_application_blank(self):
        item = {
            "id": "story-1",
            "text": "Internship applications are open",
            "image": "https://scontent-lax.cdninstagram.com/a.heic?ig_cache_key=abc",
        }
        with patch.object(monitor, "ocr_image", return_value=""):
            record = monitor.normalize_item(item, "Story")
        self.assertEqual(record["Application / Registration Link"], "")

    def test_cleanup_merges_media_duplicates_and_manual_fields(self):
        first = {header: "" for header in monitor.HEADERS}
        first.update({
            "ID": "old-1",
            "First Seen": "2026-01-01",
            "Opportunity": "Example Internship",
            "Category": "Internship",
            "Application / Registration Link":
                "https://scontent-lax.cdninstagram.com/a.heic?ig_cache_key=same",
            "Raw Text": "Internship applications are open",
            "Actioned?": "Yes",
            "Notes": "Applied",
        })
        second = dict(first)
        second.update({
            "ID": "old-2",
            "Application / Registration Link":
                "https://scontent-dfw.cdninstagram.com/a.heic?ig_cache_key=same&sig=2",
            "Actioned?": "No",
            "Notes": "Follow up",
        })
        cleaned, stats = monitor.cleanup_records([first, second])
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(stats["duplicates_removed"], 1)
        self.assertEqual(stats["invalid_links_cleared"], 2)
        self.assertEqual(cleaned[0]["Application / Registration Link"], "")
        self.assertEqual(cleaned[0]["Actioned?"], "Yes")
        self.assertIn("Applied", cleaned[0]["Notes"])
        self.assertIn("Follow up", cleaned[0]["Notes"])

    def test_cleanup_is_idempotent(self):
        record = {header: "" for header in monitor.HEADERS}
        record.update({
            "ID": "legacy-id",
            "First Seen": "2026-01-01",
            "Opportunity": "Example Internship",
            "Category": "Internship",
            "Application / Registration Link":
                "https://example.com/job/1?utm_source=instagram",
            "Raw Text": "Internship applications are open",
            "Actioned?": "No",
        })
        first, _ = monitor.cleanup_records([record])
        second, stats = monitor.cleanup_records(first)
        self.assertEqual(first, second)
        self.assertEqual(stats, {"duplicates_removed": 0, "invalid_links_cleared": 0})


if __name__ == "__main__":
    unittest.main()
