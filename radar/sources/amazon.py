"""Amazon: www.amazon.jobs/en/search.json, newest first (verified live 2026-10-02).
Watchlist slug is unused; write "amazon"."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlencode

from radar.sources.ats import WindowedSource
from radar.sources.registry import register


def _posted(text):
    """'October  1, 2026' -> UTC midnight; day-granular, so drop latency is an upper bound."""
    try:
        return datetime.strptime(" ".join((text or "").split()), "%B %d, %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class AmazonSource(WindowedSource):
    kind = "amazon"

    def board_url(self):
        return "https://www.amazon.jobs/en/search"

    async def search(self, ctx, query):
        params = urlencode({"base_query": query, "sort": "recent", "result_limit": 100})
        data = await self._get_json(ctx, f"https://www.amazon.jobs/en/search.json?{params}")
        return {} if data is None else self._shape(lambda d: {
            str(j["id_icims"]): ((j.get("title") or "").strip(), "https://www.amazon.jobs" + j["job_path"],
                                 j.get("normalized_location") or "", _posted(j.get("posted_date")))
            for j in d["jobs"]
        }, data)


@register("amazon")
def factory(company, settings):
    return AmazonSource(company)
