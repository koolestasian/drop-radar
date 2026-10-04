"""Manual/live tooling for the ATS sources -- not run by the test suite.

- `python -m radar.sources.discover --check`: one live request per board on any
  user's watchlist (config/users.yaml), prints whether it returned a parseable
  200 and how many postings. A 200 with zero postings is flagged: SmartRecruiters
  answers 200 + an empty list for a slug that doesn't exist.
- `python -m radar find-boards`: ATS boards the stored apply links point at that nobody watches
  yet, probed, written to a review file (T16 16.4). Nothing is added to a watchlist from here.
- `mine_tracker_slugs()`: (ats, slug) pairs recovered from the existing
  tracker's application links. Imports the workbook reader lazily so this
  module stays side-effect-free when the registry auto-imports it.
"""
from __future__ import annotations

import re
import sys
from urllib.parse import parse_qsl, urlparse


def _slug_from_url(url):
    """(ats, slug) for a recognized ATS application link, else None.

    Mirrors the host/path parsing the retired legacy job_pages.fetch_job_facts used
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
    match = re.fullmatch(r"([a-z0-9-]+\.fa(?:\.[a-z0-9]+)*)\.oraclecloud\.com", host)
    if match and len(parts) >= 5 and parts[1:4] == ["CandidateExperience", parts[2], "sites"]:
        return ("oracle", f"{match.group(1)}/{parts[4]}")  # /hcmUI/CandidateExperience/<lang>/sites/<site>/...
    if host.endswith(".eightfold.ai"):
        return ("eightfold", f"{host}/{host.removesuffix('.eightfold.ai')}.com")  # domain guessed; --check verifies
    if host == "apply.workable.com":
        return ("workable", parts[0]) if parts else None
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


def unwatched_boards(rows, watched):
    """`rows`: (company, url) pairs. Returns {(ats, slug): (most common company, postings)} for
    recognized boards missing from `watched` ((ats, slug) pairs, compared case-insensitively)."""
    import collections

    names, spelled = collections.defaultdict(collections.Counter), {}
    for company, url in rows:
        pair = _slug_from_url(url or "")
        if pair and (pair[0], pair[1].lower()) not in watched:
            key = (pair[0], pair[1].lower())
            spelled.setdefault(key, pair)  # first spelling seen: some ATSes (SmartRecruiters) are case-sensitive
            names[key][company or ""] += 1
    return {spelled[k]: (c.most_common(1)[0][0], sum(c.values())) for k, c in names.items()}


async def find_boards(store, watched, limit=None, concurrency=4):
    """Probe each unwatched board once. Returns [(ats, slug, company, postings_seen, status)], boards
    that answer with open postings first, then by how many stored postings point at them."""
    import asyncio

    import httpx

    from radar.config import Company
    from radar.scheduler import USER_AGENT

    rows = store.conn.execute("SELECT company, url FROM opportunities WHERE url != ''").fetchall()
    boards = sorted(unwatched_boards(((r[0], r[1]) for r in rows), watched).items(), key=lambda kv: -kv[1][1])[:limit]
    gate = asyncio.Semaphore(concurrency)

    async def one(client, key, name, seen):
        async with gate:
            ats, slug, status = await _check_one(client, Company(name or key[1], key[0], key[1]))
        return key[0], key[1], name, seen, status

    async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        done = await asyncio.gather(*(one(client, k, n, c) for k, (n, c) in boards))
    return sorted(done, key=lambda r: (not r[4].startswith("200 OK"), -r[3]))


async def _check_one(client, company):
    """One live fetch through the source's real fetch_postings, so the check runs
    the code the radar will: a parseable 200 with postings, or why not."""
    import asyncio

    from radar.scheduler import Clock, FetchContext, HostLimiter
    from radar.sources.registry import FACTORIES, _import_source_modules

    _import_source_modules()
    factory = FACTORIES.get(company.ats)
    if factory is None:
        return company.ats, company.slug, "skipped (no source for this ats)"
    clock = Clock()
    ctx = FetchContext("check", client, clock, HostLimiter(clock, 5.0), asyncio.Semaphore(5))
    try:
        fetched = await factory(company, None).fetch_postings(ctx)
    except Exception as exc:  # live tool: report every company, don't crash the batch
        return company.ats, company.slug, f"error: {exc}"
    postings = fetched[0] if fetched else {}
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
