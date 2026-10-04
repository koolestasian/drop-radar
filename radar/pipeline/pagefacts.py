"""Fill what a source left blank by reading the posting's own link.

A posting can arrive with no location ("4 locations" from a board's search, or nothing at all from an
Instagram Story), no company or no posted date. The link usually knows: the ATS detail APIs we already use
(Workday, Greenhouse, Lever, SmartRecruiters) and schema.org JobPosting data in the page answer exactly,
for free. This only ever FILLS blanks and vague counts; a value the source stated clearly is never changed.

Safety, because the URLs come from boards, community lists and Instagram text: http(s) only, public addresses
only (checked on every redirect hop), few redirects, a size cap, short timeouts, an honest User-Agent, one
request a second per host, and robots.txt is honoured for plain pages (the ATS APIs are documented public ones).
ponytail: DNS is resolved once for the safety check and again to connect; pin the address if rebinding matters."""
from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import logging
import re
import socket
import time
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urljoin, urlparse

import requests

from radar.pipeline.pay import make_pay, pay_from_json_ld, pay_from_text, period_of, show, clean
from radar.scheduler import USER_AGENT

log = logging.getLogger(__name__)

TIMEOUT = 12
MAX_BYTES = 2_000_000
RETRY_AFTER = timedelta(days=7)  # a page that gave nothing is not asked again for a week
PAY_VERSION = 2  # bump when the pay readers change: older cached pages are read again for pay
VAGUE_LOCATION = re.compile(r"^\s*\d+\s+locations?\s*$", re.I)  # "4 Locations": a count, not a place
_robots: dict[str, tuple[float, urllib.robotparser.RobotFileParser | None]] = {}
_last_hit: dict[str, float] = {}


def needs_facts(opp) -> bool:
    return (not (opp.get("location") or "").strip() or bool(VAGUE_LOCATION.match(opp.get("location") or ""))
            or not (opp.get("company") or "").strip() or not opp.get("published_at"))


def needs_pay(opp) -> bool:
    """An open posting with a link and no pay stored yet. Pay is only shown where the posting states it."""
    return bool((opp.get("url") or "").strip()) and not (opp.get("fields") or {}).get("Pay") \
        and opp.get("status") not in ("Closed", "Expired", "Not actionable")


# ---- safe fetching -------------------------------------------------------------------------------------------

def _public(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    return bool(infos) and all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


def _get(url: str, accept: str = "application/json", *, max_bytes: int = MAX_BYTES, robots: bool = False,
         method: str = "GET", json_body=None):
    """GET with every hop checked; returns the final response or None. Never raises."""
    for _ in range(4):
        parts = urlparse(url)
        if parts.scheme not in ("http", "https") or not parts.hostname or not _public(parts.hostname):
            return None
        if robots and not _robots_allows(url):
            return None
        wait = _last_hit.get(parts.hostname, 0) + 1.0 - time.monotonic()
        if wait > 0:
            time.sleep(wait)  # one request a second per host (this runs in a worker thread)
        _last_hit[parts.hostname] = time.monotonic()
        try:
            send = requests.post if method == "POST" else requests.get
            extra = {"json": json_body} if method == "POST" else {}
            r = send(url, headers={"User-Agent": USER_AGENT, "Accept": accept}, timeout=TIMEOUT,
                     allow_redirects=False, stream=True, **extra)
        except requests.RequestException:
            return None
        if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
            if method == "POST":
                r.close()
                return None  # never redirect a search body to a different endpoint
            url = urljoin(url, r.headers.get("location", ""))
            r.close()
            continue
        body = b""
        for chunk in r.iter_content(65536):
            body += chunk
            if len(body) > max_bytes:
                break
        r._content = body[:max_bytes]
        return r
    return None


def _robots_allows(url: str) -> bool:
    parts = urlparse(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    cached = _robots.get(origin)
    if cached is None or time.monotonic() - cached[0] > 86400:
        r = _get(origin + "/robots.txt", accept="text/plain")
        parser = None
        if r is not None and r.status_code == 200:
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(r.text.splitlines())
        elif r is not None and r.status_code in (401, 403):
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(["User-agent: *", "Disallow: /"])
        elif r is not None and r.status_code < 500:
            parser = urllib.robotparser.RobotFileParser()  # no robots.txt: everything is allowed
            parser.parse([])
        cached = _robots[origin] = (time.monotonic(), parser)
    return cached[1] is not None and cached[1].can_fetch(USER_AGENT, url)  # unreachable robots.txt: don't fetch


# ---- readers: each returns {"location", "company", "posted", "deadline"} (any may be missing) or None -------------

def _date(value) -> str:
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value / 1000 if value > 1e11 else value, tz=timezone.utc).date().isoformat()
    m = re.match(r"(\d{4}-\d{2}-\d{2})", str(value or ""))
    return m.group(1) if m else ""


def _join(places) -> str:
    return "; ".join(dict.fromkeys(p.strip() for p in places if p and p.strip()))


def _workday(parts, url):
    m = re.match(r"^([A-Za-z0-9_-]+)\.(wd\d+)\.myworkdayjobs\.com$", parts.hostname or "")
    path = [x for x in parts.path.split("/") if x]
    if path and re.fullmatch(r"[a-z]{2}-[A-Z]{2}", path[0]):
        path = path[1:]  # a locale prefix
    if not m or len(path) < 3 or path[1] != "job":
        return None
    r = _get(f"https://{parts.hostname}/wday/cxs/{m.group(1)}/{path[0]}/job/{'/'.join(path[2:])}")
    if r is None or r.status_code != 200:
        return None
    info = (r.json() or {}).get("jobPostingInfo") or {}
    return {"location": _join([info.get("location"), *(info.get("additionalLocations") or [])]),
            "description": clean(info.get("jobDescription")),
            "posted": _date(info.get("startDate")), "deadline": "", "pay": pay_from_text(info.get("jobDescription"))}


def _greenhouse(parts, url):
    path = [x for x in parts.path.split("/") if x]
    query = dict(parse_qsl(parts.query))
    if len(path) >= 3 and path[1] == "jobs" and path[2].isdigit():
        board, job = path[0], path[2]
    elif path[:2] == ["embed", "job_app"] and query.get("for") and query.get("token", "").isdigit():
        board, job = query["for"], query["token"]
    else:
        return None
    r = _get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job}?pay_transparency=true")
    if r is None or r.status_code != 200:
        return None
    d = r.json()
    ranges = [make_pay(x.get("min_cents", 0) / 100, x.get("max_cents", 0) / 100, x.get("currency_type"))
              for x in d.get("pay_input_ranges") or [] if isinstance(x, dict)]
    ranges = [x for x in ranges if x]
    structured = {**ranges[0], "min": min(x["min"] for x in ranges), "max": max(x["max"] for x in ranges)} if ranges else None
    return {"location": (d.get("location") or {}).get("name") or "", "company": d.get("company_name") or "",
            "posted": _date(d.get("first_published") or d.get("updated_at")), "deadline": "",
            "description": clean(d.get("content")), "pay": structured or pay_from_text(d.get("content"))}


