"""SmartRecruiters board listing: api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100.

One request per board: uses only name/id/releasedDate from the list, no
per-posting follow-up request. `ref` in the list response is the API's own
self-link (api.smartrecruiters.com/.../postings/<id>), confirmed live against
several real boards -- never the public posting page, so it is not used for
url; the public URL is built the same way job_pages._smartrecruiters's
per-posting fetcher addresses a posting.
"""
from __future__ import annotations

from radar.sources.ats import AtsSource, parse_date
from radar.sources.registry import register


class SmartRecruitersSource(AtsSource):
    kind = "smartrecruiters"

    def board_url(self):
        return f"https://api.smartrecruiters.com/v1/companies/{self.company.slug}/postings?limit=100"

    def parse(self, data):
        content = data["content"]
        postings = {}
        for job in content:
            eid = str(job["id"])
            title = job.get("name") or ""
            url = f"https://jobs.smartrecruiters.com/{self.company.slug}/{eid}"
            published_at = parse_date(job.get("releasedDate"))
            postings[eid] = (title, url, "", published_at)
        # ponytail: limit=100 with no pagination -- real boards routinely exceed this
        # (confirmed live: 331-753 postings against a 100-row page on several real
        # companies), so a posting pushed off page 1 can misread as closed, and later
        # drift back onto page 1 and misread as new. `complete=False` below only
        # guards the first case; upgrade: paginate with offset until totalFound is
        # exhausted, so both guesses go away.
        complete = int(data.get("totalFound") or 0) <= len(content)
        return postings, complete


@register("smartrecruiters")
def factory(company, settings):
    return SmartRecruitersSource(company)
