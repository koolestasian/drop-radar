"""Manual/live tooling for the ATS sources -- not run by the test suite.

- `python -m radar.sources.discover --check`: one live request per board on any
  user's watchlist (config/users.yaml), prints whether it returned a parseable
  200 and how many postings. A 200 with zero postings is flagged: SmartRecruiters
  answers 200 + an empty list for a slug that doesn't exist.
- `mine_tracker_slugs()`: (ats, slug) pairs recovered from the existing
  tracker's application links. Imports the workbook reader lazily so this
  module stays side-effect-free when the registry auto-imports it.
"""
from __future__ import annotations

import re
import sys
from urllib.parse import parse_qsl, urlparse

from radar.sources.ashby import AshbySource
from radar.sources.greenhouse import GreenhouseSource
from radar.sources.lever import LeverSource
from radar.sources.smartrecruiters import SmartRecruitersSource
from radar.sources.workday import WorkdaySource

_BOARD_SOURCE = {
    "greenhouse": GreenhouseSource,
    "lever": LeverSource,
    "ashby": AshbySource,
    "smartrecruiters": SmartRecruitersSource,
}


def _slug_from_url(url):
    """(ats, slug) for a recognized ATS application link, else None.

    Mirrors the host/path parsing radar.legacy.job_pages.fetch_job_facts uses
    per posting, including Greenhouse's embedded-board form
    (boards.greenhouse.io/embed/job_app?for=<slug>&token=<id>).
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    parts = [p for p in parsed.path.split("/") if p]
    if host.endswith("greenhouse.io"):
        if parts[:2] == ["embed", "job_app"]:
            slug = dict(parse_qsl(parsed.query)).get("for")
            return ("greenhouse", slug) if slug else None
        if len(parts) >= 2 and parts[1] == "jobs":
            return ("greenhouse", parts[0])
        return None  # e.g. app3.greenhouse.io/e/<token>: a session link, no slug in the path
    if host == "jobs.lever.co":
        return ("lever", parts[0]) if parts else None
    if host == "jobs.ashbyhq.com":
        return ("ashby", parts[0]) if parts else None
    if host == "jobs.smartrecruiters.com":
        return ("smartrecruiters", parts[0]) if parts else None
    if host.endswith(".myworkdayjobs.com"):
        # https://<tenant>.wdN.myworkdayjobs.com/[en-US/]<site>/job/... -> "tenant.wdN/site"
        if parts and re.fullmatch(r"[a-z]{2}-[a-z]{2}", parts[0], re.I):
            parts = parts[1:]
        site = parts[0] if parts else ""
        if not site or any(w in site.lower() for w in ("private", "confidential", "privileged")):
            return None  # an unlisted site: links work, but there's no board to poll
        return ("workday", f"{host.removesuffix('.myworkdayjobs.com')}/{site}")
    return None


def mine_tracker_slugs(records=None):
    """(ats, slug) pairs found in the tracker's Application/Registration Link column."""
    if records is None:
        from radar.legacy.opportunity_monitor import workbook_records
        records = workbook_records()
    found = set()
    for record in records:
        pair = _slug_from_url(str(record.get("Application / Registration Link") or ""))
        if pair:
            found.add(pair)
    return sorted(found)


async def _check_workday(client, company):
    source = WorkdaySource(company)
    body = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}
    try:
        response = await client.post(source.jobs_url(), json=body)
    except Exception as exc:
        return company.ats, company.slug, f"error: {exc}"
    if response.status_code != 200:
        return company.ats, company.slug, f"HTTP {response.status_code}"
    total = (response.json() or {}).get("total") or 0
    return company.ats, company.slug, f"200 OK ({total} postings)" if total else "200 but EMPTY"


async def _check_one(client, company):
    if company.ats == "workday":
        return await _check_workday(client, company)
    source_cls = _BOARD_SOURCE.get(company.ats)
    if source_cls is None:
        return company.ats, company.slug, "skipped (no board-listing endpoint)"
    source = source_cls(company)
    try:
        response = await client.get(source.board_url())
    except Exception as exc:  # live tool: report every company, don't crash the batch
        return company.ats, company.slug, f"error: {exc}"
    if response.status_code != 200:
        return company.ats, company.slug, f"HTTP {response.status_code}"
    try:
        parsed = source.parse(response.json())
    except Exception as exc:
        return company.ats, company.slug, f"200 but unparseable: {exc}"
    postings = parsed[0] if isinstance(parsed, tuple) else parsed
    if not postings:
        return company.ats, company.slug, "200 but EMPTY (unknown slug, or nothing posted)"
    return company.ats, company.slug, f"200 OK ({len(postings)} postings)"


async def check_all():
    import httpx

    from radar.config import load_users

    companies = {(c.ats, c.slug): c for u in load_users() for c in u.watchlist.companies}
    async with httpx.AsyncClient(timeout=15) as client:
        for company in companies.values():
            ats, slug, status = await _check_one(client, company)
            print(f"{ats:16} {slug:35} {status}")


if __name__ == "__main__":
    import asyncio

    if "--check" in sys.argv:
        asyncio.run(check_all())
    else:
        print("usage: python -m radar.sources.discover --check")