def _lever(parts, url):
    path = [x for x in parts.path.split("/") if x]
    if len(path) < 2:
        return None
    r = _get(f"https://api.lever.co/v0/postings/{path[0]}/{path[1]}")
    if r is None or r.status_code != 200:
        return None
    d = r.json()
    salary = d.get("salaryRange") or {}
    text = " ".join(str(x or "") for x in (d.get("salaryDescriptionPlain"), d.get("descriptionPlain"),
                                          *(l.get("content") for l in d.get("lists") or [] if isinstance(l, dict))))
    return {"location": (d.get("categories") or {}).get("location") or "", "posted": _date(d.get("createdAt")),
            "company": "", "deadline": "", "description": clean(text),
            "pay": make_pay(salary.get("min"), salary.get("max"), salary.get("currency"), period_of(salary.get("interval")))
            or pay_from_text(text)}


def _smartrecruiters(parts, url):
    path = [x for x in parts.path.split("/") if x]
    if len(path) < 2 or not path[1].split("-", 1)[0].isdigit():
        return None
    r = _get(f"https://api.smartrecruiters.com/v1/companies/{path[0]}/postings/{path[1].split('-', 1)[0]}")
    if r is None or r.status_code != 200:
        return None
    d = r.json()
    loc = d.get("location") or {}
    place = ", ".join(x for x in (loc.get("city"), (loc.get("region") or "").upper()) if x)
    if loc.get("remote"):
        place = f"{place} (Remote)" if place else "Remote"
    comp = d.get("compensation") or {}
    sections = ((d.get("jobAd") or {}).get("sections") or {}).values()
    text = " ".join(str(s.get("text") or "") for s in sections if isinstance(s, dict))
    return {"location": place, "company": (d.get("company") or {}).get("name") or "",
            "posted": _date(d.get("releasedDate")), "deadline": "",
            "description": clean(text), "pay": make_pay(comp.get("min"), comp.get("max"), comp.get("currency"), period_of(comp.get("period")))
            or pay_from_text(text)}


def _job_posting(url):
    """The page's schema.org JobPosting dict, or None."""
    if not _robots_allows(url):
        return None
    r = _get(url, accept="text/html,application/xhtml+xml")
    if r is None or r.status_code != 200:
        return None
    text = r.content.decode("utf-8", errors="replace")
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
                    return item
                stack.extend(v for k, v in item.items() if k == "@graph")
    return None


def _json_ld(parts, url):
    posting = _job_posting(url)
    return _from_posting(posting) if posting else None


def org_site(url):
    """The employer's own website as the posting states it (hiringOrganization.sameAs or .url), or None."""
    posting = _job_posting(url)
    org = posting.get("hiringOrganization") if posting else None
    if not isinstance(org, dict):
        return None
    for key in ("sameAs", "url"):
        value = org.get(key)
        value = value[0] if isinstance(value, list) and value else value
        if isinstance(value, str) and value.startswith("http"):
            return value
    return None


