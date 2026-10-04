"""python -m radar <command>

  stats   drop-latency p50/p95 per source (T7)
  serve   scheduler + pipeline + API in one process, for every user in
          config/users.yaml (T8b). Binds 127.0.0.1 unless --host says
          otherwise: putting it on the internet is a deploy decision (T10).
          'run' is an alias (00-overview.md's original name for this).
  backup  copy the live SQLite db (safe while serve is running) to
          <db's dir>/backups/, keeping the most recent --keep (T10).
  reset-password <username>
          give that login a new random password, print it once, and sign
          the user out everywhere (forgotten-password help until email exists)
  fix-pages [--dry-run] [--limit N]
          read the links of postings with a blank or "N locations" place, no company or no posted date,
          and fill what the page says (never changes a value a source stated clearly)
  fix-logos [--dry-run] [--limit N]
          check every company's logo domain: replace ones whose homepage names someone else, look up misses
  fix-pay [--dry-run] [--limit N]
          read the link of every open posting that matches someone's profile and fill the pay range it states
          (one request a second per site; a posting that states none is left without pay)
  fix-stories [--dry-run]
          ask Claude for the real title of Instagram Story rows whose title is composed or OCR junk
          ("Other Opportunity · 2026"); also fills their blank company/location/deadline
  find-boards [--limit N] [--out FILE]
          ATS boards the stored apply links point at that no watchlist has, probed once each and written to a
          review file (T16 16.4); read-only: nothing is added to a watchlist or the db
  rate-tiers [--limit N] [--dry-run] [--out FILE]
          rate every company with postings or on a watchlist that has no tier or one over 30 days old, for a
          CS student (Jev + Haiku by name, Haiku with web search when they differ; T16.5). Needs TYPESAFE_API_KEY
          and ANTHROPIC_API_KEY. Writes the tiers to the db unless --dry-run, and a review file either way
  openapi print the API schema; docs/openapi.json is this output (the web
          app's types are generated from it)
"""
from __future__ import annotations

import argparse

