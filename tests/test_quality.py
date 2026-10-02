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


if __name__ == "__main__":
    unittest.main()
