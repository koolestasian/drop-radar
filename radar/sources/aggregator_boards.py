"""Off-box, pinned aggregator company lists -> verified boards -> review queue.

python -m radar.sources.aggregator_boards --ats ashby --limit 50
Dataset attribution: Riley Dorrington / Feashliaa, job-board-aggregator,
https://github.com/Feashliaa/job-board-aggregator (CC BY-NC 4.0).
No DB writes or automatic watchlist additions. Company names are not guessed.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from radar.config import Company, load_users
from radar.pipeline import pagefacts
from radar.sources.yc_boards import discover

COMMIT = "4bee912c68ca7549ce202db19c61dacded0baaf6"
BASE = f"https://raw.githubusercontent.com/Feashliaa/job-board-aggregator/{COMMIT}/data"
BOARDS = {"greenhouse": "https://boards.greenhouse.io/", "lever": "https://jobs.lever.co/",
          "ashby": "https://jobs.ashbyhq.com/", "workday": ""}
ATTRIBUTION = "Riley Dorrington / Feashliaa, job-board-aggregator"
LICENSE = "https://creativecommons.org/licenses/by-nc/4.0/"


def candidates(ats, slugs, watched):
    """Validate untrusted dataset slugs before constructing any fetch URL."""
    seen = set(watched)
    for slug in slugs:
        if ats == "workday":
            if not isinstance(slug, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,40}\|wd\d{1,2}\|[A-Za-z0-9_-]{1,80}", slug):
                continue
            tenant, host, site = slug.split("|")
            slug = f"{tenant}.{host}/{site}"
            url = f"https://{tenant}.{host}.myworkdayjobs.com/{site}"
        else:
            url = BOARDS[ats] + slug if isinstance(slug, str) else ""
        if ats != "workday" and (not isinstance(slug, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", slug)):
            continue
        key = (ats, slug.lower())
        if key in seen:
            continue
        seen.add(key)
        yield {"name": "", "website": url, "isHiring": True}


def workday_boards(batch):
    from radar.sources.board_review import pair_from_url, probe
    for candidate in batch:
        pair = pair_from_url(candidate["website"])
        if pair:
            result = probe(Company("", *pair))
            if result["status"] == "ok":
                yield {"ats": pair[0], "slug": pair[1], "company": "", "website": candidate["website"],
                       "board_url": candidate["website"], "postings": result["postings"], "verified": True,
                       "checked_at": datetime.now(timezone.utc).isoformat(), "version": 1}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ats", choices=BOARDS, default="ashby")
    parser.add_argument("--limit", type=int, default=50, help="source entries to inspect (watched boards skipped)")
    parser.add_argument("--offset", type=int, default=0, help="offset within the pinned source list")
    parser.add_argument("--out", default="data/t16/16.4-aggregator-queue.jsonl")
    parser.add_argument("--watched", help="JSON array of [ats, slug] pairs exported from live watchlists")
    args = parser.parse_args(argv)
    if args.limit < 1 or args.offset < 0:
        parser.error("limit must be positive and offset must be nonnegative")
    source = f"{BASE}/{args.ats}_companies.json"
    response = pagefacts._get(source, robots=True)
    if response is None or response.status_code != 200:
        raise SystemExit("aggregator dataset unavailable; no review file written")
    try:
        slugs = response.json()
        if not isinstance(slugs, list) or any(not isinstance(s, str) for s in slugs):
            raise ValueError("expected an array of slugs")
    except ValueError as exc:
        raise SystemExit("aggregator dataset unreadable; no review file written") from exc
    watched = {(c.ats, c.slug.lower()) for u in load_users() for c in u.watchlist.companies}
    if args.watched:
        watched.update((ats, slug.lower()) for ats, slug in json.loads(Path(args.watched).read_text()))
    out = Path(args.out)
    if out.exists():
        with out.open() as file:
            for line in file:
                row = json.loads(line)
                watched.add((row["ats"], row["slug"].lower()))
    # Slice before removing watched/queued rows so batch offsets stay stable across runs.
    batch = list(candidates(args.ats, slugs[args.offset:args.offset + args.limit], watched))
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out.open("a") as file:
        for row in (workday_boards(batch) if args.ats == "workday" else discover(batch, watched)):
            row.update(source=source, dataset_commit=COMMIT, attribution=ATTRIBUTION,
                       license=LICENSE, company_verified=False)
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
            file.flush()
            count += 1
    print(f"probed {len(batch)} unwatched {args.ats} boards: queued {count} -> {out}; "
          f"pinned list has {len(slugs)} slugs; next offset {args.offset + args.limit}")


if __name__ == "__main__":
    main()
