"""Guarded careers URL discovery and board health probes; never edits a watchlist."""
import re
from urllib.parse import urlparse

from radar.config import Company
from radar.pipeline import pagefacts
from radar.sources.discover import _slug_from_url
from radar.sources.registry import FACTORIES, _import_source_modules
from radar.sources.yc_boards import board_from_url, page_links

KINDS = ("greenhouse", "lever", "ashby", "smartrecruiters", "workday")
SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
WORKDAY = re.compile(r"[A-Za-z0-9_-]{1,40}\.wd\d{1,2}/[A-Za-z0-9_-]{1,80}")


def valid(company):
    return company.ats in KINDS and bool((WORKDAY if company.ats == "workday" else SLUG).fullmatch(company.slug))


def pair_from_url(url):
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or parts.username or parts.password:
        return None
    pair = board_from_url(url)
    if not pair and re.fullmatch(r"[A-Za-z0-9_-]+\.wd\d{1,2}\.myworkdayjobs\.com", parts.hostname or ""):
        pair = _slug_from_url(url)
    return pair if pair and valid(Company("", *pair)) else None


def probe(company):
    if not valid(company):
        return {"status": "error", "postings": 0}
    _import_source_modules()
    source = FACTORIES[company.ats](company, None)
    if company.ats == "workday":
        response = pagefacts._get(source.jobs_url(), method="POST",
                                  json_body={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""})
    else:
        response = pagefacts._get(source.board_url())
    if response is None:
        return {"status": "error", "postings": 0}
    if response.status_code == 404:
        return {"status": "not_found", "postings": 0}
    if response.status_code != 200:
        return {"status": "error", "postings": 0}
    try:
        data = response.json()
        if company.ats == "workday":
            count = data["total"]
            if not isinstance(count, int) or isinstance(count, bool) or count < 0 or not isinstance(data["jobPostings"], list):
                raise ValueError("invalid search result")
        elif company.ats == "smartrecruiters":
            source.parse(data)  # schema validation, including the first page
            count = int(data["totalFound"])
            if count < 0:
                raise ValueError("invalid posting count")
        else:
            count = len(source.parse(data))
    except (ValueError, KeyError, TypeError, AttributeError, IndexError):
        return {"status": "error", "postings": 0}
    return {"status": "ok" if count else "empty", "postings": count}


def discover_url(url):
    """Find one verified board, or explain why more precise input is needed."""
    parts = urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError("Paste a public https:// careers or job-board URL.")
    direct = pair_from_url(url)
    links = [url] if direct else page_links(url)
    if not direct:
        careers = next((u for u in links if urlparse(u).hostname == parts.hostname
                        and re.search(r"(?:careers?|jobs|join)(?:/|$|[?#-])", urlparse(u).path, re.I)), None)
        if careers:
            links += page_links(careers)
    pairs = {pair for link in links if (pair := pair_from_url(link))}
    if len(pairs) > 3:
        raise ValueError("Several boards are linked here. Paste the direct job-board URL.")
    found = []
    for ats, slug in sorted(pairs):
        result = probe(Company("", ats, slug))
        if result["status"] == "ok":
            found.append({"name": "", "ats": ats, "slug": slug, "tier": "C", "postings": result["postings"]})
    if len(found) > 1:
        raise ValueError("Several boards are linked here. Paste the direct job-board URL.")
    if not found:
        raise ValueError("No supported board with open postings was found. Try a direct Greenhouse, Lever, Ashby, SmartRecruiters or Workday URL.")
    return found[0]
