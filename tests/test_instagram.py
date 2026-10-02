import time
import unittest

from radar.legacy import instagram_scraper as ig
from radar.legacy import opportunity_monitor as monitor

PK = "3988152627153629542"
USER_ID = "4242"


class Response:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self.payload = payload
        self.headers = headers or {}

    def json(self):
        if self.payload is None:
            raise ValueError("html")
        return self.payload


class Session:
    def __init__(self, routes):
        self.routes = routes
        self.headers = {}
        self.cookies = ig.requests.cookies.RequestsCookieJar()
        self.calls = []

    def get(self, url, params=None, **kwargs):
        self.calls.append((url, params))
        return self.routes[url.replace(ig.BASE, "")]


def profile(posts=()):
    return Response(payload={"data": {"user": {"id": USER_ID, "edge_owner_to_timeline_media": {
        "edges": [{"node": node} for node in posts]}}}})


STORY = {
    "pk": PK,
    "taken_at": 1790000000,
    "image_versions2": {"candidates": [
        {"url": "https://scontent.cdninstagram.com/v/small.jpg", "width": 320, "height": 568},
        {"url": "https://scontent.cdninstagram.com/v/big.jpg", "width": 1080, "height": 1920},
    ]},
    "story_link_stickers": [{"story_link": {
        "url": "https://l.instagram.com/?u=https%3A%2F%2Fjobs.lever.co%2Fpalantir%2Fabc&e=x",
        "link_title": "Apply here",
    }}],
    "accessibility_caption": "May be an image of text that says 'Palantir SWE internship applications are open'",
}


class ScraperTests(unittest.TestCase):
    def client(self, routes, sessionid="4242%3Aabc%3A1"):
        return ig.InstagramClient(sessionid, session=Session(routes))

    def test_stories_are_normalized(self):
        client = self.client({
            "/api/v1/users/web_profile_info/": profile(),
            "/api/v1/feed/reels_media/": Response(payload={"reels": {USER_ID: {"items": [STORY]}}}),
        })
        items = client.stories("zero2sudo")
        self.assertEqual(client.session.cookies.get("ds_user_id"), "4242")
        item = items[0]
        self.assertEqual(item["url"], f"https://www.instagram.com/stories/zero2sudo/{PK}/")
        self.assertEqual(item["image_url"], "https://scontent.cdninstagram.com/v/big.jpg")
        self.assertIn("jobs.lever.co", item["links"][0])
        self.assertIn("Apply here", item["text"])

    def test_known_user_id_skips_the_profile_lookup(self):
        """web_profile_info is Instagram's most throttled endpoint; an id never changes."""
        client = self.client({"/api/v1/feed/reels_media/": Response(payload={"reels": {USER_ID: {"items": [STORY]}}})})
        self.assertEqual(len(client.stories("zero2sudo", user_id=USER_ID)), 1)
        self.assertEqual([url for url, _ in client.session.calls], [ig.BASE + "/api/v1/feed/reels_media/"])


    def test_posts_skip_pinned_and_old(self):
        now = int(time.time())
        client = self.client({"/api/v1/users/web_profile_info/": profile([
            {"id": "1", "shortcode": "Old", "taken_at_timestamp": now - 10 * 86400},
            {"id": "2", "shortcode": "Pin", "taken_at_timestamp": now, "pinned_for_users": [{"id": 1}]},
            {"id": "3", "shortcode": "New", "taken_at_timestamp": now, "display_url": "https://x/y.jpg",
             "edge_media_to_caption": {"edges": [{"node": {"text": "Apply now"}}]}},
        ])}, sessionid="")
        posts = client.recent_posts("zero2sudo", lookback_days=3)
        self.assertEqual([post["shortCode"] for post in posts], ["New"])
        self.assertEqual(posts[0]["url"], "https://www.instagram.com/p/New/")

    def test_errors_are_classified(self):
        cases = [
            (Response(401, {"message": "login_required"}), ig.InstagramAuthError),
            (Response(302, None, {"location": "https://www.instagram.com/accounts/login/"}), ig.InstagramAuthError),
            (Response(400, {"message": "checkpoint_required"}), ig.InstagramAuthError),
            (Response(200, None), ig.InstagramAuthError),
            (Response(429, {}), ig.InstagramBlockedError),
            (Response(400, {"message": "Please wait a few minutes before you try again."}), ig.InstagramBlockedError),
        ]
        for response, error in cases:
            client = self.client({"/api/v1/users/web_profile_info/": response})
            with self.assertRaises(error):
                client.profile("zero2sudo")

    def test_stories_need_a_session(self):
        with self.assertRaises(ig.InstagramAuthError):
            self.client({}, sessionid="").stories("zero2sudo")


class MediaIdTests(unittest.TestCase):
    def test_shortcode_and_cache_key_decoding(self):
        self.assertEqual(monitor.shortcode_to_media_id("B"), "1")
        self.assertEqual(monitor.shortcode_to_media_id("BA"), "64")
        self.assertEqual(
            monitor.media_id_from_url("https://x.cdninstagram.com/a.jpg?ig_cache_key=Mzk4ODE1MjYyNzE1MzYyOTU0Mg%3D%3D.3"),
            PK,
        )
        self.assertEqual(monitor.instagram_media_key(["https://www.instagram.com/p/BA/"]), "64")

    def test_story_id_beats_a_post_linked_in_the_caption(self):
        links = ["https://www.instagram.com/p/BA/", f"https://www.instagram.com/stories/zero2sudo/{PK}/"]
        self.assertEqual(monitor.instagram_media_key(links), PK)


if __name__ == "__main__":
    unittest.main()
