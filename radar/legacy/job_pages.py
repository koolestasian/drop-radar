#!/usr/bin/env python3
"""Read the real job posting behind an application link.

Applicant-tracking systems (Greenhouse, Lever, Ashby, SmartRecruiters) expose
public JSON APIs that return the canonical title and location, and answer 404
or "inactive" once a posting is taken down. Other pages are read for
schema.org JobPosting JSON-LD, falling back to og:title.

`fetch_job_facts` never raises. Its result always has a "status":

- "open": the posting was found and is live
- "closed": the source definitively says the posting is gone
- "unknown": the page could not be read (timeouts, 403s, JS-only pages)

Only a definitive signal produces "closed"; errors never do.
"""
import html
import json
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlparse

import requests

USER_AGENT = "Mozilla/5.0 (compatible; zero2sudo-opportunity-monitor; +https://github.com)"
TIMEOUT = 12
DESCRIPTION_LIMIT = 6000

_ashby_boards = {}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _get(session, url, **kwargs):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9"}
    headers.update(kwargs.pop("headers", {}))
    return session.get(url, headers=headers, timeout=TIMEOUT, **kwargs)


def _plain_text(value):
    value = html.unescape(str(value or ""))  # Greenhouse double-escapes content
    value = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", value, flags=re.S | re.I)
    value = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    lines = [" ".join(line.split()) for line in value.splitlines()]
    return "\n".join(line for line in lines if line)[:DESCRIPTION_LIMIT]


def _iso_date(value):
    if not value:
        return ""
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10**11 else value
        return datetime.fromtimestamp(seconds, tz=timezone.utc).date().isoformat()
    match = re.match(r"(\d{4}-\d{2}-\d{2})", str(value))
    return match.group(1) if match else ""


def _facts(status, source, **values):
    facts = {"status": status, "source": source, "checked_at": _now()}
    facts.update({key: value for key, value in values.items() if value not in (None, "", [])})
    return facts


def _unknown(source, reason):
    return _facts("unknown", source, error=str(reason)[:200])


def _greenhouse(session, board, job_id):
    response = _get(session, f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}")
    if response.status_code == 404:
        return _facts("closed", "greenhouse")
    if response.status_code != 200:
        return _unknown("greenhouse", f"HTTP {response.status_code}")
    data = response.json()
    return _facts(
        "open", "greenhouse",
        title=data.get("title"),
        organization=data.get("company_name"),
        location=(data.get("location") or {}).get("name"),
        posted=_iso_date(data.get("first_published") or data.get("updated_at")),
        description=_plain_text(data.get("content")),
    )


def _lever(session, company, posting_id):
    response = _get(session, f"https://api.lever.co/v0/postings/{company}/{posting_id}")
    if response.status_code == 404:
        return _facts("closed", "lever")
    if response.status_code != 200:
        return _unknown("lever", f"HTTP {response.status_code}")
    data = response.json()
    categories = data.get("categories") or {}
    return _facts(
        "open", "lever",
        title=data.get("text"),
        location=categories.get("location"),
        posted=_iso_date(data.get("createdAt")),
        description=_plain_text(data.get("descriptionPlain") or data.get("description")),
    )


def _ashby(session, board, job_id):
    if board not in _ashby_boards:
        response = _get(session, f"https://api.ashbyhq.com/posting-api/job-board/{board}")
        if response.status_code != 200:
            return _unknown("ashby", f"HTTP {response.status_code}")
        _ashby_boards[board] = {job.get("id"): job for job in response.json().get("jobs") or []}
    job = _ashby_boards[board].get(job_id)
    if not job or job.get("isListed") is False:
        return _facts("closed", "ashby")
    return _facts(
        "open", "ashby",
        title=job.get("title"),
        location=job.get("location"),
        posted=_iso_date(job.get("publishedAt")),
        description=_plain_text(job.get("descriptionPlain") or job.get("descriptionHtml")),
    )


