"""A careers sitemap as the listing: for sites that refuse automated page views but
publish their job pages in a sitemap for crawlers (Citadel and Citadel Securities:
pages 403, robots.txt points at the sitemap; verified 2026-10-02). Each <loc> is a
posting; its title is the last path segment, de-slugged. The sitemap is the whole
set of open postings, so closed detection stays on.

Watchlist slug: the sitemap URL minus "https://", e.g. "www.citadel.com/career-sitemap.xml".
"""
from __future__ import annotations

import html
import re

from radar.sources.ats import AtsSource, parse_date
from radar.sources.registry import register

_URL_RE = re.compile(r"<url>\s*<loc>([^<]+)</loc>(?:\s*<lastmod>([^<]+)</lastmod>)?", re.S)


def _title(url):
    return url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title()


class SitemapSource(AtsSource):
    kind = "sitemap"

    def board_url(self):
        return f"https://{self.company.slug}"

    async def fetch_postings(self, ctx):
        response = await self._send(ctx.get, self.board_url())
        if response.status_code != 200:
            self._json(response)  # raises the matching SourceError
        postings = {}
        for loc, lastmod in _URL_RE.findall(response.text):
            url = html.unescape(loc.strip())
            postings[url] = (_title(url), url, "", parse_date(lastmod))
        return postings, True


@register("sitemap")
def factory(company, settings):
    return SitemapSource(company)