from radar.config import load_settings
from radar.store import Store


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m radar")
    db = argparse.ArgumentParser(add_help=False)
    db.add_argument("--db", default=None, help="defaults to RADAR_DB_PATH / data/radar.db")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("stats", parents=[db], help="drop-latency p50/p95 per source")
    serve = sub.add_parser("serve", aliases=["run"], parents=[db],
                           help="run the scheduler, pipeline and API as one process")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--graceful-timeout", type=float, default=10.0,
                       help="max seconds to wait for open connections (e.g. /api/stream) on SIGTERM")
    backup = sub.add_parser("backup", parents=[db], help="back up the SQLite db to <db's dir>/backups/")
    backup.add_argument("--backup-dir", default=None, help="defaults to <db's dir>/backups")
    backup.add_argument("--keep", type=int, default=14, help="how many recent backups to keep")
    reset = sub.add_parser("reset-password", parents=[db], help="set a new random password for a username")
    reset.add_argument("username")
    fix = sub.add_parser("fix-pages", parents=[db], help="fill blank locations, companies and dates from the posting links")
    fix.add_argument("--dry-run", action="store_true", help="show what would change; write nothing")
    fix.add_argument("--limit", type=int, default=None, help="only look at this many postings")
    logos = sub.add_parser("fix-logos", parents=[db], help="check every company's logo domain; fill misses")
    logos.add_argument("--dry-run", action="store_true", help="show what would change; write nothing")
    logos.add_argument("--limit", type=int, default=None, help="only look at this many companies")
    pay = sub.add_parser("fix-pay", parents=[db], help="fill stated pay ranges from the posting links")
    pay.add_argument("--dry-run", action="store_true", help="show what would change; write nothing")
    pay.add_argument("--limit", type=int, default=None, help="only look at this many postings")
    stories = sub.add_parser("fix-stories", parents=[db], help="give Story rows with junk titles their real title")
    stories.add_argument("--dry-run", action="store_true", help="show what would change; write nothing")
    boards = sub.add_parser("find-boards", parents=[db], help="probe boards the stored links point at that nobody watches")
    boards.add_argument("--limit", type=int, default=None, help="only probe this many boards (most-linked first)")
    boards.add_argument("--out", default="data/t16/16.4-board-queue.tsv", help="review file to write")
    tiers = sub.add_parser("rate-tiers", parents=[db], help="rate companies S/A/B/C for a CS student")
    tiers.add_argument("--limit", type=int, default=None, help="only rate this many companies")
    tiers.add_argument("--dry-run", action="store_true", help="show the tiers; write nothing to the db")
    tiers.add_argument("--out", default="data/t16/16.5-tiers.tsv", help="review file to write")
    sub.add_parser("openapi", help="print the API's OpenAPI schema as JSON")
    args = parser.parse_args(argv)

    settings = load_settings()
    db_path = getattr(args, "db", None) or settings.db_path
    if args.command == "stats":
        from radar.stats import format_latency_table, latency_by_source

        with Store(db_path) as store:
            print(format_latency_table(latency_by_source(store)))
    elif args.command == "backup":
        from radar.backup import backup_once

        print(backup_once(db_path, args.backup_dir, keep=args.keep))
    elif args.command == "reset-password":
        import secrets

        from radar.api.auth import hash_password, normalize_username

        with Store(db_path) as store:
            creds = store.get_credentials(normalize_username(args.username))
            if creds is None:
                raise SystemExit(f"no login named {args.username!r}")
            new = "-".join(secrets.token_hex(3) for _ in range(4))  # 24 hex characters, easy to read out
            store.set_credentials(creds["user_id"], creds["username"], hash_password(new))
            store.delete_user_sessions(creds["user_id"])
            print(f"{creds['username']}: new password {new} (shown once; they are signed out everywhere)")
    elif args.command == "fix-pages":
        import asyncio

        from radar.pipeline.pagefacts import PageFacts, needs_facts

        async def run():
            with Store(db_path) as store:
                pages, done = PageFacts(store), {"location": 0, "company": 0, "published_at": 0, "deadline": 0}
                rows = [r["id"] for r in store.conn.execute(
                    "SELECT id FROM opportunities WHERE url != '' AND status NOT IN ('Closed', 'Expired') "
                    "ORDER BY first_seen DESC")]
                todo = []
                for opp_id in rows:
                    opp = store.get_opportunity(opp_id)
                    if needs_facts(opp):
                        todo.append(opp)
                    if args.limit is not None and len(todo) >= args.limit:
                        break
                looked = examples = fixed = 0

                async def one(opp):  # PageFacts keeps at most three pages in flight, and one request a second per host
                    changes = await pages.fill(opp["id"], dry_run=args.dry_run)
                    return opp, changes

                for finished in asyncio.as_completed([one(o) for o in todo]):
                    opp, changes = await finished
                    looked += 1
                    if changes:
                        fixed += 1
                        for k in changes:
                            done[k] += 1
                        if examples < 12:
                            examples += 1
                            print(f"  {opp['company'] or '?'}: {opp['title'][:50]!r}: " +
                                  "; ".join(f"{k} {str(opp.get(k) or '(blank)')[:30]!r} -> {str(v)[:60]!r}" for k, v in changes.items()))
                print(f"{'would fix' if args.dry_run else 'fixed'} {fixed} of {looked} postings looked at; fields: {done}")
        asyncio.run(run())
    elif args.command == "fix-logos":
        import asyncio

        from radar.logos import LogoResolver, fix_all

        with Store(db_path) as store:
            changes = asyncio.run(fix_all(store, LogoResolver(store), dry_run=args.dry_run, limit=args.limit))
        for c in sorted(changes, key=lambda c: (c["old"] is None, c["name"])):
            print(f"  {c['name'][:40]:40} {c['old'] or '(none)':30} -> {c['new'] or '(monogram)':30} {c['source'] or ''}")
        replaced = sum(1 for c in changes if c["old"])
        print(f"{'would change' if args.dry_run else 'changed'} {len(changes)}: {replaced} replaced or dropped, "
              f"{len(changes) - replaced} newly found")
    elif args.command == "fix-pay":
        import asyncio

        from radar.config import account_user, load_users
        from radar.pipeline.filter import matches_profile
        from radar.pipeline.pagefacts import PageFacts, needs_pay

        async def run():
            with Store(db_path) as store:
                profiles = [u.profile for u in (*load_users(None), *(account_user(r) for r in store.list_accounts()))]
                todo = []
                for (opp_id,) in store.conn.execute("SELECT id FROM opportunities WHERE url != '' ORDER BY first_seen DESC").fetchall():
                    opp = store.get_opportunity(opp_id)
                    if needs_pay(opp) and any(matches_profile(opp, p)[0] for p in profiles):
                        todo.append(opp)
                    if args.limit is not None and len(todo) >= args.limit:
                        break
                pages, looked, found, examples = PageFacts(store), 0, 0, 0

                async def one(opp):
                    return opp, await pages.fill(opp["id"], dry_run=args.dry_run, pay=True)

                for finished in asyncio.as_completed([one(o) for o in todo]):
                    opp, changes = await finished
                    looked += 1
                    if changes.get("pay"):
                        found += 1
                        if examples < 15:
                            examples += 1
                            print(f"  {opp['company'] or '?':24.24} {opp['title'][:48]!r:52} {changes['pay']}")
                print(f"{'would fill' if args.dry_run else 'filled'} pay on {found} of {looked} matching postings looked at")
        asyncio.run(run())
    elif args.command == "find-boards":
        import asyncio
        from pathlib import Path

        from radar.config import account_user, load_users
        from radar.sources.discover import find_boards

        with Store(db_path) as store:
            users = (*load_users(None), *(account_user(r) for r in store.list_accounts()))
            watched = {(c.ats, c.slug.lower()) for u in users for c in u.watchlist.companies}
            found = asyncio.run(find_boards(store, watched, limit=args.limit))
        ok = [r for r in found if r[4].startswith("200 OK")]
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("ats\tslug\tcompany\tstored_postings\tstatus\n" + "".join("\t".join(map(str, r)) + "\n" for r in ok))
        print(f"probed {len(found)} unwatched boards: {len(ok)} answer with open postings -> {out}; "
              f"{len(found) - len(ok)} did not (empty, unreadable or no source for that ATS)")
    elif args.command == "rate-tiers":
        from collections import Counter
        from pathlib import Path

        from radar.config import account_user, load_users
        from radar.pipeline import priority

        with Store(db_path) as store:
            users = (*load_users(None), *(account_user(r) for r in store.list_accounts()))
            todo = priority.stale(store, priority.company_names(store, users))[:args.limit]
            rated = priority.refresh(store, todo, dry_run=args.dry_run)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text("company\ttier\n" + "".join(f"{n}\t{t}\n" for n, t in sorted(rated.items())))
        print(f"{'would rate' if args.dry_run else 'rated'} {len(rated)} of {len(todo)} companies "
              f"({dict(Counter(rated.values()))}); unrated ones keep B and are retried -> {out}")
    elif args.command == "fix-stories":
        import asyncio
        import json

        from radar.models import Item
        from radar.pipeline.enrich import CATEGORY, Enricher, generic_title

        async def run():
            with Store(db_path) as store:
                enricher, fixed = Enricher(store), 0
                rows = store.conn.execute("SELECT opportunity_id, source, external_id, url, title, raw FROM items "
                                          "WHERE source LIKE 'instagram.%'").fetchall()
                for opp_id, source, external_id, url, title, raw in rows:
                    opp = store.get_opportunity(opp_id)
                    text = (json.loads(raw or "{}") or {}).get("text") or ""
                    if not opp or not text or not generic_title(opp["title"], (opp.get("fields") or {}).get(CATEGORY, "")):
                        continue
                    item = Item(source=source, external_id=external_id, url=url, title=title, text=text,
                                raw=json.loads(raw or "{}") or {})
                    if args.dry_run:  # straight to the model: no cache write either
                        from radar.pipeline.enrich import _story_image

                        image = await asyncio.to_thread(_story_image, item)
                        facts = await asyncio.to_thread(enricher.extractor().extract, text, url, "",
                                                        **({"image": image} if image else {}))
                        facts = facts or {}
                        new = facts.get("title") or ""
                        hide = (facts.get("is_opportunity") is False and (facts.get("confidence") or 0) >= 0.8
                                and "instagram.com/" in (url or "instagram.com/"))
                    else:
                        await enricher.enrich(opp_id, item)
                        after = store.get_opportunity(opp_id)
                        new, hide = after["title"], after["status"] == "Not actionable" != opp["status"]
                    if hide or (new and new != opp["title"]):
                        fixed += 1
                        print(f"  {opp['company'] or '?':22.22} {opp['title'][:45]!r:48} -> "
                              f"{'hidden: not an opportunity' if hide else repr(new[:60])}")
                print(f"{'would fix' if args.dry_run else 'fixed'} {fixed} Story titles")
        asyncio.run(run())
    elif args.command == "openapi":
        import json

        from radar.api.app import create_app

        print(json.dumps(create_app(None, tokens={}).openapi(), indent=2, sort_keys=True))
    elif args.command in ("serve", "run"):
        import logging

        import uvicorn

        from radar.api.app import create_app
        from radar.api.runtime import Runtime

        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        store = Store(db_path)  # created on the thread uvicorn runs the event loop on
        # timeout_graceful_shutdown: the PWA holds /api/stream open, so uvicorn's default
        # "wait for connections to close" would otherwise hang a SIGTERM restart indefinitely.
        from radar.pipeline.pagefacts import PageFacts

        uvicorn.run(create_app(store, Runtime(store, settings, pagefacts=PageFacts(store))), host=args.host, port=args.port,
                   timeout_graceful_shutdown=args.graceful_timeout)


if __name__ == "__main__":
    main()
