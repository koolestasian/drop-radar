"""Drop latency stats: p50/p95 per source, from alerts already sent (T7-alerts.md)."""
from __future__ import annotations

from collections import defaultdict


def _percentile(values, p):
    values = sorted(values)
    k = min(len(values) - 1, int(round((len(values) - 1) * p / 100)))
    return values[k]


def latency_by_source(store, channel=None) -> dict[str, dict]:
    """{"source": {"n", "p50", "p95"}}, sorted by source name."""
    by_source = defaultdict(list)
    for row in store.alert_latencies():
        if channel is not None and row["channel"] != channel:
            continue
        by_source[row["source"] or "(unknown)"].append(row["drop_latency_s"])
    return {
        source: {"n": len(values), "p50": _percentile(values, 50), "p95": _percentile(values, 95)}
        for source, values in sorted(by_source.items())
    }


def format_latency_table(by_source: dict[str, dict]) -> str:
    if not by_source:
        return "No alerts sent yet."
    lines = [f"{'source':<40} {'n':>5} {'p50':>8} {'p95':>8}"]
    for source, s in by_source.items():
        lines.append(f"{source:<40} {s['n']:>5} {s['p50']:>7.1f}s {s['p95']:>7.1f}s")
    return "\n".join(lines)


if __name__ == "__main__":
    assert _percentile([1, 2, 3, 4, 5], 50) == 3
    assert _percentile([1, 2, 3, 4, 5], 95) == 5
    assert _percentile([1, 2, 3], 50) == 2
    print("ok")
