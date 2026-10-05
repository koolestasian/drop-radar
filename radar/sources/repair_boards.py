"""Off-box board maintenance: verified repairs/archive proposals, never live edits.

Run daily: python -m radar.sources.repair_boards [--companies FILE]
FILE is a JSON array of watchlist company records exported from live config/accounts.
State/log/queue are local under data/t16; the owner reviews proposals before applying.
"""
import argparse
import dataclasses
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from radar.config import Company, load_users
from radar.sources.board_review import KINDS, probe, valid


def variants(company):
    """Small bounded set, across simple-slug ATSes. Guesses remain review proposals."""
    names = [company.slug.split("/")[0].split(".")[0], company.name]
    slugs = []
    for name in names:
        words = re.sub(r"\b(?:incorporated|inc|corporation|corp|llc|ltd)\b", "", name, flags=re.I)
        for slug in (re.sub(r"[^a-z0-9]", "", words.lower()), re.sub(r"[^a-z0-9]+", "-", words.lower()).strip("-")):
            if slug and slug not in slugs:
                slugs.append(slug)
    for ats in KINDS:
        if ats == "workday":
            continue  # a Workday tenant/site can't be inferred from a company name
        for slug in slugs[:3]:
            candidate = Company(company.name, ats, slug)
            if valid(candidate) and (ats, slug.lower()) != (company.ats, company.slug.lower()):
                yield candidate


def inspect(company, previous, now):
    result = probe(company)
    state = {**result, "checked_at": now.isoformat()}
    proposals = []
    if result["status"] == "empty":
        last = datetime.fromisoformat(previous["checked_at"]) if previous.get("checked_at") else now
        since = previous.get("empty_since") if previous.get("status") == "empty" and now - last <= timedelta(days=2) else None
        state["empty_since"] = since or now.isoformat()
        if now - datetime.fromisoformat(state["empty_since"]) >= timedelta(days=30):
            proposals.append({"action": "archive", "reason": "no postings observed for 30 days", "empty_since": state["empty_since"]})
    elif result["status"] == "not_found":
        for candidate in variants(company):
            checked = probe(candidate)
            if checked["status"] == "ok":
                proposals.append({"action": "repair", "replacement": dataclasses.asdict(candidate),
                                  "postings": checked["postings"], "company_verified": False,
                                  "reason": "original board returned 404; candidate board has open postings"})
    # Errors and nonempty boards reset empty history; never archive from a failed fetch.
    return state, [{**p, "company": dataclasses.asdict(company), "source": "board-health-probe",
                    "verified": True, "checked_at": now.isoformat(), "version": 1, "status": "pending_review"} for p in proposals]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companies", help="JSON array of live watchlist company records")
    parser.add_argument("--state", default="data/t16/16.4-board-health.json")
    parser.add_argument("--out", default="data/t16/16.4-repair-queue.jsonl")
    parser.add_argument("--log", default="data/t16/16.4-board-health.jsonl")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("limit must be positive")
    records = json.loads(Path(args.companies).read_text()) if args.companies else [
        dataclasses.asdict(c) for user in load_users() for c in user.watchlist.companies]
    companies = {(c.ats, c.slug.lower()): c for c in (Company(**r) for r in records)}
    state_path, out, log = map(Path, (args.state, args.out, args.log))
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    queued = set()
    def identity(row):
        replacement = row.get("replacement", {})
        return (row["company"]["ats"], row["company"]["slug"].lower(), row["action"],
                replacement.get("ats", ""), replacement.get("slug", "").lower())
    if out.exists():
        for line in out.read_text().splitlines():
            queued.add(identity(json.loads(line)))
    for path in (state_path, out, log):
        path.parent.mkdir(parents=True, exist_ok=True)
    now, count, looked = datetime.now(timezone.utc), 0, 0
    with out.open("a") as queue, log.open("a") as history:
        for company in list(companies.values())[:args.limit]:
            key = f"{company.ats}:{company.slug.lower()}"
            if not valid(company):
                history.write(json.dumps({"board": key, "status": "unsupported", "checked_at": now.isoformat()}) + "\n")
                continue
            try:
                current, proposals = inspect(company, state.get(key, {}), now)
            except Exception as exc:
                current, proposals = {"status": "error", "checked_at": now.isoformat(), "error": type(exc).__name__}, []
            state[key] = current
            looked += 1
            history.write(json.dumps({"board": key, **current}) + "\n")
            history.flush()
            for row in proposals:
                if identity(row) not in queued:
                    queue.write(json.dumps(row) + "\n")
                    queue.flush()
                    queued.add(identity(row))
                    count += 1
            # Persist each observation atomically; interrupted runs retain completed work.
            temporary = state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(state))
            temporary.replace(state_path)
    print(f"checked {looked} boards; queued {count} repair/archive proposals -> {out}; live watchlists unchanged")


if __name__ == "__main__":
    main()
