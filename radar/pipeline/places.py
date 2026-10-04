"""One display format for every location: "Seattle, WA" in the US, "Barcelona, Spain" everywhere else.

Sources write places a dozen ways ("Houston, TX", "Poland - Wroclaw", "US-TN-Tullahoma", "United States, Wisconsin,
Milwaukee", a bare "Redmond", "KUALA LUMPUR GENERAL OFFICE"). format_location() reads any of them and returns the one
shape; several places are listed in the order the source gave them: "Reston, VA; Plano, TX; Toronto, Canada". The
stored text is never changed (filters and search still read it); this is for display and pushes.

A country comes, in order, from the text itself, from a US state or Canadian province, or from the biggest city of that
name in radar/data/places.json (generated once from GeoNames, CC BY 4.0, cities over 40,000 people). A US city's state
comes from the text, else from the biggest US city of that exact name (Redmond is WA, Boston is MA); a small town with no
state anywhere keeps "United States" rather than a guessed state. A city we can't place keeps just its name."""
from __future__ import annotations

import json
import math
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

_DATA = json.loads(Path(__file__).resolve().parent.parent.joinpath("data", "places.json").read_text())
COUNTRIES: dict[str, str] = _DATA["countries"]  # ISO2 -> English name
_CITY_COUNTRY: dict[str, str] = _DATA["cities"]  # folded name -> ISO2 of its biggest city
_ISO3 = _DATA["iso3"]
_COORDS: dict[str, list] = _DATA["coords"]  # "seattle|WA" / "london|GB" -> [lat, lon]
_US_STATE: dict[str, str] = _DATA["us_state"]  # folded city name -> state abbreviation of the biggest US city of that name


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower().strip()


