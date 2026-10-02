"""Eightfold career sites: the public PCSX search behind Microsoft's
apply.careers.microsoft.com and <company>.eightfold.ai (verified live 2026-10-02;
the older /api/apply/v2 endpoint answers 403 "Not authorized for PCSX").

Watchlist slug: "<host>/<domain>", e.g. "apply.careers.microsoft.com/microsoft.com".
"""
from __future__ import annotations

from urllib.parse import urlencode

from radar.errors import ConfigError
from radar.sources.ats import WindowedSource, parse_date
from radar.sources.registry import register

PAGES = 2  # 10 positions per page


class EightfoldSource(WindowedSource):
    kind = "eightfold"

    def __init__(self, company):
        self.host, _, self.domain = (company.slug or "").partition("/")
        if not (self.host and "." in self.domain):
            raise ConfigError(f"eightfold company {company.name!r}: slug must be 'host/domain', got {company.slug!r}")
        super().__init__(company)

    def board_url(self):
        return f"https://{self.host}/careers"

    async def search(self, ctx, query):
        postings = {}
        for page in range(PAGES):
            params = urlencode({"domain": self.domain, "query": query, "sort_by": "timestamp", "start": page * 10})
            data = await self._get_json(ctx, f"https://{self.host}/api/pcsx/search?{params}")
            rows = [] if data is None else self._shape(lambda d: d["data"]["positions"], data)
            for p in rows:
                postings[str(p["id"])] = (p.get("name") or "", f"https://{self.host}{p['positionUrl']}",
                                          (p.get("locations") or [""])[0], parse_date(p.get("postedTs")))
            if len(rows) < 10:
                break
        return postings


@register("eightfold")
def factory(company, settings):
    return EightfoldSource(company)
