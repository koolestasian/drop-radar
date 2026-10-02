"""python -m radar <command>

  stats   drop-latency p50/p95 per source (T7)
  serve   scheduler + pipeline + API in one process, for every user in
          config/users.yaml (T8b). Binds 127.0.0.1 unless --host says
          otherwise: putting it on the internet is a deploy decision (T10).
          'run' is an alias (00-overview.md's original name for this).
  backup  copy the live SQLite db (safe while serve is running) to
          <db's dir>/backups/, keeping the most recent --keep (T10).
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
        uvicorn.run(create_app(store, Runtime(store, settings)), host=args.host, port=args.port,
                   timeout_graceful_shutdown=args.graceful_timeout)


if __name__ == "__main__":
    main()
