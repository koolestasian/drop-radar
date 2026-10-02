#!/usr/bin/env python3
"""Native Instagram scraper: Stories and recent posts, without Apify.

It calls the same JSON endpoints instagram.com's own web app uses, authenticated
with the `sessionid` cookie of a logged-in account (Stories are only served to
logged-in viewers). Compared with the Apify actors it is free, needs one or two
requests per check instead of a queued actor run, and returns fields the actors
flatten or drop: link-sticker and call-to-action URLs, Instagram's own image
text descriptions, and each Story's permalink.

Items come back in the shape `opportunity_monitor.normalize_item` expects, so
they are interchangeable with Apify items; both identify a Story by its media
ID, so switching scrapers does not re-alert anything already tracked.

Errors raise `InstagramError` subclasses so the caller can fall back to Apify:
`InstagramAuthError` for a missing/expired session or a security checkpoint,
`InstagramBlockedError` for rate limiting.
"""
import time
from urllib.parse import unquote

import requests

WEB_APP_ID = "936619743392459"  # instagram.com web client's public app ID
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
BASE = "https://www.instagram.com"


class InstagramError(RuntimeError):
    pass


class InstagramAuthError(InstagramError):
    pass


class InstagramBlockedError(InstagramError):
    pass


class InstagramClient:
    def __init__(self, sessionid="", session=None, timeout=30):
        self.session = session or requests.Session()
        self.timeout = timeout
        self.session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "X-IG-App-ID": WEB_APP_ID,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{BASE}/",
        })
        self.authenticated = bool(sessionid)
        if sessionid:
            sessionid = unquote(sessionid.strip())
            self.session.cookies.set("sessionid", sessionid, domain=".instagram.com")
            user_id = sessionid.split(":", 1)[0]
            if user_id.isdigit():
                self.session.cookies.set("ds_user_id", user_id, domain=".instagram.com")
        self._profiles = {}

    def _get(self, path, params=None):
        try:
            response = self.session.get(
                f"{BASE}{path}", params=params, timeout=self.timeout, allow_redirects=False
            )
        except requests.RequestException as exc:
            raise InstagramError(f"network error: {type(exc).__name__}") from exc
        if response.status_code == 429:
            raise InstagramBlockedError("rate limited by Instagram (HTTP 429)")
        if response.status_code in (301, 302) or "login" in response.headers.get("location", ""):
            raise InstagramAuthError("Instagram redirected to login; the session is missing or expired")
        try:
            data = response.json()
        except ValueError:
            raise InstagramAuthError(
                f"Instagram returned a non-JSON page (HTTP {response.status_code}); "
                "usually a login wall or an expired session"
            ) from None
        message = str(data.get("message") or "") if isinstance(data, dict) else ""
        if "checkpoint" in message or "challenge" in message or data.get("checkpoint_url"):
            raise InstagramAuthError("Instagram requires a security checkpoint; log in on the web to clear it")
        if response.status_code in (401, 403) or message == "login_required":
            raise InstagramAuthError(
                f"Instagram refused the request (HTTP {response.status_code}): {message or 'login required'}"
            )
        if "wait a few minutes" in message.lower():
            raise InstagramBlockedError(f"rate limited by Instagram: {message}")
        if response.status_code >= 400:
            raise InstagramError(f"Instagram returned HTTP {response.status_code}: {message}")
        return data

    def profile(self, username):
        if username not in self._profiles:
            data = self._get("/api/v1/users/web_profile_info/", {"username": username})
            user = (data.get("data") or {}).get("user")
            if not user or not user.get("id"):
                raise InstagramError(f"profile @{username} not found or not public")
            self._profiles[username] = user
        return self._profiles[username]

    def stories(self, username, user_id=None):
        """`user_id` skips the profile lookup: web_profile_info is the endpoint Instagram
        throttles hardest, and an account's id never changes."""
        if not self.authenticated:
            raise InstagramAuthError("Stories need IG_SESSIONID (Instagram only serves them to logged-in viewers)")
        user_id = str(user_id or self.profile(username)["id"])
        data = self._get("/api/v1/feed/reels_media/", {"reel_ids": user_id})
        reel = (data.get("reels") or {}).get(user_id)
        if reel is None:
            reel = next(
                (item for item in data.get("reels_media") or [] if str(item.get("id")) == user_id), None
            )
        items = (reel or {}).get("items") or []
        return [story_item(item, username) for item in items]

    def recent_posts(self, username, lookback_days=3, limit=12):
        user = self.profile(username)
        edges = ((user.get("edge_owner_to_timeline_media") or {}).get("edges")) or []
        cutoff = time.time() - lookback_days * 86400
        posts = []
        for edge in edges[:limit]:
            node = edge.get("node") or {}
            if node.get("pinned_for_users"):
                continue
            if (node.get("taken_at_timestamp") or 0) < cutoff:
                continue
            posts.append(post_item(node))
        return posts


def _best_image(item):
    candidates = ((item.get("image_versions2") or {}).get("candidates")) or []
    candidates = [c for c in candidates if isinstance(c, dict) and c.get("url")]
    if not candidates:
        return ""
    return max(candidates, key=lambda c: (c.get("width") or 0) * (c.get("height") or 0))["url"]


def story_item(item, username):
    pk = str(item.get("pk") or str(item.get("id") or "").split("_")[0])
    links, texts = [], []
    for sticker in item.get("story_link_stickers") or []:
        link = (sticker or {}).get("story_link") or {}
        if link.get("url"):
            links.append(link["url"])
        for key in ("link_title", "display_url"):
            if link.get(key):
                texts.append(str(link[key]))
    for cta in item.get("story_cta") or []:
        for link in (cta or {}).get("links") or []:
            if (link or {}).get("webUri"):
                links.append(link["webUri"])
    caption = (item.get("caption") or {}).get("text") if isinstance(item.get("caption"), dict) else ""
    for value in (caption, item.get("accessibility_caption")):
        if value:
            texts.append(str(value))
    videos = item.get("video_versions") or []
    return {
        "id": pk,
        "pk": pk,
        "taken_at": item.get("taken_at"),
        "url": f"{BASE}/stories/{username}/{pk}/",
        "image_url": _best_image(item),
        "video_url": videos[0].get("url", "") if videos and isinstance(videos[0], dict) else "",
        "text": "\n".join(texts),
        "links": list(dict.fromkeys(links)),
    }


def post_item(node):
    shortcode = node.get("shortcode") or ""
    caption_edges = ((node.get("edge_media_to_caption") or {}).get("edges")) or []
    caption = (caption_edges[0].get("node") or {}).get("text", "") if caption_edges else ""
    extra = node.get("accessibility_caption") or ""
    return {
        "id": str(node.get("id") or ""),
        "shortCode": shortcode,
        "timestamp": node.get("taken_at_timestamp"),
        "caption": "\n".join(x for x in (caption, extra) if x),
        "displayUrl": node.get("display_url") or "",
        "url": f"{BASE}/p/{shortcode}/" if shortcode else "",
    }
