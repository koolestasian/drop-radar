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

Searches rank by relevance, so when a posting above closes, an older one moves
up into view and looks new. A posting the board itself dates more than
MAX_AGE_DAYS old joins the baseline without alerting. Identity is the req id
(bulletFields[0]), not externalPath, which embeds the title and changes on an edit.
"""
from __future__ import annotations

import re
from datetime import timedelta

from radar.errors import ConfigError, SourceError
from radar.sources.ats import AtsSource
from radar.sources.registry import register

PAGE = 20
MAX_AGE_DAYS = 7
NEWEST_PAGES = 2
QUERIES = ("", "summer analyst", "summer associate", "summer intern", "new grad", "university graduate",
           "campus", "analyst program")
_SLUG_RE = re.compile(r"^([A-Za-z0-9_-]+)\.(wd\d+)/([A-Za-z0-9_-]+)$")


class WorkdaySource(AtsSource):
    kind = "workday"

    def __init__(self, company):
        self._stale = set()
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

    async def fetch(self, ctx):
        items = await super().fetch(ctx)  # the cursor keeps stale postings too, so they never alert later
        return [i for i in items if i.raw.get("closed") or i.external_id not in self._stale]

    async def fetch_postings(self, ctx):
        """Complete (closed-detection on) only when the newest pages held the whole board.
        ponytail: on a big board the cursor keeps every id it has seen; trim it by age
        if a long-running board's cursor ever gets large."""
        postings, self._stale = {}, set()
        today = ctx.now().replace(hour=0, minute=0, second=0, microsecond=0)
        total, newest_seen = None, 0
        for query in QUERIES:
            for page in range(NEWEST_PAGES if query == "" else 1):
                body = {"appliedFacets": {}, "limit": PAGE, "offset": page * PAGE, "searchText": query}
                data = await self._request_json(ctx.post, self.jobs_url(), json=body)
                if not isinstance(data, dict):
                    raise SourceError(f"{self.name}: unexpected response shape", kind="schema")
                rows = data.get("jobPostings") or []
                if query == "":
                    total = data.get("total") if total is None else total
                    newest_seen += len(rows)
                for row in rows:
                    path, title = row.get("externalPath"), row.get("title")
                    if not (path and title):
                        continue
                    req = (row.get("bulletFields") or [None])[0]
                    eid = str(req) if req else path
                    age = _age_days(row.get("postedOn"))
                    if age is not None and age > MAX_AGE_DAYS:
                        self._stale.add(eid)
                    # Day-granular: drop latency for Workday is an upper bound, not exact.
                    published = today - timedelta(days=age) if age is not None and age <= 30 else None
                    postings[eid] = (title, self.board_url() + path, row.get("locationsText") or "", published)
                if len(rows) < PAGE:
                    break
        return postings, isinstance(total, int) and newest_seen >= total


def _age_days(posted_on):
    """'Posted Today' 0, 'Posted Yesterday' 1, 'Posted 3 Days Ago' 3, 'Posted 30+ Days Ago' 31;
    None when the tenant sends no date (Blackstone's campus board)."""
    text = (posted_on or "").lower()
    if "today" in text:
        return 0
    if "yesterday" in text:
        return 1
    match = re.search(r"(\d+)(\+?)\s*day", text)
    return int(match.group(1)) + (1 if match.group(2) else 0) if match else None


@register("workday")
def factory(company, settings):
    return WorkdaySource(company)
