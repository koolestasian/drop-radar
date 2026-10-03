"""One display format for every location: "City - Country" ("Houston - United States").

Sources write places a dozen ways ("Houston, TX", "Poland - Wroclaw", "US-TN-Tullahoma", "United States, Wisconsin,
Milwaukee", a bare "Redmond", "KUALA LUMPUR GENERAL OFFICE"). format_location() reads any of them and returns the one
shape. Several places in one country are grouped: "Reston, Plano - United States; Toronto - Canada". The stored text is
never changed (filters and search still read it); this is for display and pushes.

A country comes, in order, from the text itself, from a US state or Canadian province, or from the biggest city of that
name in radar/data/places.json (generated once from GeoNames, CC BY 4.0, cities over 40,000 people; Redmond is
Washington, Boston is Massachusetts). A city we can't place keeps just its name rather than a guessed country."""
from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

_DATA = json.loads(Path(__file__).resolve().parent.parent.joinpath("data", "places.json").read_text())
COUNTRIES: dict[str, str] = _DATA["countries"]  # ISO2 -> English name
_CITY_COUNTRY: dict[str, str] = _DATA["cities"]  # folded name -> ISO2 of its biggest city
_ISO3 = _DATA["iso3"]


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower().strip()


_ALIASES = {  # spellings sources use for a country
    "usa": "US", "u.s.": "US", "u.s.a.": "US", "us": "US", "america": "US", "united states of america": "US",
    "uk": "GB", "u.k.": "GB", "great britain": "GB", "england": "GB", "scotland": "GB", "wales": "GB",
    "northern ireland": "GB", "korea": "KR", "south korea": "KR", "republic of korea": "KR", "czech republic": "CZ",
    "russia": "RU", "uae": "AE", "vietnam": "VN", "viet nam": "VN", "turkey": "TR", "turkiye": "TR", "hong kong": "HK",
    "the netherlands": "NL", "holland": "NL", "ivory coast": "CI", "taiwan": "TW", "macau": "MO",
}
_COUNTRY_BY_NAME = {_fold(n): iso for iso, n in COUNTRIES.items()} | _ALIASES
_US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "PR": "Puerto Rico",
}
_CA_PROVINCES = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba", "NB": "New Brunswick", "NL": "Newfoundland and Labrador",
    "NS": "Nova Scotia", "ON": "Ontario", "PE": "Prince Edward Island", "QC": "Quebec", "SK": "Saskatchewan",
}
_REGION_COUNTRY = {_fold(n): "US" for n in _US_STATES.values()} | {_fold(n): "CA" for n in _CA_PROVINCES.values()}
_REGION_COUNTRY.update({"puerto rico": "US", "quebec": "CA", "new brunswick": "CA"})
_CITY_ALIASES = {"sf": "San Francisco", "nyc": "New York", "la": "Los Angeles", "dc": "Washington", "bay area": "San Francisco",
                 "washington dc": "Washington", "washington d.c": "Washington", "d.c": "Washington", "south sf": "South San Francisco"}
_CITY_COUNTRY.update({"new york": "US", "washington": "US", "san francisco": "US", "los angeles": "US", "south san francisco": "US"})
# words that say how or where inside a place, not which place: dropped when a real city is present
_NOISE = re.compile(r"\b(remote|virtual|hybrid|on-?site|anywhere|multiple locations?|nationwide|hq|headquarters|"
                    r"general offices?|regional offices?|offices?|downtown|campus|home office|center|centre|facility|plant|site)\b", re.I)
_COUNT = re.compile(r"^\s*\d+\s+locations?\b", re.I)
_ZIP = re.compile(r"^\d{4,6}(-\d{4})?$")


def _titled(city: str) -> str:
    return city.title() if city.isupper() or city.islower() else city


def _classify(token: str):
    """('country', iso) | ('region', iso) | ('zip', None) | ('city', name)"""
    t = token.strip(" .")
    f = _fold(t)
    if _ZIP.match(t):
        return "zip", None
    if f in _COUNTRY_BY_NAME:
        return "country", _COUNTRY_BY_NAME[f]
    if len(t) == 3 and t.isupper() and t in _ISO3:
        return "country", _ISO3[t]
    if f in _REGION_COUNTRY:
        return "region", _REGION_COUNTRY[f]
    if t in _US_STATES:
        return "region", "US"
    if t in _CA_PROVINCES:
        return "region", "CA"
    return "city", t


def _peel_country(token: str) -> list[str]:
    """'New York New York United States' -> ['New York New York', 'United States'] (a country spelled at the end)."""
    words = token.split()
    for n in (3, 2, 1):
        if len(words) > n and _fold(" ".join(words[-n:])) in _COUNTRY_BY_NAME and n > 1 or (
                len(words) > n and n == 1 and words[-1] in ("USA", "US", "Canada", "India", "Germany", "Singapore")):
            return [" ".join(words[:-n]), " ".join(words[-n:])]
    return [token]


