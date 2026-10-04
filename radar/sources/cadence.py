"""Adaptive polling (T16.5 part 1): poll a board faster in the UTC hours it
tends to post in and slower outside them. Plain counts, no model."""
from __future__ import annotations

from collections import Counter

MIN_POSTINGS = 10      # fewer first-seen times than this: keep the tier interval
HOT_SHARE = 1.5        # an hour is active when it holds >= 1.5x an even share (1/24) of postings
HOT_FACTOR = 0.5       # active hours poll at half the tier interval...
QUIET_FACTOR = 3.0     # ...quiet hours at three times it
MIN_INTERVAL_S = 60.0
MAX_INTERVAL_S = 1800.0


def active_hours(seen_times) -> frozenset[int] | None:
    """UTC hours that hold a high share of these first-seen datetimes, or None
    when there is too little history to say."""
    hours = Counter(t.hour for t in seen_times)
    total = sum(hours.values())
    if total < MIN_POSTINGS:
        return None
    return frozenset(h for h, n in hours.items() if n / total >= HOT_SHARE / 24)


def interval_for(base_s: float, hours: frozenset[int] | None, now) -> float:
    """The tier interval `base_s`, scaled by whether `now`'s UTC hour is active."""
    if not hours:
        return base_s
    factor = HOT_FACTOR if now.hour in hours else QUIET_FACTOR
    return min(MAX_INTERVAL_S, max(MIN_INTERVAL_S, base_s * factor))
