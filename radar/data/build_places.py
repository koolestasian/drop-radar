"""Regenerate places.json (country names, ISO3 codes, the biggest city of each name over 40,000 people, and for
US cities the state that biggest US city is in).

    pip install geonamescache && python radar/data/build_places.py

The data is GeoNames (https://www.geonames.org), licensed CC BY 4.0, via the geonamescache package. Only the
generated file is used at runtime, so the box never loads the 16 MB source list."""
import json
import unicodedata
from pathlib import Path

import geonamescache


def fold(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower().strip()


gc = geonamescache.GeonamesCache()
best = {}
for c in gc.get_cities().values():
    if c["population"] < 40000:
        continue
    for name in {c["name"], *[a for a in c["alternatenames"] if a.isascii() and 3 <= len(a) <= 40 and not a.islower()][:6]}:
        k = fold(name)
        if k not in best or c["population"] > best[k][1]:
            best[k] = (c["countrycode"], c["population"])
us_state = {}
us_pop = {}
for c in gc.get_cities().values():  # real names only (no alternate spellings): a wrong state is worse than none
    if c["countrycode"] != "US" or c["population"] < 30000 or not c["admin1code"].isalpha():
        continue
    k = fold(c["name"])
    if c["population"] > us_pop.get(k, 0):
        us_pop[k], us_state[k] = c["population"], c["admin1code"]
coords, coord_pop = {}, {}  # "seattle|WA" / "london|GB" -> [lat, lon], so "Seattle" can take in Redmond
for c in gc.get_cities().values():
    region = c["admin1code"] if c["countrycode"] == "US" else c["countrycode"]
    for name in {c["name"], c["name"].removesuffix(" City")}:  # GeoNames calls it "New York City"
        k = f"{fold(name)}|{region}"
        if c["population"] > coord_pop.get(k, 0):
            coord_pop[k], coords[k] = c["population"], [round(c["latitude"], 2), round(c["longitude"], 2)]
out = {"us_state": us_state, "countries": {iso: c["name"] for iso, c in gc.get_countries().items()},
       "iso3": {c["iso3"]: iso for iso, c in gc.get_countries().items()},
       "cities": {k: v[0] for k, v in best.items()}, "coords": coords}
(Path(__file__).parent / "places.json").write_text(json.dumps(out, separators=(",", ":"), sort_keys=True))