def _from_posting(posting) -> dict:
    places = []
    locations = posting.get("jobLocation")
    for loc in [locations] if isinstance(locations, dict) else (locations or []):
        address = (loc or {}).get("address") or {}
        if isinstance(address, dict):
            places.append(", ".join(str(x) for x in (address.get("addressLocality"), address.get("addressRegion")) if x))
    if str(posting.get("jobLocationType", "")).upper() == "TELECOMMUTE":
        places.append("Remote")
    org = posting.get("hiringOrganization")
    org = org.get("name") if isinstance(org, dict) else org
    return {"location": _join(places), "company": html.unescape(org).strip() if isinstance(org, str) else "",
            "posted": _date(posting.get("datePosted")), "deadline": _date(posting.get("validThrough")),
            "description": clean(posting.get("description")), "pay": pay_from_json_ld(posting) or pay_from_text(posting.get("description"))}


def fetch_facts(url: str):
    """What the link says, or None. Never raises."""
    try:
        parts = urlparse(url)
        host = (parts.hostname or "").lower()
        if host.endswith("myworkdayjobs.com"):
            return _workday(parts, url)
        if host.endswith("greenhouse.io"):
            facts = _greenhouse(parts, url)
            return facts or _json_ld(parts, url)
        if host == "jobs.lever.co":
            return _lever(parts, url) or _json_ld(parts, url)
        if host == "jobs.smartrecruiters.com":
            return _smartrecruiters(parts, url) or _json_ld(parts, url)
        return _json_ld(parts, url)  # Ashby, company sites, anything with schema.org job data
    except Exception:
        log.warning("page facts failed for %s", url, exc_info=True)
        return None


# ---- applying ------------------------------------------------------------------------------------------------

def changes_for(opp, facts) -> dict:
    """The columns to set: only blanks and bare counts, from non-empty facts."""
    out = {}
    loc = (opp.get("location") or "").strip()
    if facts.get("location") and (not loc or VAGUE_LOCATION.match(loc)):
        out["location"] = facts["location"]
    if facts.get("company") and not (opp.get("company") or "").strip():
        out["company"] = facts["company"]
    if facts.get("posted") and not opp.get("published_at"):
        out["published_at"] = f"{facts['posted']}T00:00:00+00:00"  # date-only, stored the way sources store them
    if facts.get("deadline") and not (opp.get("deadline") or "").strip():
        out["deadline"] = facts["deadline"]
    if facts.get("pay") and needs_pay(opp):
        out["pay"] = show(facts["pay"])  # stored in fields["Pay"], see PageFacts.fill
    return out


class PageFacts:
    def __init__(self, store, fetch=fetch_facts, concurrency=3, pay_llm=None):
        self.store, self.fetch = store, fetch
        self._slots = asyncio.Semaphore(concurrency)
        from radar.pipeline.pay_llm import PayLLM
        self.pay_llm = pay_llm or PayLLM(store)

    def _cached(self, url):
        hit = self.store.get_enrichment(f"page:{url}")
        if hit is None:
            return None
        if hit.get("facts") is None and datetime.fromisoformat(hit["t"]) < datetime.now(timezone.utc) - RETRY_AFTER:
            return None  # a miss is retried after a week
        return hit

    async def fill(self, opportunity_id, dry_run=False, pay=False, llm=True):
        """Read the link if the stored posting is missing something. Returns what it set (or would set); `pay`
        also looks for a stated pay range, which costs a request even for a posting with nothing else missing."""
        opp = self.store.get_opportunity(opportunity_id)
        wants_pay = pay and opp is not None and needs_pay(opp)
        if opp is None or not opp.get("url") or not (needs_facts(opp) or wants_pay):
            return {}
        url = opp["url"]
        hit = self._cached(url)
        if hit is not None and wants_pay and hit.get("pv") != PAY_VERSION:
            hit = None  # read before pay was looked for
        if hit is None:
            async with self._slots:
                facts = await asyncio.to_thread(self.fetch, url)
            hit = {"t": datetime.now(timezone.utc).isoformat(), "facts": facts or None, "pv": PAY_VERSION}
            if not dry_run:
                self.store.set_enrichment(f"page:{url}", hit)
        facts = dict(hit["facts"] or {})
        if wants_pay and llm and not facts.get("pay"):
            facts["pay"] = await self.pay_llm.extract(facts.get("description"), dry_run=dry_run)
        opp = self.store.get_opportunity(opportunity_id)  # fills still blank after network/model awaits
        changes = changes_for(opp, facts) if opp else {}
        if not wants_pay:
            changes.pop("pay", None)
        if changes and not dry_run:
            columns = {k: v for k, v in changes.items() if k != "pay"}
            if "pay" in changes:
                columns["fields"] = {**(opp.get("fields") or {}), "Pay": changes["pay"]}
            self.store.save_opportunity(opportunity_id, first_seen=opp["first_seen"], **columns)
        return changes
