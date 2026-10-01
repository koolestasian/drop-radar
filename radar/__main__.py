"""python -m radar <command>

  stats   drop-latency p50/p95 per source (T7)
  serve   scheduler + pipeline + API in one process, for every user in
          config/users.yaml (T8b). Binds 127.0.0.1 unless --host says
          otherwise: putting it on the internet is a deploy decision (T10).
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
    serve = sub.add_parser("serve", parents=[db], help="run the scheduler, pipeline and API as one process")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)

    settings = load_settings()
    db_path = args.db or settings.db_path
    if args.command == "stats":
        from radar.stats import format_latency_table, latency_by_source

        with Store(db_path) as store:
            print(format_latency_table(latency_by_source(store)))
    elif args.command == "serve":
        import logging

        import uvicorn

        from radar.api.app import create_app
        from radar.api.runtime import Runtime

        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        store = Store(db_path)  # created on the thread uvicorn runs the event loop on
        uvicorn.run(create_app(store, Runtime(store, settings)), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
