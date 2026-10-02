"""Ashby board listing: api.ashbyhq.com/posting-api/job-board/{slug}."""
from __future__ import annotations

from radar.sources.ats import AtsSource, parse_date
from radar.sources.registry import register


class AshbySource(AtsSource):
    kind = "ashby"

    def board_url(self):
        return f"https://api.ashbyhq.com/posting-api/job-board/{self.company.slug}"

    def parse(self, data):
        postings = {}
        for job in data["jobs"]:
            if job.get("isListed") is False:
                continue
            eid = str(job["id"])
            title = job.get("title") or ""
            url = job.get("jobUrl") or ""
            location = job.get("location") or ""
            published_at = parse_date(job.get("publishedAt"))
            postings[eid] = (title, url, location, published_at)
        return postings


@register("ashby")
def factory(company, settings):
    return AshbySource(company)
