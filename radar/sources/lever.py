"""Lever board listing: api.lever.co/v0/postings/{slug}?mode=json (a JSON array directly)."""
from __future__ import annotations

from radar.sources.ats import AtsSource, parse_date
from radar.sources.registry import register


class LeverSource(AtsSource):
    kind = "lever"

    def board_url(self):
        return f"https://api.lever.co/v0/postings/{self.company.slug}?mode=json"

    def parse(self, data):
        postings = {}
        for job in data:
            eid = str(job["id"])
            title = job.get("text") or ""
            url = job.get("hostedUrl") or ""
            location = (job.get("categories") or {}).get("location") or ""
            published_at = parse_date(job.get("createdAt"))
            postings[eid] = (title, url, location, published_at)
        return postings


@register("lever")
def factory(company, settings):
    return LeverSource(company)
