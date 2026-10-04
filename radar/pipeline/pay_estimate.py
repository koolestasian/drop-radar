"""US occupation wage benchmarks for postings without employer-stated pay.

WageDex's May 2025 BLS OEWS compilation (CC BY 4.0); these survey percentiles
cover all workers in an occupation, not this company, seniority or internship.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

from radar.pipeline import places
from radar.pipeline.filter import is_us_location
from radar.pipeline.pay import make_pay, show

_DATA = json.loads(Path(__file__).resolve().parent.parent.joinpath("data", "pay_estimates.json").read_text())
_RULES = (
    (r"\b(?:software (?:engineer(?:ing)?|developer|development)|swe|backend|back end|front.?end|full.?stack|devops|site reliability|platform engineer|cloud engineer)\b", "15-1252"),
    (r"\b(?:software qa|quality assurance|software test|test automation|sdet)\b", "15-1253"),
    (r"\b(?:data scien(?:ce|tist)|machine learning engineer|ml engineer|ai engineer)\b", "15-2051"),
    (r"\b(?:cybersecurity|cyber security|information security|security (?:engineer|analyst))\b", "15-1212"),
    (r"\b(?:data analyst|business intelligence|systems analyst|analytics engineer)\b", "15-1211"),
    (r"\b(?:network engineer|systems administrator)\b", "15-1244"),
    (r"\b(?:hardware engineer|computer hardware engineer)\b", "17-2061"),
    (r"\b(?:electrical engineer|electrical engineering)\b", "17-2071"),
    (r"\b(?:mechanical engineer|mechanical engineering)\b", "17-2141"),
    (r"\b(?:industrial engineer|industrial engineering)\b", "17-2112"),
    (r"\b(?:civil engineer|civil engineering)\b", "17-2051"),
    (r"\b(?:financial analyst|investment analyst|investment banking|equity research)\b", "13-2051"),
    (r"\b(?:quantitative researcher|quant researcher|operations research)\b", "15-2031"),
    (r"\b(?:management consultant|strategy analyst|business analyst)\b", "13-1111"),
    (r"\b(?:marketing analyst|market research)\b", "13-1161"),
    (r"\b(?:accountant|accounting|tax analyst|audit analyst)\b", "13-2011"),
    (r"\b(?:web developer|web development)\b", "15-1254"),
    (r"\b(?:graphic designer|graphic design)\b", "27-1024"),
    (r"\b(?:logistics analyst|logistician|supply chain analyst)\b", "13-1081"),
    (r"\b(?:computer programmer)\b", "15-1251"),
)


@lru_cache(maxsize=20000)
def estimate_pay(title: str, location: str) -> tuple[str, str]:
    """Return (range, basis); blank where occupation or US location is uncertain."""
    if is_us_location(location) is not True:
        return "", ""
    placed = places.parse_places(location)
    if not placed or any(iso != "US" for _, iso, _, _ in placed):
        return "", ""
    for pattern, occupation in _RULES:
        if re.search(pattern, title, re.I):
            wages = _DATA["US"][occupation]
            intern = bool(re.search(r"\b(?:intern|internship|co-?op)\b", title, re.I))
            divisor, period = (2080, "hr") if intern else (1, "yr")
            pay = make_pay(wages["p10"] / divisor, wages["p25"] / divisor, "USD", period)
            if pay:
                return show(pay), f"US-wide {wages['occupation']}; BLS OEWS {_DATA['year']} 10th–25th percentiles (WageDex)"
    return "", ""