def _smartrecruiters(session, company, posting_id):
    response = _get(session, f"https://api.smartrecruiters.com/v1/companies/{company}/postings/{posting_id}")
    if response.status_code == 404:
        return _facts("closed", "smartrecruiters")
    if response.status_code != 200:
        return _unknown("smartrecruiters", f"HTTP {response.status_code}")
    data = response.json()
    location = data.get("location") or {}
    place = ", ".join(x for x in (location.get("city"), (location.get("region") or "").upper()) if x)
    if location.get("remote"):
        place = f"{place} (Remote)" if place else "Remote"
    sections = ((data.get("jobAd") or {}).get("sections") or {}).values()
    return _facts(
        "open" if data.get("active", True) else "closed", "smartrecruiters",
        title=data.get("name"),
        organization=(data.get("company") or {}).get("name"),
        location=place,
        posted=_iso_date(data.get("releasedDate")),
        description=_plain_text(" ".join(str(s.get("text") or "") for s in sections if isinstance(s, dict))),
    )


def _json_ld_postings(text):
    postings = []
    for block in re.findall(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", text, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                kind = item.get("@type")
                if kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind):
                    postings.append(item)
                stack.extend(value for key, value in item.items() if key == "@graph")
    return postings


def _json_ld_location(posting):
    locations = posting.get("jobLocation")
    if isinstance(locations, dict):
        locations = [locations]
    places = []
    for location in locations or []:
        address = (location or {}).get("address") or {}
        if isinstance(address, dict):
            place = ", ".join(
                str(x) for x in (address.get("addressLocality"), address.get("addressRegion")) if x
            )
            if place:
                places.append(place)
    if str(posting.get("jobLocationType", "")).upper() == "TELECOMMUTE":
        places.append("Remote")
    return "; ".join(dict.fromkeys(places))


def _generic(session, url):
    response = _get(session, url, headers={"Accept": "text/html,application/xhtml+xml"})
    if response.status_code in (404, 410):
        return _facts("closed", "html")
    if response.status_code != 200:
        return _unknown("html", f"HTTP {response.status_code}")
    headers = getattr(response, "headers", None) or {}
    if "charset" not in headers.get("content-type", "").lower() and hasattr(response, "encoding"):
        # requests assumes ISO-8859-1 for text/html without a charset, which
        # turns UTF-8 dashes into mojibake; the web is overwhelmingly UTF-8.
        response.encoding = "utf-8"
    text = response.text[:2_000_000]
    postings = _json_ld_postings(text)
    if postings:
        posting = postings[0]
        organization = posting.get("hiringOrganization")
        if isinstance(organization, dict):
            organization = organization.get("name")
        return _facts(
            "open", "json-ld",
            title=html.unescape(str(posting.get("title") or "")).strip(),
            organization=organization if isinstance(organization, str) else "",
            location=_json_ld_location(posting),
            deadline=_iso_date(posting.get("validThrough")),
            posted=_iso_date(posting.get("datePosted")),
            description=_plain_text(posting.get("description")),
        )
    match = re.search(
        r"<meta[^>]+property=[\"']og:title[\"'][^>]+content=[\"']([^\"']*)[\"']", text, re.I
    ) or re.search(r"<meta[^>]+content=[\"']([^\"']*)[\"'][^>]+property=[\"']og:title[\"']", text, re.I)
    title = html.unescape(match.group(1)).strip() if match else ""
    # Without structured data the page might be a search page or a login
    # wall, so it only contributes a title and never a "closed" verdict.
    return _facts("unknown", "og:title", title=title) if title else _unknown("html", "no job data")


def fetch_job_facts(url, session=None):
    """Facts about the posting at `url`; never raises."""
    session = session or requests.Session()
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        parts = [part for part in parsed.path.split("/") if part]
        query = dict(parse_qsl(parsed.query))
        if host.endswith("greenhouse.io"):
            if len(parts) >= 3 and parts[1] == "jobs" and parts[2].isdigit():
                return _greenhouse(session, parts[0], parts[2])
            if parts[:2] == ["embed", "job_app"] and query.get("for") and query.get("token", "").isdigit():
                return _greenhouse(session, query["for"], query["token"])
        if host == "jobs.lever.co" and len(parts) >= 2:
            return _lever(session, parts[0], parts[1])
        if host == "jobs.ashbyhq.com" and len(parts) >= 2:
            return _ashby(session, parts[0], parts[1])
        if host == "jobs.smartrecruiters.com" and len(parts) >= 2:
            posting_id = parts[1].split("-", 1)[0]
            if posting_id.isdigit():
                return _smartrecruiters(session, parts[0], posting_id)
        return _generic(session, url)
    except (requests.RequestException, ValueError) as exc:
        return _unknown("network", exc)
