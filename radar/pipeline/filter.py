"""filter: matches_profile(opp) -> (bool, reasons), from config/profile.yaml."""
from __future__ import annotations

import re

from radar.legacy import opportunity_monitor as legacy

_US_TOKENS = ("united states", "usa", "u.s.")


def _location_matches(location: str, wanted: str) -> bool:
    loc, wl = location.lower(), wanted.lower()
    if wl in loc:
        return True
    # "United States"/"USA" is a country, not a city/state string a posting
    # literally contains; accept any US city/state ("New York, NY") for it.
    if wl in _US_TOKENS:
        return bool(legacy.CITY_STATE_RE.search(location)) or any(t in loc for t in _US_TOKENS)
    return False


def matches_profile(opp: dict, profile) -> tuple[bool, list[str]]:
    title = str(opp.get("title") or "")
    fields = opp.get("fields") or {}

    hit = next((term for term in profile.exclude if re.search(rf"\b{re.escape(term)}\b", title, re.I)), None)
    if hit:
        return False, [f"excluded keyword matched in title: {hit!r}"]

    haystack = " ".join(str(x) for x in (title, opp.get("company"), *fields.values())).lower()
    role_terms = profile.roles + profile.keywords
    role_hit = next((term for term in role_terms if term.lower() in haystack), None)
    if role_terms and not role_hit:
        return False, ["no role keyword matched"]

    if profile.grad_year is not None:
        season = str(fields.get("Season / Year") or "")
        if season and str(profile.grad_year) not in season:
            return False, [f"grad_year {profile.grad_year} not in season {season!r}"]

    location = str(opp.get("location") or "")
    if profile.locations and location and not any(_location_matches(location, loc) for loc in profile.locations):
        return False, [f"location {location!r} not in {list(profile.locations)}"]

    reasons = [f"role keyword: {role_hit!r}"] if role_hit else []
    return True, reasons
