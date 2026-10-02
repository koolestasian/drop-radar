"""github_repo source: poll curated community lists (e.g. SimplifyJobs) via the
GitHub Contents API, conditionally (ETag), and diff rows against what we've
already emitted.

Verified against the live READMEs of SimplifyJobs/Summer2027-Internships and
SimplifyJobs/New-Grad-Positions:
- The listing is an HTML <table> embedded in the markdown (columns Company |
  Role | Location | Application | Age), not a '|'-delimited markdown table.
  We parse it with stdlib html.parser. A plain JSON array (list of objects)
  is also accepted, best-effort.
- Summer2027-Internships' README.md is >1MB. The default
  'application/vnd.github+json' media type then returns encoding:"none" with
  no content, so we request 'application/vnd.github.raw+json' instead: the
  raw file body comes back as the response text at any size, and ETag/304
  still work the same way.
- Rows are grouped by category into several <table> blocks, each repeating
  its own <thead>; we skip every header row, not just the first.
- A company cell of "↳" means "same company as the row above" (continuation
  of a multi-location/multi-role posting); we carry the last real company
  name forward.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import quote

from radar.errors import SourceError
from radar.models import Item
from radar.sources import registry

API = "https://api.github.com/repos/{owner}/{repo}/contents/{path}"
GITHUB_TOKEN = os.environ.get("GH_TOKEN", "").strip()  # same var as radar/legacy/opportunity_monitor.py

_Row = namedtuple("_Row", "company role location url date_text")
_AGE_RE = re.compile(r"^(\d+)\s*(mo|[dhy])$", re.I)
_LEADING_MARKER_RE = re.compile(r"^[^\w(]+")  # strips emoji/legend markers like "🔥 " from a company cell
_HEADER_ALIASES = {
    "company": ("company",),
    "role": ("role", "title"),
    "location": ("location",),
    "url": ("application", "apply", "link"),
    "date_text": ("age", "date posted", "date", "posted"),
}
_DEFAULT_COLUMNS = {"company": 0, "role": 1, "location": 2, "url": 3, "date_text": 4}


@registry.register("github_repo")
def factory(repo, settings):
    return GithubRepoSource(repo)


class GithubRepoSource:
    def __init__(self, repo):
        self.repo = repo
        self.path = repo.path or "README.md"
        self.name = f"github_repo.{repo.name}"
        self.interval_s = 60.0

    async def fetch(self, ctx) -> list[Item]:
        owner, name = self.repo.name.split("/", 1)
        url = API.format(owner=owner, repo=name, path=quote(self.path, safe="/"))
        headers = {"Accept": "application/vnd.github.raw+json"}
        if GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
        if ctx.etag:
            headers["If-None-Match"] = ctx.etag
        resp = await ctx.get(url, headers=headers)

        if resp.status_code == 304:
            return []  # unchanged; keep the stored etag/cursor as-is, no body touched
        if resp.status_code == 404:
            raise SourceError(f"{self.repo.name}: path {self.path!r} not found", kind="schema")
        if resp.status_code == 401:
            raise SourceError(f"{self.repo.name}: GH_TOKEN rejected (401)", kind="auth")
        if resp.status_code in (403, 429):
            raise SourceError(f"{self.repo.name}: rate limited (status {resp.status_code})", kind="blocked")
        if resp.status_code != 200:
            raise SourceError(f"{self.repo.name}: unexpected status {resp.status_code}", kind="transient")

        # ~100ms measured on the live 1.2MB Summer2027-Internships README: too
        # long to run synchronously on the shared event loop (other sources,
        # including the latency-sensitive Instagram poller, run on it too).
        rows = await asyncio.to_thread(_parse_listing, resp.text, self.repo.name)
        if not rows:
            raise SourceError(f"{self.repo.name}: no rows parsed from {self.path!r}", kind="schema")

        ids = [_row_id(row) for row in rows]
        seen = set(json.loads(ctx.cursor)) if ctx.cursor else None
        first = seen is None  # first poll: backfill, marked seed so it never alerts (see AtsSource.fetch)
        items, emitted = [], set()
        for row, rid in zip(rows, ids):
            if rid in emitted or (not first and rid in seen):
                continue
            items.append(_to_item(self.name, row, rid, ctx.now(), raw={"seed": True} if first else None))
            emitted.add(rid)

        etag = resp.headers.get("ETag") or resp.headers.get("etag") or ctx.etag
        ctx.remember(etag=etag, cursor=json.dumps(sorted(set(ids))))
        return items


def _row_id(row):
    basis = row.url or f"{row.company}|{row.role}|{row.location}"
    return hashlib.sha256(basis.strip().lower().encode("utf-8")).hexdigest()[:16]


def _to_item(source, row, rid, now, raw=None):
    return Item(
        source=source, external_id=rid, url=row.url, title=row.role, company=row.company,
        location=row.location, published_at=_parse_published_at(row.date_text, now), raw=raw or {},
    )


def _parse_listing(text, repo_name):
    stripped = text.lstrip()
    if stripped.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SourceError(f"{repo_name}: could not parse JSON listing: {exc}", kind="schema") from exc
        if not isinstance(data, list):
            raise SourceError(f"{repo_name}: expected a JSON array of postings", kind="schema")
        return _parse_json_rows(data)
    return _parse_html_rows(text)


def _parse_json_rows(entries):
    rows = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue  # a row we can't make sense of is skipped, not a crash
        company = str(entry.get("company") or "")
        role = str(entry.get("title") or entry.get("role") or "")
        if not company and not role:
            continue
        url = str(entry.get("url") or entry.get("link") or "")
        location = str(entry.get("location") or "")
        date_text = str(entry.get("date_posted") or entry.get("date") or "")
        rows.append(_Row(company, role, location, url, date_text))
    return rows


def _clean_company(text):
    return _LEADING_MARKER_RE.sub("", text).strip()


def _parse_html_rows(text):
    parser = _TableParser()
    parser.feed(text)

    header, body = None, []
    for row in parser.rows:
        if all(is_th for _, _, is_th in row):
            if header is None:  # every table repeats its header; map columns once, skip them all
                header = [cell_text.strip().lower() for cell_text, _, _ in row]
            continue
        body.append(row)

    index = {field: _column_index(header, field, names) for field, names in _HEADER_ALIASES.items()}
    rows, last_company = [], ""
    for raw in body:
        cells = {field: _cell(raw, i) for field, i in index.items()}
        company_raw = cells["company"][0].strip()
        if company_raw == "↳":  # "↳": continuation of the row above's company
            company = last_company
        else:
            company = _clean_company(company_raw)
            last_company = company
        role = cells["role"][0]
        url = cells["url"][1] or ""
        if not url or (not company and not role):
            # No apply link (live data: a bare "🔒" Application cell means the
            # role has closed) or a row we can't make sense of: skip, don't crash.
            continue
        rows.append(_Row(company=company, role=role, location=cells["location"][0], url=url,
                          date_text=cells["date_text"][0]))
    return rows


def _column_index(header, field, names):
    if header is None:
        return _DEFAULT_COLUMNS[field]
    for name in names:
        if name in header:
            return header.index(name)
    return None


def _cell(row, i):
    if i is None or i >= len(row):
        return "", None
    text, href, _is_th = row[i]
    return text, href


class _TableParser(HTMLParser):
    """Collects every <tr>'s cells as (text, first_href, is_header_cell) across
    every HTML <table> block in a markdown/HTML blob."""

    def __init__(self):
        super().__init__()
        self.rows = []
        self._depth = 0
        self._row = None
        self._cell = None
        self._href = None
        self._is_th = False

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._depth += 1
        elif self._depth:
            if tag == "tr":
                self._row = []
            elif tag in ("td", "th"):
                self._cell, self._href, self._is_th = [], None, tag == "th"
            elif tag == "a" and self._cell is not None and self._href is None:
                self._href = dict(attrs).get("href")
            elif tag == "br" and self._cell is not None:
                self._cell.append(" | ")

    def handle_endtag(self, tag):
        if tag == "table":
            self._depth = max(0, self._depth - 1)
        elif tag == "summary" and self._cell is not None:
            self._cell.append(" | ")  # e.g. "<summary>4 locations</summary>Tampa, FL<br>..."
        elif tag == "br" and self._cell is not None and self._cell[-1:] != [" | "]:
            # Simplify writes "</br>" between locations; without this "Seattle, WA</br>Jessup, MD"
            # came out "Seattle, WAJessup, MD". The guard keeps "<br/>" (start + end) to one separator.
            self._cell.append(" | ")
        elif tag in ("td", "th") and self._cell is not None:
            text = " ".join("".join(self._cell).split())
            if self._row is not None:
                self._row.append((text, self._href, self._is_th))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(text for text, _, _ in self._row):
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _parse_published_at(text, now):
    text = (text or "").strip()
    if not text:
        return None
    m = _AGE_RE.match(text)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        days = {"h": n / 24, "d": n, "mo": n * 30, "y": n * 365}[unit]
        return now - timedelta(days=days)
    try:
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for fmt in ("%b %d %Y", "%B %d %Y"):  # year-qualified only: "Sep 15" alone is ambiguous (no year)
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return parsed.replace(tzinfo=timezone.utc)
    return None
