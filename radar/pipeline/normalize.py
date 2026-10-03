"""normalize: canonical URL and canonical company name.

ponytail: reuses radar.legacy.opportunity_monitor's clean_url/display_org and
their ~400-name ORG_ALIASES/KNOWN_ORGS tables as-is instead of copying them
into a new config/orgs.yaml -- that would be a pure data move with no
behavior change and a real risk of the two drifting. Move it if/when
something other than this pipeline needs the list without importing legacy.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from radar.legacy import opportunity_monitor as legacy

# Community lists (T4, e.g. SimplifyJobs) link through Simplify's own tracking
# param; legacy.clean_url only strips utm_*/fbclid/gclid/igshid/mc_*.
_EXTRA_TRACKING_PARAMS = {"ref"}
_GREENHOUSE_HOSTS = ("boards.greenhouse.io", "job-boards.greenhouse.io")
_WORKDAY_LOCALE_RE = re.compile(r"^/[a-z]{2}-[a-z]{2}(?=/)", re.I)
_SMARTRECRUITERS_TITLED_RE = re.compile(r"^(/[^/]+/\d+)-[^/]*$")


def canonical_url(url: str) -> str:
    """One string per posting. Beyond tracking params, ATS links come in several
    shapes per posting -- the board API's vs the apply-page/embed links community
    lists use (Lever matched 0/22 and Ashby 0/16 against SimplifyJobs before
    this, 2026-10-02) -- and a mismatch is a permanent duplicate opportunity."""
    url = legacy.clean_url(url)
    if not url:
        return url
    parsed = urlparse(url)
    host, path = parsed.netloc, parsed.path
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
             if k.lower() not in _EXTRA_TRACKING_PARAMS]
    if host in _GREENHOUSE_HOSTS:
        host = "boards.greenhouse.io"  # job-boards.* 301s to the same page; boards.* keeps pre-rule rows matching
        params = dict(query)
        if path == "/embed/job_app" and params.get("for") and params.get("token"):
            path, query = f"/{params['for']}/jobs/{params['token']}", []
        if re.fullmatch(r"/[^/]+/jobs/\d+", path):  # gh_jid only repeats the id in the path; else it IS the id
            query = [(k, v) for k, v in query if k != "gh_jid"]
    elif host == "jobs.lever.co":
        path = path.removesuffix("/apply")
    elif host == "jobs.ashbyhq.com":
        path = path.removesuffix("/application")
        query = [(k, v) for k, v in query if k not in ("embed", "jr_id")]  # jr_id: a referral tag; it made a Story's link a second row
    elif host.endswith(".myworkdayjobs.com"):
        path = _WORKDAY_LOCALE_RE.sub("", path)
    elif host == "jobs.smartrecruiters.com":
        path = _SMARTRECRUITERS_TITLED_RE.sub(r"\1", path)
    return urlunparse((parsed.scheme, host, path, "", urlencode(query), ""))


def canonical_company(name: str) -> str:
    return legacy.display_org(name) if name else ""
