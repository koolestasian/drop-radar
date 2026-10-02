"""SmartRecruiters board listing: api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100.

Paginate the whole board: uses only name/id/releasedDate from the list, no
per-posting follow-up request. `ref` in the list response is the API's own
self-link (api.smartrecruiters.com/.../postings/<id>), confirmed live against
several real boards -- never the public posting page, so it is not used for
url; the public URL is built the same way job_pages._smartrecruiters's
per-posting fetcher addresses a posting.
"""
from __future__ import annotations

from dataclasses import replace

from radar.errors import SourceError
from radar.sources.ats import AtsSource, parse_date
from radar.sources.registry import register


class SmartRecruitersSource(AtsSource):
    kind = "smartrecruiters"
    PAGINATED = "smartrecruiters:paginated-v1"  # source_state.etag is unused for HTTP on this source

    def board_url(self):
        return f"https://api.smartrecruiters.com/v1/companies/{self.company.slug}/postings?limit=100"

    async def fetch(self, ctx):
        upgrading = bool(ctx.cursor) and ctx.etag != self.PAGINATED
        items = await super().fetch(ctx)
        ctx.remember(etag=self.PAGINATED)
        # Existing deployments only knew page one. First full scan silently adds
        # the expanded backlog instead of claiming old page-two jobs are fresh drops.
        return [replace(i, raw={**i.raw, "seed": True}) if upgrading and not i.raw.get("closed") else i
                for i in items]

    async def fetch_postings(self, ctx):
        # A first-page 304 says nothing about later pages. Fetch each page through
        # the host limiter and commit the baseline only after the entire scan succeeds.
        postings, offset, total = {}, 0, None
        while True:
            url = self.board_url() + (f"&offset={offset}" if offset else "")
            data = await self._request_json(ctx.get, url)
            try:
                page_total = int(data["totalFound"])
                content = data["content"]
                page, _ = self.parse(data)
                if not isinstance(content, list) or not 0 <= page_total <= 100_000:
                    raise ValueError("invalid listing size")
            except (KeyError, TypeError, AttributeError, IndexError, ValueError) as exc:
                raise SourceError(f"{self.name}: unexpected response shape: {exc}", kind="schema") from exc
            if total is None:
                total = page_total
            if (page_total != total or len(page) != len(content) or postings.keys() & page.keys()
                    or offset + len(content) > total or (not content and offset < total)):
                raise SourceError(f"{self.name}: inconsistent pagination; retry the whole board", kind="transient")
            postings.update(page)
            offset += len(content)
            if offset >= total:
                return postings, True

    def parse(self, data):
        content = data["content"]
        postings = {}
        for job in content:
            eid = str(job["id"])
            title = job.get("name") or ""
            url = f"https://jobs.smartrecruiters.com/{self.company.slug}/{eid}"
            published_at = parse_date(job.get("releasedDate"))
            postings[eid] = (title, url, _location(job.get("location")), published_at)
        complete = int(data.get("totalFound") or 0) <= len(content)
        return postings, complete


def _location(loc) -> str:
    """"Nürnberg, BY, Germany" from fullLocation (or city/region/country), blanks dropped."""
    loc = loc if isinstance(loc, dict) else {}
    full = loc.get("fullLocation") or ", ".join(str(loc.get(k) or "") for k in ("city", "region", "country"))
    text = ", ".join(p.strip() for p in str(full).split(",") if p.strip())
    return f"{text} (Remote)" if loc.get("remote") and text else ("Remote" if loc.get("remote") else text)


@register("smartrecruiters")
def factory(company, settings):
    return SmartRecruitersSource(company)
