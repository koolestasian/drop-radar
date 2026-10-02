"""Apple: jobs.apple.com renders each results page into the HTML as
window.__staticRouterHydrationData = JSON.parse("...") (verified live 2026-10-02).
Search text is ignored server-side, so filter by team instead: watchlist slug is
the `team` value, e.g. "internships-STDNT-INTRN"."""
from __future__ import annotations

import json
import re
from urllib.parse import urlencode

from radar.errors import SourceError
from radar.sources.ats import WindowedSource, parse_date
from radar.sources.registry import register

BASE = "https://jobs.apple.com/en-us"
PAGES = 2  # 20 per page, newest first
_DATA_RE = re.compile(r'window\.__staticRouterHydrationData\s*=\s*JSON\.parse\(("(?:[^"\\]|\\.)*")\);', re.S)


class AppleSource(WindowedSource):
    kind = "apple"
    queries = ("",)  # one team, paged

    def board_url(self):
        return f"{BASE}/search?{urlencode({'team': self.company.slug})}"

    async def search(self, ctx, query):
        postings = {}
        for page in range(1, PAGES + 1):
            url = f"{BASE}/search?{urlencode({'team': self.company.slug, 'sort': 'newest'})}" + (f"&page={page}" if page > 1 else "")
            response = await self._send(ctx.get, url)
            if response.status_code != 200:
                self._json(response)  # raises the matching SourceError
            match = _DATA_RE.search(response.text)
            if match is None:
                raise SourceError(f"{self.name}: results page has no router data", kind="schema")
            rows = self._shape(lambda m: json.loads(json.loads(m))["loaderData"]["search"]["searchResults"], match.group(1))
            for r in rows:
                pid = str(r["positionId"])
                postings[pid] = (r.get("postingTitle") or "", f"{BASE}/details/{pid}/{r.get('transformedPostingTitle') or ''}",
                                 ((r.get("locations") or [{}])[0] or {}).get("name") or "", parse_date(r.get("postDateInGMT")))
        return postings


@register("apple")
def factory(company, settings):
    return AppleSource(company)
