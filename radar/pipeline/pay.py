"""Pay ranges, read from what a posting states and nothing else.

A pay range is {"min", "max", "currency", "period"} with period one of hr/day/wk/mo/yr, or None. Structured sources
(Lever's salaryRange, SmartRecruiters' compensation, schema.org baseSalary, Greenhouse's pay_input_ranges) are
trusted once the numbers are plausible for their period. Free text is read only for a range whose first amount has
a currency mark ("$120,000 - $150,000", "$45 to $60 per hour", "USD 62-72/hr"), whose period is stated or obvious
from its size, and which isn't a bonus, a stipend of something else or a company figure ("raised $50 - $100 million").
A posting that lists several ranges (one per region) shows the widest one. Never a guess: no range, no pay.
ponytail: amounts are not converted between currencies or periods; sort by pay would need that."""
from __future__ import annotations

import html
import re

PERIODS = {"hr": (7, 1_000), "day": (50, 5_000), "wk": (300, 30_000), "mo": (1_000, 150_000), "yr": (15_000, 2_000_000)}
SYMBOLS = {"USD": "$", "GBP": "£", "EUR": "€", "CAD": "CA$", "AUD": "A$"}
_MARKS = {"$": "USD", "£": "GBP", "€": "EUR", "USD": "USD", "GBP": "GBP", "EUR": "EUR", "CAD": "CAD", "AUD": "AUD"}
_AMOUNT = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?\s?[kK]?"
_RANGE = re.compile(
    rf"(?P<mark>\$|£|€|USD|GBP|EUR|CAD|AUD)\s?(?P<lo>{_AMOUNT})\s*(?:-|–|—|−|to|and)\s*(?:\$|£|€|USD|GBP|EUR|CAD|AUD)?\s?(?P<hi>{_AMOUNT})",
    re.I)
_AFTER_NOT_PAY = re.compile(r"^\s*(?:m\b|mm\b|b\b|million|billion|bn\b|[^.]{0,25}\b(?:bonus|stipend|relocation|signing|sign-on|equity|funding|"
                            r"raised|revenue|valuation|gift|scholarship|tuition|reimburse|match|reward)\w*)", re.I)
_BEFORE_NOT_PAY = re.compile(r"(?:bonus|stipend|relocation|signing|sign-on|equity|raised|raise|funding|revenue|valuation|"
                             r"tuition|reimburse|match(?:ing)?|up to a)\W[^.]{0,30}$", re.I)
_WORDS = (("hr", re.compile(r"\b(?:per hour|an hour|hourly|/\s?hr|/\s?hour|per hr|hr\b)", re.I)),
          ("yr", re.compile(r"\b(?:per year|a year|annual(?:ly)?|/\s?yr|/\s?year|per annum|yearly|salary|base pay|base salary)", re.I)),
          ("mo", re.compile(r"\b(?:per month|a month|monthly|/\s?mo\b|/\s?month)", re.I)),
          ("wk", re.compile(r"\b(?:per week|a week|weekly|/\s?wk|/\s?week)", re.I)),
          ("day", re.compile(r"\b(?:per day|a day|daily|/\s?day)", re.I)))


def _number(text: str) -> float:
    text = text.replace(",", "").strip()
    scale = 1000 if text[-1:] in "kK" else 1
    return float(text.rstrip("kK").strip()) * scale


def make_pay(lo, hi, currency="USD", period="") -> dict | None:
    """A validated pay range, or None. period "" means unstated: only a yearly-sized amount is believed then."""
    try:
        lo, hi = float(lo), float(hi)
    except (TypeError, ValueError):
        return None
    if not 0 < lo <= hi:
        return None
    if period not in PERIODS:
        period = "yr" if PERIODS["yr"][0] <= lo and hi <= PERIODS["yr"][1] else ""
    if not period or not (PERIODS[period][0] <= lo and hi <= PERIODS[period][1]):
        return None
    if hi > lo * 4 and period in ("hr", "day", "wk", "mo"):  # "$15 - $90 per hour" is two figures, not a range
        return None
    return {"min": round(lo, 2), "max": round(hi, 2), "currency": (currency or "USD").upper(), "period": period}


def period_of(word) -> str:
    """Structured sources name periods many ways ("per-year-salary", "HOUR", "HOURLY", "Annual")."""
    w = (word or "").lower()
    for key, names in (("hr", ("hour",)), ("day", ("day", "daily")), ("wk", ("week",)),
                       ("mo", ("month",)), ("yr", ("year", "annual"))):
        if any(n in w for n in names):
            return key
    return ""


def show(pay: dict | None) -> str:
    """"$62–$72/hr", "$120,000–$165,000/yr", "£30,000–£40,000/yr"; "" for no pay."""
    if not pay:
        return ""
    symbol = SYMBOLS.get(pay["currency"], pay["currency"] + " ")

    def amount(x):
        return f"{symbol}{x:,.0f}" if float(x).is_integer() else f"{symbol}{x:,.2f}"
    lo, hi = amount(pay["min"]), amount(pay["max"])
    return f"{lo}/{pay['period']}" if lo == hi else f"{lo}–{hi}/{pay['period']}"


def clean(text) -> str:
    """HTML (often escaped twice, as in Greenhouse's `content`) to plain text."""
    text = html.unescape(html.unescape(str(text or "")))
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def pay_from_text(text) -> dict | None:
    text = clean(text)
    found = []
    for m in _RANGE.finditer(text):
        before, after = text[max(0, m.start() - 60):m.start()], text[m.end():m.end() + 60]
        if _AFTER_NOT_PAY.match(after) or _BEFORE_NOT_PAY.search(before):
            continue
        period = ""
        for key, pattern in _WORDS:  # the word right after the range wins over one further away
            if pattern.search(after[:40]):
                period = key
                break
        else:
            for key, pattern in _WORDS:
                if pattern.search(before[-50:]):
                    period = key
                    break
        pay = make_pay(_number(m.group("lo")), _number(m.group("hi")), _MARKS[m.group("mark").upper()], period)
        if pay:
            found.append(pay)
    if not found:
        return None
    first = found[0]
    same = [p for p in found if p["period"] == first["period"] and p["currency"] == first["currency"]]
    return {**first, "min": min(p["min"] for p in same), "max": max(p["max"] for p in same)}


def pay_from_json_ld(posting) -> dict | None:
    """schema.org baseSalary: MonetaryAmount with a QuantitativeValue (minValue/maxValue/value, unitText)."""
    salary = posting.get("baseSalary") if isinstance(posting, dict) else None
    if not isinstance(salary, dict):
        return None
    value = salary.get("value")
    value = value if isinstance(value, dict) else {"value": value}
    lo = value.get("minValue", value.get("value"))
    hi = value.get("maxValue", value.get("value"))
    return make_pay(lo, hi if hi not in (None, "") else lo, salary.get("currency") or "USD", period_of(value.get("unitText")))
