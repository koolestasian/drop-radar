"""python -m radar stats: drop-latency p50/p95 per source (T7-alerts.md).

The run/deploy entrypoint (`python -m radar run`) is T10; this is the one
command T7 needs ahead of it.
"""
from __future__ import annotations

import argparse

from radar.config import load_settings
from radar.stats import format_latency_table, latency_by_source
from radar.store import Store


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m radar")
    sub = parser.add_subparsers(dest="command", required=True)
    stats = sub.add_parser("stats", help="drop-latency p50/p95 per source")
    stats.add_argument("--db", default=None, help="defaults to RADAR_DB_PATH / data/radar.db")
    args = parser.parse_args(argv)

    db_path = args.db or load_settings().db_path
    with Store(db_path) as store:
        print(format_latency_table(latency_by_source(store)))


if __name__ == "__main__":
    main()
