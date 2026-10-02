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

from radar.legacy import opportunity_monitor as legacy

_SUFFIX = r"(?:s|es|ing|ship|ships|ed)?"
# Fields enrichment fills from the title/caption; a post's title alone can be
# just "Applications are open!".
_MATCH_FIELDS = ("Role / Track", "Category")

_US_COUNTRY = r"united states|u\.s\.a?\.?|usa|us"
_US_STATE_NAMES = (
    "alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|hawaii|"
    "idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|michigan|"
    "minnesota|mississippi|missouri|montana|nebraska|nevada|new hampshire|new jersey|new mexico|"
    "new york|north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|"
    "south carolina|south dakota|tennessee|texas|utah|vermont|virginia|washington|west virginia|"
    "wisconsin|wyoming|district of columbia|d\\.c\\.|dc"
)
# ponytail: hubs that show up on real boards, not a gazetteer; an unlisted US city
# with no state ("Clifton Park") is "unknown", which is accepted, not rejected.
_US_CITIES = (
    "san francisco|south san francisco|sf|bay area|silicon valley|new york city|nyc|manhattan|brooklyn|"
    "seattle|bellevue|redmond|kirkland|chicago|chi|boston|cambridge, ma|austin|dallas|houston|denver|boulder|"
    "los angeles|santa monica|el segundo|long beach|irvine|san diego|san jose|palo alto|mountain view|"
    "menlo park|sunnyvale|cupertino|santa clara|redwood city|san mateo|foster city|oakland|berkeley|"
    "emeryville|arlington|mclean|reston|philadelphia|pittsburgh|atlanta|miami|raleigh|durham|charlotte|"
    "nashville|salt lake city|lehi|phoenix|scottsdale|tempe|portland|minneapolis|detroit|ann arbor|"
    "columbus|st\\. louis|kansas city|jersey city|hoboken|stamford|greenwich|princeton|baltimore|tampa|"
    "orlando|las vegas|sacramento|cleveland|cincinnati|indianapolis|new haven|plano|irving|fort worth|"
    "san antonio|omaha|boise|honolulu|cedar rapids|sea"
)
# US towns named like a foreign city in _NON_US ("Vienna, VA" is not Vienna, Austria).
_US_NAMESAKES = (
    "vienna, va|melbourne, fl|new london, ct|london, ky|london, oh|paris, tx|paris, ky|paris, tn|"
    "athens, ga|athens, oh|athens, al|athens, tn|athens, tx|dublin, oh|dublin, ca|dublin, va|dublin, ga|"
    "berlin, ct|berlin, nh|berlin, md|berlin, nj|berlin, wi|berlin, pa|warsaw, in|milan, tn|milan, mi|"
    "amsterdam, ny|geneva, il|geneva, ny|geneva, oh|hamburg, ny|hamburg, pa|cairo, il|cairo, ga|lisbon, me|"
    "ottawa, il|ottawa, ks|waterloo, ia|waterloo, ny|vancouver, wa|delhi, ny|toronto, oh"
)
_NON_US = (
    "canada|toronto|vancouver|montreal|ottawa|calgary|waterloo|kitchener|ontario|quebec|alberta|"
    "british columbia|united kingdom|uk|england|scotland|london|edinburgh|ireland|dublin|india|bengaluru|"
    "bangalore|hyderabad|pune|chennai|mumbai|delhi|gurgaon|gurugram|noida|singapore|mexico|cdmx|brazil|"
    "sao paulo|são paulo|argentina|buenos aires|colombia|bogota|romania|bucharest|spain|barcelona|madrid|"
    "germany|berlin|munich|frankfurt|hamburg|france|paris|netherlands|amsterdam|belgium|brussels|"
    "switzerland|zurich|geneva|italy|milan|poland|warsaw|krakow|czech|prague|portugal|lisbon|sweden|"
    "stockholm|denmark|copenhagen|norway|oslo|finland|helsinki|austria|vienna|serbia|belgrade|greece|"
    "athens|turkey|istanbul|israel|tel aviv|uae|dubai|abu dhabi|qatar|doha|saudi|riyadh|japan|tokyo|"
    "korea|seoul|china|beijing|shanghai|shenzhen|hong kong|taiwan|taipei|australia|sydney|melbourne|"
    "new zealand|auckland|philippines|manila|vietnam|indonesia|jakarta|malaysia|kuala lumpur|thailand|"
    "bangkok|south africa|cape town|nigeria|lagos|kenya|nairobi|egypt|cairo|emea|apac|latam|europe|ch|can|"
    "costa rica|liechtenstein"
)


def _words(alternation):
    return re.compile(rf"(?<![a-z0-9])(?:{alternation})(?![a-z0-9])", re.I)


_US_STRONG = _words(f"{_US_COUNTRY}|{_US_STATE_NAMES}|{_US_CITIES}|{_US_NAMESAKES}")
_NON_US_RE = _words(_NON_US)
_NEW_MEXICO = re.compile(r"new mexico", re.I)  # a US state whose name contains a country
_COUNTRY_RE = re.compile(
    r"canada|united kingdom|uk|england|scotland|ireland|india|singapore|mexico|brazil|argentina|colombia|"
    r"romania|spain|germany|france|netherlands|belgium|switzerland|italy|poland|czech republic|czechia|"
    r"portugal|sweden|denmark|norway|finland|austria|serbia|greece|turkey|t[uü]rkiye|israel|uae|"
    r"united arab emirates|qatar|saudi arabia|japan|south korea|korea|china|hong kong|taiwan|australia|"
    r"new zealand|philippines|vietnam|viet nam|indonesia|malaysia|thailand|south africa|nigeria|kenya|egypt|"
    r"costa rica|liechtenstein|hungary|ukraine|lithuania|latvia|estonia|bulgaria|croatia|slovakia|slovenia|"
    r"luxembourg|chile|peru|uruguay|ecuador|guatemala|panama|dominican republic|pakistan|bangladesh|sri lanka|morocco",
    re.I)
_MULTI = re.compile(r"[;|/\n]| or | and |\d+ locations", re.I)


def is_us_location(location: str) -> bool | None:
    """True if the location names somewhere in the US (any of several), False if
    it only names somewhere else, None if it says neither ("In-Office", "N/A")."""
    loc = location or ""
    # A trailing country name decides first: "Ho Chi Minh, , Vietnam" names no US place,
    # but "chi" (Chicago's abbreviation) would otherwise read as one.
    # Only for one place: "New York, NY; London, UK" is still a US job.
    last = "" if _MULTI.search(loc) or "," not in loc else _NEW_MEXICO.sub("", loc.rsplit(",", 1)[-1]).strip()
    if last and re.fullmatch(_US_COUNTRY, last, re.I):
        return True
    if last and _COUNTRY_RE.fullmatch(last):
        return False
    if _US_STRONG.search(loc):
        return True
    if _NON_US_RE.search(_NEW_MEXICO.sub("", loc)):
        return False
    # "City, ST" is weaker evidence than a name ("Toronto, ON, CA" ends in CA),
    # so it only counts once nothing non-US has shown up.
    if legacy.CITY_STATE_RE.search(loc):
        return True
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