def _parse_part(part: str):
    """One place -> (city or '', ISO2 or '', explicit); explicit is True when the text itself names the country
    (or a state/province), not just when a city name suggested one."""
    part = re.sub(r"\(([^)]*)\)", lambda m: ", " + m.group(1) + ", ", part).strip()
    if _fold(part).strip(" .") in _CITY_ALIASES:  # "SF", "NYC", "LA" alone are cities, not states
        part = _CITY_ALIASES[_fold(part).strip(" .")]
    m = re.match(r"^(US|USA)[- ]([A-Z]{2})[- ](.+)$", part)  # "US-TN-Tullahoma", "USA LA Bossier City"
    if m and m.group(2) in _US_STATES:
        part = f"{m.group(3)}, {m.group(2)}, US"
    m = re.match(r"^([A-Z]{2})[- ]+([A-Za-z].+)$", part)  # "TX-Dallas", "WI Madison"
    if m and (m.group(1) in _US_STATES or m.group(1) in _CA_PROVINCES) and "," not in part:
        part = f"{m.group(2)}, {m.group(1)}"
    m = re.match(r"^([A-Za-z][A-Za-z .'-]+?)\s+([A-Z]{2})$", part)  # "Atlanta GA", "Rosemont IL"
    if m and (m.group(2) in _US_STATES or m.group(2) in _CA_PROVINCES) and "," not in part:
        part = f"{m.group(1)}, {m.group(2)}"
    if "," not in part and " - " not in part and "-" in part:  # "US-California-Palo Alto", "Singapore-CapitaSky"
        pieces = part.split("-")
        if len(pieces) > 1 and _classify(pieces[0])[0] in ("country", "region"):
            part = ", ".join(pieces)
    tokens = [x for x in re.split(r",|\s+-\s+|\s+–\s+|/", part) if x.strip()]
    tokens = [t2 for t in tokens for t2 in _peel_country(t)]
    country, region_country, cities, remote = "", "", [], False
    for token in tokens:
        if re.fullmatch(r"\s*(remote|virtual|work from home|anywhere)[\w\s]*", token, re.I) and not re.search(r"\bin\b", token, re.I):
            remote = True
            continue
        if re.match(r"^\s*remote in\b", token, re.I):  # "Remote in USA"
            remote = True
            token = re.sub(r"^\s*remote in\s+", "", token, flags=re.I)
        kind, value = _classify(token)
        if kind == "country":
            country = country or value
        elif kind == "region":
            region_country = region_country or value
            if len(tokens) == 1 and len(token.strip()) > 2 and _fold(token) in _CITY_COUNTRY:  # "New York" alone is a city
                cities.append(_CITY_ALIASES.get(_fold(token), token.strip()))
        elif kind == "city":
            cleaned = _NOISE.sub(" ", token)
            cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_.")
            cleaned = _CITY_ALIASES.get(_fold(cleaned), cleaned)
            if cleaned and cleaned.lower() not in ("in", "at", "of") and not _COUNT.match(cleaned) and not _ZIP.match(cleaned):
                cities.append(cleaned)
    if not cities:  # "New York, NY", "Washington, DC": the state-named token is the city
        for token in tokens:
            if _classify(token)[0] == "region" and len(token.strip()) > 2 and _fold(token) in _CITY_COUNTRY:
                cities.append(_CITY_ALIASES.get(_fold(token), token.strip()))
                break
    explicit = bool(country or region_country)
    if not country and region_country:
        country = region_country
    if cities and country:  # several candidates ("Gerlingen, BW"): prefer the one that is a known city in that country
        known = [c for c in cities if _CITY_COUNTRY.get(_fold(c)) == country]
        city = (known or cities)[0]
    elif cities:
        known = [c for c in cities if _fold(c) in _CITY_COUNTRY]
        city = (known or cities)[0]
        country = _CITY_COUNTRY.get(_fold(city), "")
    else:
        city = "Remote" if remote else ""
        if not city and country and _fold(COUNTRIES.get(country, "")) in _CITY_COUNTRY and not region_country:
            city = COUNTRIES[country]  # a city-state: "Singapore - Singapore"
    return (_titled(city), country, explicit) if (city or country) else ("", "", False)


@lru_cache(maxsize=20000)
def format_location(raw: str) -> str:
    """'City - Country', or 'A, B - Country; C - Other' for several places. '' when nothing is placeable."""
    if not raw or not raw.strip():
        return ""
    parsed = []
    for part in re.split(r"\s*;\s*|\s+\|\s+", raw):
        if not part.strip() or _COUNT.match(part):
            continue
        city, iso, explicit = _parse_part(part.strip())
        if city or iso:
            parsed.append((city, iso, explicit))
    stated = {iso for _, iso, explicit in parsed if explicit and iso}
    context = next(iter(stated)) if len(stated) == 1 else ""
    if any(c and c != "Remote" for c, _, _ in parsed):
        parsed = [p for p in parsed if p[0] != "Remote" or not p[1]] if False else [p for p in parsed if p[0] != "Remote"]
    groups: dict[str, list[str]] = {}
    for city, iso, explicit in parsed:
        if context and not explicit:  # "New York; Bethlehem; Holmdel": the one stated country settles the others
            iso = context
        name = COUNTRIES.get(iso, "") if iso else ""
        bucket = groups.setdefault(name, [])
        if city and city not in bucket:
            bucket.append(city)
    shown = []
    for name, cities in groups.items():
        shown.append(f"{', '.join(cities)} - {name}" if cities and name else (", ".join(cities) or name))
    return "; ".join(shown)
