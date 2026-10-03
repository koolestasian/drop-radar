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
