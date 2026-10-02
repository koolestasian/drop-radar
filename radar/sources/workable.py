"""Workable board listing: POST apply.workable.com/api/v3/accounts/{slug}/jobs, 10 per
page with a `nextPage` token (verified live 2026-10-02). Whole board, so closed
detection stays on unless the page cap cuts it short."""
from __future__ import annotations

from radar.errors import SourceError
from radar.sources.ats import AtsSource, parse_date
from radar.sources.registry import register

MAX_PAGES = 10


def _location(job):
    loc = job.get("location") or {}
    return ", ".join(x for x in (loc.get("city"), loc.get("region"), loc.get("country")) if x)


class WorkableSource(AtsSource):
    kind = "workable"

    def board_url(self):
        return f"https://apply.workable.com/{self.company.slug}/"

    async def fetch_postings(self, ctx):
        api = f"https://apply.workable.com/api/v3/accounts/{self.company.slug}/jobs"
        postings, token = {}, None
        for _ in range(MAX_PAGES):
            data = await self._request_json(ctx.post, api, json={"query": "", **({"token": token} if token else {})})
            for job in self._rows(data):
                postings[job["shortcode"]] = (job.get("title") or "", f"{self.board_url()}j/{job['shortcode']}/",
                                              _location(job), parse_date(job.get("published")))
            token = data.get("nextPage")
            if not token:
                return postings, True
        return postings, False

    def _rows(self, data):
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            raise SourceError(f"{self.name}: unexpected response shape", kind="schema")
        return data["results"]


@register("workable")
def factory(company, settings):
    return WorkableSource(company)
