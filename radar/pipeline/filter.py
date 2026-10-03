"""filter: matches_profile(opp, profile) -> (bool, reasons), from a user's profile.yaml.

A profile names a *track* (`roles`: "software engineer", "investment banking")
and a *level* (`keywords`: "intern", "new grad", "summer analyst"). A title
matches when it has a role AND a level -- either list may be empty, then only
the other is needed -- has no excluded word, fits the grad year's season when
one is known, and is somewhere in `locations`.

Terms match whole words, order-insensitive, allowing plural/-ing/-ship forms:
"software engineer intern" matches "Software Engineering Internship", but
"intern" never matches "International" or "Internal".
"""
from __future__ import annotations

import re
from functools import lru_cache

from radar.pipeline import places

_SUFFIX = r"(?:s|es|ing|ship|ships|ed)?"
# Fields enrichment fills from the title/caption; a post's title alone can be
# just "Applications are open!".
_MATCH_FIELDS = ("Role / Track", "Category")

_US_COUNTRY = r"united states|u\.s\.a?\.?|usa|us"
_US = {"US", "PR"}  # Puerto Rico hires like the rest of the US
_WORLD_REGION = re.compile(r"\b(emea|apac|latam|europe|asia)\b", re.I)


def is_us_location(location: str) -> bool | None:
    """True if the location names somewhere in the US (any of several), False if
    it only names somewhere else, None if it says neither ("In-Office", "N/A").

    Places come from places.py (GeoNames). A bare city whose biggest namesake is abroad
    but which is also a US city ("Cambridge", "Dublin") is unknown, not foreign; so is a
    list where one place can't be placed and the others are only guessed from a city
    name ("Poughkeepsie; Kingston": Kingston, NY is too small for the data)."""
    loc = location or ""
    placed, stated, unplaced = set(), False, False
    for city, iso, explicit, _ in places.parse_places(loc):
        if iso and not explicit and iso not in _US and places.has_us_namesake(city):
            iso = ""
        if iso:
            placed.add(iso)
            stated |= explicit
        else:
            unplaced = True
    if unplaced or not placed:  # free text the parser can't structure: look for any place name in it
        if places.scan_countries(loc) & _US:
            return True
        if not placed:  # but only a country or state name rules it out ("George Bush Airport" is in Houston)
            placed = places.scan_countries(loc, cities=False)
            unplaced = not placed
    if placed & _US:
        return True
    if placed and (stated or not unplaced) or _WORLD_REGION.search(loc):
        return False
    return None


@lru_cache(maxsize=512)
def _term_patterns(term: str):
    tokens = [t.strip(",()") for t in term.lower().split()]
    return tuple(  # "&"/"-" alone are dropped: "sales & trading" also matches "Sales and Trading"
        re.compile(rf"(?<![\w]){re.escape(t)}{_SUFFIX}(?![\w])", re.I) for t in tokens if re.search(r"\w", t)
    )


def has_term(text: str, term: str) -> bool:
    patterns = _term_patterns(term)
    return bool(patterns) and all(p.search(text) for p in patterns)


def _location_matches(location: str, wanted: str) -> bool:
    w = wanted.strip().lower()
    us = is_us_location(location)
    if re.fullmatch(_US_COUNTRY, w):
        return us is not False  # unknown is accepted: missing a real drop is worse than one extra
    if w == "remote":
        return "remote" in location.lower() and us is not False
    return w in location.lower()


def matches_profile(opp: dict, profile, level_implied: bool = False) -> tuple[bool, list[str]]:
    """`level_implied`: the item came from a list that only carries early-career
    roles (the SimplifyJobs repos), so a bare "Software Engineer 1" counts."""
    title = str(opp.get("title") or "")
    fields = opp.get("fields") or {}

    hit = next((t for t in profile.exclude if re.search(rf"\b{re.escape(t)}\b", title, re.I)), None)
    if hit:
        return False, [f"excluded keyword matched in title: {hit!r}"]

    text = " | ".join([title] + [str(fields.get(k) or "") for k in _MATCH_FIELDS])
    reasons = []
    if profile.roles:
        role = next((t for t in profile.roles if has_term(text, t)), None)
        if role is None:
            return False, ["no role matched"]
        reasons.append(f"role: {role!r}")
    if profile.keywords and not level_implied:
        level = next((t for t in profile.keywords if has_term(text, t)), None)
        if level is None:
            return False, ["no level keyword matched"]
        reasons.append(f"level: {level!r}")

    if profile.grad_year is not None:
        season = str(fields.get("Season / Year") or "")
        if season and str(profile.grad_year) not in season:
            return False, [f"grad_year {profile.grad_year} not in season {season!r}"]

    location = str(opp.get("location") or "")
    if profile.locations and location and not any(_location_matches(location, w) for w in profile.locations):
        return False, [f"location {location!r} not in {list(profile.locations)}"]
    if profile.locations and location and is_us_location(location) is None:
        reasons.append(f"location unverified: {location!r}")
    return True, reasons
