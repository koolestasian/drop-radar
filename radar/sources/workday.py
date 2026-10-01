"""Workday: the public CXS jobs search behind every <tenant>.wdN.myworkdayjobs.com
careers site -- most banks, asset managers and many big-tech employers.

Verified live 2026-10-01 on 14 tenants (NVIDIA, Salesforce, Adobe, Capital One,
Citi, Fidelity, Blackstone, BlackRock, Intel, Mastercard, Wells Fargo, Bank of
America, State Street, PwC): POST {"appliedFacets": {}, "limit": 20, "offset":
N, "searchText": "..."} -> {"total", "jobPostings": [{title, externalPath,
locationsText, postedOn, bulletFields}]}. limit is capped at 20.

Watchlist slug: "<tenant>.wdN/<site>", copied from the careers URL
https://<tenant>.wdN.myworkdayjobs.com/<site>, e.g. "nvidia.wd5/NVIDIAExternalCareerSite".

Boards run to thousands of postings, so a poll never pages through them all.
It takes the newest two pages of an empty search (newest-first on most
tenants) plus one page each of a few early-career searches, then the same
seed-then-diff as every ATS source. Single-word searches are fuzzy ("intern"
returns "International ..." first on Citi), so the searches are phrases.
"""
from __future__ import annotations

import re

from radar.errors import ConfigError, SourceError
from radar.sources.ats import AtsSource
from radar.sources.registry import register

PAGE = 20
NEWEST_PAGES = 2
QUERIES = ("", "summer analyst", "summer associate", "summer intern", "new grad", "university graduate",
           "campus", "analyst program")
_SLUG_RE = re.compile(r"^([A-Za-z0-9_-]+)\.(wd\d+)/([A-Za-z0-9_-]+)$")


class WorkdaySource(AtsSource):
    kind = "workday"

    def __init__(self, company):
        match = _SLUG_RE.match(company.slug or "")
        if match is None:
            raise ConfigError(
                f"workday company {company.name!r}: slug must be 'tenant.wdN/site' "
                f"(from https://<tenant>.wdN.myworkdayjobs.com/<site>), got {company.slug!r}"
            )
        self.tenant, self.host_n, self.site = match.groups()
        super().__init__(company)

    def _base(self):
        return f"https://{self.tenant}.{self.host_n}.myworkdayjobs.com"

    def jobs_url(self):
        return f"{self._base()}/wday/cxs/{self.tenant}/{self.site}/jobs"

    def board_url(self):
        return f"{self._base()}/{self.site}"

    async def fetch_postings(self, ctx):
        # ponytail: never complete (no closed-detection) and the cursor keeps every id
        # it has seen; trim it by age if a long-running board's cursor gets large.
        postings = {}
        for query in QUERIES:
            for page in range(NEWEST_PAGES if query == "" else 1):
                body = {"appliedFacets": {}, "limit": PAGE, "offset": page * PAGE, "searchText": query}
                data = await self._request_json(ctx.post, self.jobs_url(), json=body)
                if not isinstance(data, dict):
                    raise SourceError(f"{self.name}: unexpected response shape", kind="schema")
                rows = data.get("jobPostings") or []
                for row in rows:
                    path, title = row.get("externalPath"), row.get("title")
                    if path and title:
                        # Workday's postedOn is day-granular ("Posted 3 Days Ago"); too coarse
                        # for drop latency, which falls back to first_seen instead.
                        postings[path] = (title, self.board_url() + path, row.get("locationsText") or "", None)
                if len(rows) < PAGE:
                    break
        return postings, False


@register("workday")
def factory(company, settings):
    return WorkdaySource(company)
