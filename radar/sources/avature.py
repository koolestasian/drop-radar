"""Avature career sites (Two Sigma, Koch, Delta, ManTech, ...): no JSON API, but a
listing page links each posting as <a href=".../JobDetail/<slug>/<id>">Title</a>
(verified live 2026-10-02 on careers.twosigma.com; robots.txt allows it).

Watchlist slug: the listing page minus "https://", e.g.
"careers.twosigma.com/careers/InternshipsAndEarlyCareers". One page per poll, so
it's a window: closed detection stays off.
"""
from __future__ import annotations

import html
import re

from radar.sources.ats import WindowedSource
from radar.sources.registry import register

_LINK_RE = re.compile(r'<a\b[^>]*href="(https?://[^"]*/JobDetail/[^"]*?/(\d+))/?"[^>]*>\s*([^<]+?)\s*</a>', re.S)


class AvatureSource(WindowedSource):
    kind = "avature"
    queries = ("",)

    def board_url(self):
        return f"https://{self.company.slug}"

    async def search(self, ctx, query):
        response = await self._send(ctx.get, self.board_url())
        if response.status_code != 200:
            self._json(response)  # raises the matching SourceError
        return {eid: (html.unescape(title), html.unescape(url), "", None) for url, eid, title in _LINK_RE.findall(response.text)}


@register("avature")
def factory(company, settings):
    return AvatureSource(company)
