"""Greenhouse board listing: boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true."""
from __future__ import annotations

from radar.sources.ats import AtsSource, parse_date
from radar.sources.registry import register


class GreenhouseSource(AtsSource):
    kind = "greenhouse"

    def board_url(self):
        return f"https://boards-api.greenhouse.io/v1/boards/{self.company.slug}/jobs?content=true"

    def parse(self, data):
        postings = {}
        for job in data["jobs"]:
            eid = str(job["id"])
            title = job.get("title") or ""
            url = job.get("absolute_url") or ""
            location = (job.get("location") or {}).get("name") or ""
            published_at = parse_date(job.get("first_published") or job.get("updated_at"))
            postings[eid] = (title, url, location, published_at)
        return postings


@register("greenhouse")
def factory(company, settings):
    return GreenhouseSource(company)