_ALIASES = {  # spellings sources use for a country
    "usa": "US", "u.s.": "US", "u.s.a.": "US", "us": "US", "america": "US", "united states of america": "US",
    "uk": "GB", "u.k.": "GB", "great britain": "GB", "england": "GB", "scotland": "GB", "wales": "GB",
    "northern ireland": "GB", "korea": "KR", "south korea": "KR", "republic of korea": "KR", "czech republic": "CZ",
    "russia": "RU", "uae": "AE", "vietnam": "VN", "viet nam": "VN", "turkey": "TR", "turkiye": "TR", "hong kong": "HK",
    "the netherlands": "NL", "netherlands": "NL", "ivory coast": "CI", "taiwan": "TW", "macau": "MO",
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
_STATE_ABBR = {_fold(n): a for a, n in _US_STATES.items()} | {a.lower(): a for a in _US_STATES}
_REGION_COUNTRY = {_fold(n): "US" for n in _US_STATES.values()} | {_fold(n): "CA" for n in _CA_PROVINCES.values()}
_REGION_COUNTRY.update({"puerto rico": "US", "quebec": "CA", "new brunswick": "CA"})
_CITY_ALIASES = {"sf": "San Francisco", "nyc": "New York", "la": "Los Angeles", "dc": "Washington", "bay area": "San Francisco",
                 "washington dc": "Washington", "washington d.c": "Washington", "d.c": "Washington", "south sf": "South San Francisco"}
_PART_ALIASES = {"dc": "Washington, DC", "washington dc": "Washington, DC", "washington d.c": "Washington, DC", "d.c": "Washington, DC"}
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
    if len(t) == 3 and t.isupper() and t in _ISO3 and t != "AND":  # "AND - Jacksonville, FL" is not Andorra
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


def _peel_state(token: str) -> list[str]:
    """'Danvers MA' -> ['Danvers', 'MA'] (a state abbreviation written after the city without a comma)."""
    folded = _fold(token)
    for name in sorted((n for n in _STATE_ABBR if len(n) > 2), key=len, reverse=True):  # "Chicago Illinois"
        if folded.endswith(" " + name) and len(folded) > len(name) + 1:
            return [token.strip()[: len(folded) - len(name) - 1].strip(), token.strip()[-len(name):]]
    m = re.match(r"^(.+?)\s+([A-Z]{2})$", token.strip())
    if m and (m.group(2) in _US_STATES or m.group(2) in _CA_PROVINCES) and not _fold(token) in _CITY_COUNTRY:
        return [m.group(1), m.group(2)]
    return [token]


def _parse_part(part: str):
    """One place -> (city, ISO2, explicit, US state abbreviation); explicit is True when the text itself names the
    country (or a state/province), not just when a city name suggested one."""
    part = re.sub(r"\(([^)]*)\)", lambda m: ", " + m.group(1) + ", ", part).strip()
    part = re.sub(r"[-\s]+\d+\s*$", "", part.split("~")[0].strip())  # "CEDAR RAPIDS-182 ~ 1100 Cimmie Ave" -> the place; "TORONTO 02" -> TORONTO
    key = _fold(part).strip(" .")
    if key in _PART_ALIASES or key in _CITY_ALIASES:  # "SF", "NYC", "LA", "DC" alone are cities, not states
        part = _PART_ALIASES.get(key) or _CITY_ALIASES[key]
    m = re.match(r"^(US|USA)[- ]([A-Z]{2})[- ](.+)$", part)  # "US-TN-Tullahoma", "USA LA Bossier City"
    if m and m.group(2) in _US_STATES:
        part = f"{m.group(3)}, {m.group(2)}, US"
    m = re.match(r"^([A-Z]{2})[- ]+([A-Za-z].+)$", part)  # "TX-Dallas", "WI Madison"; "DE-Berlin", "IN - Bengaluru" are countries
    if m and (m.group(1) in _US_STATES or m.group(1) in _CA_PROVINCES) and "," not in part:
        first = re.split(r"\s*-\s*", m.group(2))[0]  # "DE-Berlin", "CA-QC-Mirabel": the country with that code
        country = m.group(1) in (_CITY_COUNTRY.get(_fold(first)), _classify(first)[1]) and COUNTRIES.get(m.group(1))
        part = f"{m.group(2)}, {country or m.group(1)}"
    m = re.match(r"^([A-Za-z][A-Za-z .'-]+?)\s+([A-Z]{2})$", part)  # "Atlanta GA", "Rosemont IL"
    if m and (m.group(2) in _US_STATES or m.group(2) in _CA_PROVINCES) and "," not in part:
        part = f"{m.group(1)}, {m.group(2)}"
    if "," not in part and " - " not in part and "-" in part:  # "US-California-Palo Alto", "Singapore-CapitaSky"
        pieces = part.split("-")
        if len(pieces) > 1 and any(_classify(x)[0] in ("country", "region") for x in (pieces[0], pieces[-1])):  # "Lubbock-Texas-USA"
            part = ", ".join(pieces)
    tokens = [x for x in re.split(r",|\s+-\s+|\s+–\s+|/", part) if x.strip()]
    tokens = [t2 for t in tokens for t2 in _peel_country(t)]
    tokens = [t for t in tokens if not re.match(r"^\s*\d+\s+[A-Za-z]", t)]  # "152 Endicott Street": a street, not a place
    tokens = [t2 for t in tokens for t2 in _peel_state(t)]
    country, region_country, cities, remote, state = "", "", [], False, ""
    for token in tokens:
        if re.fullmatch(r"\s*(remote|virtual|work from home|anywhere)[\w\s]*", token, re.I) and not re.search(r"\bin\b", token, re.I):
            remote = True
            continue
        if re.match(r"^\s*remote in\b", token, re.I):  # "Remote in USA"
            remote = True
            token = re.sub(r"^\s*remote in\s+", "", token, flags=re.I)
        bare = re.sub(r"\s+", " ", _NOISE.sub(" ", token)).strip(" -_.")
        if bare and _classify(token)[0] == "city" != _classify(bare)[0]:  # "Virginia Remote Office" is the state
            token = bare
        kind, value = _classify(token)
        if kind == "region" and token.strip() in COUNTRIES and any(  # "Hyderabad, IN" is India, "Warsaw, IN" Indiana
                _CITY_COUNTRY.get(_fold(t)) == token.strip() and not has_us_namesake(t) for t in tokens):
            kind, value = "country", token.strip()
        if kind == "country":
            country = country or value
        elif kind == "region":
            region_country = region_country or value
            state = state or _STATE_ABBR.get(_fold(token.strip(" .")), "")
            if len(tokens) == 1 and len(token.strip()) > 2 and _CITY_COUNTRY.get(_fold(token)) == value:  # "New York" alone is a city
                cities.append(_CITY_ALIASES.get(_fold(token), token.strip()))
        elif kind == "city":
            cleaned = _NOISE.sub(" ", token)
            cleaned = re.sub(r"\s+", " ", cleaned).strip(" -_.")
            cleaned = _CITY_ALIASES.get(_fold(cleaned), cleaned)
            if cleaned and cleaned.lower() not in ("in", "at", "of") and not _COUNT.match(cleaned) and not _ZIP.match(cleaned):
                cities.append(cleaned)
    regions = [t.strip() for t in tokens if _classify(t)[0] == "region"]
    if not cities and len(regions) >= 2:  # "New York, NY", "Washington, DC", "New Brunswick, NJ": a state-named city, then its state
        cities.append(_CITY_ALIASES.get(_fold(regions[0]), regions[0]))
        state = _STATE_ABBR.get(_fold(regions[-1]), state)
        region_country = _classify(regions[-1])[1]
    if country == "GE" and not any(_CITY_COUNTRY.get(_fold(c)) == "GE" for c in cities):  # the US state, unless Tbilisi
        country, region_country, state = "", "US", state or "GA"
    explicit = bool(country or region_country)
    if not country and region_country:
        country = region_country
    if country != "US":
        state = ""
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
    city = _titled(city)
    if country == "US" and city and city != "Remote" and not state:
        state = _US_STATE.get(_fold(city), "")
    return (city, country, explicit, state) if (city or country or state) else ("", "", False, "")


def _show(city: str, iso: str, state: str) -> str:
    country = COUNTRIES.get(iso, "") if iso else ""
    if city == "Remote":
        return f"Remote, {country}" if country else "Remote"
    if iso == "US":
        if city:
            return f"{city}, {state}" if state else f"{city}, {country}"
        return f"{_US_STATES[state].title()}, {country}" if state in _US_STATES else country
    return f"{city}, {country}" if city and country else (city or country)


@lru_cache(maxsize=20000)
def parse_places(raw: str) -> tuple[tuple[str, str, bool, str], ...]:
    """Each place in raw as (city, ISO2, explicit, US state); explicit is True when the text names the country or a
    state/province. One stated country settles the others: "New York; Bethlehem; Holmdel"."""
    parsed = []
    for part in re.split(r"\s*;\s*|\s+\|\s+", raw or ""):
        if not part.strip() or _COUNT.match(part):
            continue
        city, iso, explicit, state = _parse_part(part.strip())
        if city or iso:
            parsed.append((city, iso, explicit, state))
    stated = {iso for _, iso, explicit, _ in parsed if explicit and iso}
    context = next(iter(stated)) if len(stated) == 1 else ""
    out = []
    for city, iso, explicit, state in parsed:
        if context and not explicit and (not iso or context == "US" and has_us_namesake(city)):
            iso = context
            if iso == "US" and city and not state:
                state = _US_STATE.get(_fold(city), "")
        out.append((city, iso, explicit, state))
    return tuple(out)


def scan_countries(text: str, cities: bool = True) -> set[str]:
    """Countries named anywhere in free text the parser can't structure ("Greater Seattle Area", "Warsaw  Poland",
    "USA > CA > Corona"): country names, US state/Canadian province names and (unless cities=False) cities, longest
    words first. A city abroad that is also a US city ("Cambridge") counts for neither."""
    words, found, i = re.findall(r"[a-z]+", _fold(text)), set(), 0
    while i < len(words):
        for n in (4, 3, 2, 1):
            g = " ".join(words[i:i + n])
            iso = _COUNTRY_BY_NAME.get(g) or _REGION_COUNTRY.get(g) or (cities and len(g) > 3 and _CITY_COUNTRY.get(g))
            if i + n <= len(words) and iso:
                if not (g in _CITY_COUNTRY and iso != "US" and g not in _COUNTRY_BY_NAME and has_us_namesake(g)):
                    found.add(iso)
                i += n
                break
        else:
            i += 1
    return found


def _coords(city: str, iso: str, state: str):
    return _COORDS.get(f"{_fold(city)}|{state if iso == 'US' else iso}") if city and iso else None


def near(raw: str, wanted: str, km: float = 50) -> bool:
    """Any place in raw within km of the place `wanted` names: "Seattle" takes in "Redmond, WA" and "Bellevue",
    "New York" takes in "Jersey City" and "Brooklyn". False when either side can't be placed."""
    # ponytail: straight-line radius around one point; per-metro shapes if 50 km proves wrong somewhere
    centers = [c for p in parse_places(wanted) if (c := _coords(p[0], p[1], p[3]))]
    if not centers:
        return False
    for city, iso, _, state in parse_places(raw):
        here = _coords(city, iso, state)
        if here and any(_km(here, c) <= km for c in centers):
            return True
    return False


def _km(a, b) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def has_us_namesake(city: str) -> bool:
    """A US city over 40,000 people has this name (Cambridge, MA; Dublin, CA), whatever the biggest one is."""
    return _fold(city) in _US_STATE


@lru_cache(maxsize=20000)
def format_location(raw: str) -> str:
    """'Seattle, WA' for a US place, 'Barcelona, Spain' for any other; '; ' between several. '' when nothing is placeable."""
    if not raw or not raw.strip():
        return ""
    parsed = parse_places(raw)
    if any(c and c != "Remote" for c, _, _, _ in parsed):
        parsed = [p for p in parsed if p[0] != "Remote"]  # how you work is a badge, not part of the place
    shown: list[str] = []
    for city, iso, _, state in parsed:
        text = _show(city, iso, state)
        if text and text not in shown:
            shown.append(text)
    return "; ".join(shown)
