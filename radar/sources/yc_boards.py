"""Off-box YC board discovery: source links -> guarded fetch -> JSONL review queue.

python -m radar.sources.yc_boards --limit 50 --offset 0
Uses the documented https://github.com/yc-oss/api hiring directory. No DB writes,
watchlist changes or guessed slugs. Run again to retry blocked/unreadable pages.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

from radar.config import Company, load_users
from radar.pipeline import pagefacts
from radar.sources.discover import _slug_from_url
from radar.sources.registry import FACTORIES, _import_source_modules

DIRECTORY = "https://yc-oss.github.io/api/companies/hiring.json"
VERSION = 1
KINDS = {"greenhouse", "lever", "ashby", "smartrecruiters"}


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.urls.append(href)


def board_from_url(url):
    parts = urlparse(url)
    # Exact hosts and simple slugs: directory/page data must never shape an API host/path.
    if parts.scheme not in {"http", "https"} or parts.hostname not in {
        "boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.lever.co",
        "jobs.ashbyhq.com", "jobs.smartrecruiters.com",
    }:
        return None
    pair = _slug_from_url(url)
    if pair is None and parts.hostname in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
        path = parts.path.strip("/").split("/")
        if len(path) == 1:
            pair = ("greenhouse", path[0])
    if pair and pair[0] in KINDS and re.fullmatch(r"[A-Za-z0-9_-]{1,100}", pair[1]):
        return pair
    return None


def page_links(url):
    if not pagefacts._robots_allows(url):
        return []
    response = pagefacts._get(url, accept="text/html", robots=True)
    if response is None or response.status_code != 200:
        return []
    parser = Links()
    parser.feed(response.text)
    return [urljoin(response.url, href) for href in parser.urls]


def discover(companies, watched):
    """Yield only nonempty parseable boards linked by the company's own site."""
    _import_source_modules()
    seen = set(watched)
    for company in companies:
        if not isinstance(company, dict) or company.get("isHiring") is not True:
            continue
        name, website = company.get("name"), company.get("website")
        if not isinstance(name, str) or not isinstance(website, str) or not website.strip():
            continue
        website = website.strip()
        if "://" not in website:
            website = "https://" + website
        try:
            direct = board_from_url(website)
            links = [website] if direct else page_links(website)
            # One careers page linked from the homepage; no speculative crawl.
            careers = next((u for u in links if urlparse(u).hostname == urlparse(website).hostname
                            and re.search(r"(?:careers?|jobs|join)(?:/|$|[?#-])", urlparse(u).path, re.I)), None)
            if careers and not board_from_url(careers):
                links += page_links(careers)
            for url in links:
                pair = board_from_url(url)
                if not pair or (pair[0], pair[1].lower()) in seen:
                    continue
                seen.add((pair[0], pair[1].lower()))
                source = FACTORIES[pair[0]](Company(name, *pair), None)
                response = pagefacts._get(source.board_url())  # documented public ATS API
                if response is None or response.status_code != 200:
                    continue
                postings = source.parse(response.json())
                if isinstance(postings, tuple):
                    postings = postings[0]
                if postings:
                    yield {"ats": pair[0], "slug": pair[1], "company": name, "website": website,
                           "board_url": url, "postings": len(postings), "source": DIRECTORY,
                           "verified": True, "checked_at": datetime.now(timezone.utc).isoformat(), "version": VERSION}
        except Exception as exc:  # batch tool: one unreadable page must not lose other companies' results
            print(f"skipped {name!r}: {type(exc).__name__}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=50, help="number of hiring companies to inspect")
    parser.add_argument("--offset", type=int, default=0, help="resume at this hiring-directory offset")
    parser.add_argument("--out", default="data/t16/16.4-yc-queue.jsonl")
    parser.add_argument("--watched", help="JSON array of [ats, slug] pairs exported from the live watchlists")
    args = parser.parse_args(argv)
    if args.limit < 1 or args.offset < 0:
        parser.error("limit must be positive and offset must be nonnegative")
    # This command runs off-box; retain the default 2 MB limit for all posting/page fetches.
    response = pagefacts._get(DIRECTORY, max_bytes=32_000_000)
    if response is None or response.status_code != 200:
        raise SystemExit("YC directory unavailable; no review file written")
    try:
        companies = response.json()
        if not isinstance(companies, list) or any(not isinstance(c, dict) for c in companies):
            raise ValueError("expected an array of companies")
    except ValueError as exc:
        raise SystemExit("YC directory unreadable; no review file written") from exc
    watched = {(c.ats, c.slug.lower()) for u in load_users() for c in u.watchlist.companies}
    if args.watched:
        watched.update((ats, slug.lower()) for ats, slug in json.loads(Path(args.watched).read_text()))
    companies = [c for c in companies if c.get("isHiring") is True]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        with out.open() as file:
            for line in file:
                row = json.loads(line)
                watched.add((row["ats"], row["slug"].lower()))
    # Append across batches; keep previous review results and never cache misses.
    count = 0
    with out.open("a") as file:
        for row in discover(companies[args.offset:args.offset + args.limit], watched):
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
            file.flush()
            count += 1
    print(f"queued {count} boards -> {out}; directory has {len(companies)} hiring companies")


if __name__ == "__main__":
    main()
