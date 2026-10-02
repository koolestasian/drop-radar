"""Google: there is no public JSON API any more (careers.google.com/api/v3 is 404),
but the results page embeds its 20 rows as JSON in AF_initDataCallback 'ds:1'
(verified live 2026-10-02): row[0] id, row[1] title, row[9] locations, row[12] [epoch, ns].
Watchlist slug is unused; write "google"."""
from __future__ import annotations

import json
import re
from urllib.parse import urlencode

from radar.errors import SourceError
from radar.sources.ats import WindowedSource, parse_date
from radar.sources.registry import register

BASE = "https://www.google.com/about/careers/applications/jobs/results"
_DATA_RE = re.compile(r"AF_initDataCallback\(\{key: 'ds:1'.*?data:(\[.*?\]), sideChannel", re.S)


class GoogleSource(WindowedSource):
    kind = "google"
    queries = ("intern", "early career", "university graduate")

    def board_url(self):
        return BASE

    async def search(self, ctx, query):
        response = await self._send(ctx.get, f"{BASE}?{urlencode({'q': query, 'sort_by': 'date'})}")
        if response.status_code != 200:
            self._json(response)  # raises the right SourceError for the status
        match = _DATA_RE.search(response.text)
        if match is None:
            raise SourceError(f"{self.name}: results page has no ds:1 data block", kind="schema")
        return self._shape(lambda rows: {
            str(r[0]): (r[1] or "", f"{BASE}/{r[0]}", "; ".join(loc[0] for loc in (r[9] or [])),
                        parse_date((r[12] or [None])[0]))
            for r in rows[0] or []
        }, json.loads(match.group(1)))


@register("google")
def factory(company, settings):
    return GoogleSource(company)
