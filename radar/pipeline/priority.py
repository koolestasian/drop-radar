"""Company tiers (T16.5 part 2), rated for a CS student and never set by hand.

Jev and Claude Haiku each rate the company name. When they agree and Jev is confident, that
tier is cached; otherwise Haiku with web search decides. Each rating is cached per company in
`enrichment` (`company_tier:<name>`) and redone after REFRESH_DAYS. A company the user has
actioned ranks at least A. Any failure leaves the company unrated (B, the default) and it is
asked again on a later pass. Network work runs off-thread; SQLite stays on its owning thread."""
from __future__ import annotations

import asyncio
import logging
import os
import math
import re
from datetime import datetime, timedelta

from radar.pipeline.enrich import DEFAULT_DAILY_TOKEN_BUDGET, _today

from radar.models import utcnow
from radar.pipeline.normalize import canonical_company

log = logging.getLogger(__name__)

URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
HAIKU = "claude-haiku-4-5"
LEVELS = "CBAS"                          # Score levels 0..3, lowest first
RANK = {"S": 3, "A": 2, "B": 1, "C": 0}  # radar.api.bitindex ranks an unrated company 1 (B)
ACTIONED_RANK = RANK["A"]                # a company the user has actioned ranks up to A
TIER_INTERVAL_S = {"S": 120.0, "A": 300.0, "B": 300.0, "C": 900.0}  # ATS poll interval by tier
BATCH = 10
KEY = "company_tier:"
RATING_VERSION = 2  # CS-student rubric: big tech, frontier AI and quant belong in S
REFRESH_DAYS = 30
RETRY_KEY = "company_tier_retry:"
JEV_GATE = 0.6        # below this Jev confidence an agreeing pair still goes to the web tiebreak
PASS_SIZE = 10        # background loop: companies rated per pass...
PASS_BUDGET = 65000  # reserve before network work; refund unused tokens on the SQLite thread
PASS_PAUSE_S = 3600   # ...one pass an hour, so at most 240 a day
QUESTION = ("For a US computer science student looking for a software, ML or quant internship or new-grad job, "
            "how desirable is working at this company?")
CRITERIA = {
    "C": "Not a CS destination: staffing or recruiting agencies, IT outsourcing, non-tech companies with little "
         "software work (hospitals, utilities, local retail), or unknown tiny companies.",
    "B": "A solid employer with real engineering work but not a top target: banks, insurers, defense contractors, "
         "big retailers' tech arms, consulting, older enterprise software, ordinary startups "
         "(e.g. Lockheed Martin, Capital One, Accenture).",
    "A": "A strong target: well-known, well-paying tech companies and fast-growing AI or tech startups "
         "(e.g. Salesforce, Snowflake, Robinhood, Ramp, Perplexity, Figma).",
    "S": "Dream tier: quant trading firms and quant hedge funds of any size, frontier AI labs, big tech, and the "
         "top-paying unicorns (e.g. Jane Street, Citadel, Two Sigma, Five Rings, AQR, OpenAI, Anthropic, Google, "
         "Meta, Apple, Microsoft, Amazon, NVIDIA, Stripe, Databricks, Palantir, Scale AI).",
}
RUBRIC = "\n".join(f"{t}: {CRITERIA[t]}" for t in "SABC")
_warned = set()


def cache_key(company):
    return KEY + canonical_company(company).lower()


def _fail(who, why):
    if who not in _warned:
        _warned.add(who)
        log.warning("%s tier rating unavailable (%s); keeping current tiers", who, why)


def _post(payload, key):
    import httpx
    r = httpx.post(URL, json=payload, headers={"Authorization": f"Bearer {key}"}, timeout=60)
    r.raise_for_status()
    return r.json()


def jev_rate(names, key=None, post=None):
    """[name] -> {name: (tier, confidence)}. A missing key, a transport error or a malformed
    answer skips that batch and logs once."""
    key = key if key is not None else os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        _fail("Jev", "no TYPESAFE_API_KEY")
        return {}
    out = {}
    for i in range(0, len(names), BATCH):
        batch = {f"c{j}": name for j, name in enumerate(names[i:i + BATCH])}
        payload = {"model": MODEL, "state": batch, "questions": {
            qid: {"type": "score", "instructions": f"{QUESTION} The company is `{qid}`.",
                  "criteria": [CRITERIA[t] for t in LEVELS]} for qid in batch}}
        try:
            answers = (post or _post)(payload, key)["answers"]
        except Exception as exc:
            _fail("Jev", type(exc).__name__)
            continue
        for qid, name in batch.items():
            try:
                probs = {int(k): float(v) for k, v in answers[qid]["probabilities"].items()}
                conf = float(answers[qid]["confidence"])
                if (set(probs) != {0, 1, 2, 3} or not all(math.isfinite(v) and 0 <= v <= 1 for v in probs.values())
                        or abs(sum(probs.values()) - 1) > 0.01 or not math.isfinite(conf) or not 0 <= conf <= 1):
                    continue
                out[name] = (LEVELS[max(probs, key=lambda k: probs[k])], conf)
            except (KeyError, TypeError, ValueError):
                continue
    return out


def _ask_haiku(prompt, web):
    import anthropic
    tools = {"tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 1}]} if web else {}
    r = anthropic.Anthropic(max_retries=2, timeout=90).messages.create(
        model=HAIKU, max_tokens=1024 if web else 5, messages=[{"role": "user", "content": prompt}], **tools)
    texts = [b for b in r.content if b.type == "text"]
    urls = sorted({c.url for b in texts for c in (getattr(b, "citations", None) or [])
                   if getattr(c, "url", "").startswith("https://")})
    return "".join(b.text for b in texts), r.usage.input_tokens + r.usage.output_tokens, urls


def haiku_rate(name, web=False, ask=None):
    """One tier letter, or None on a failure or an answer that is not a tier."""
    prompt = f"{QUESTION}\nCompany: {name}\n\nTiers:\n{RUBRIC}\n\n" + (
        "Search the web for current information about this company and cite your sources. End with a final line 'TIER: X' "
        "where X is S, A, B or C." if web else "Answer with one letter only: S, A, B or C.")
    try:
        text, _, urls = (ask or _ask_haiku)(prompt, web)
        if web and not urls:
            return None
        match = re.search(r"(?:^|\n)TIER: ([SABC])\s*$", text.strip()) if web else re.fullmatch(r"[SABC]", text.strip())
        return ((match.group(1) if web else match.group()), urls) if match else None
    except Exception as exc:
        _fail("Haiku web" if web else "Haiku", type(exc).__name__)
        return None


def rate(names, key=None, post=None, ask=None, stopping=lambda: False):
    """[name] -> {name: cache value}. Agreement with a confident Jev wins; anything else goes
    to Haiku with web search. A company no model could rate is left out."""
    jev, out = jev_rate(names, key, post), {}
    for name in names:
        if stopping():
            break
        plain = haiku_rate(name, ask=ask)
        guess, (jtier, conf) = plain[0] if plain else None, jev.get(name, (None, 0.0))
        if guess and guess == jtier and conf >= JEV_GATE:
            out[name] = {"tier": guess, "source": "jev+haiku", "confidence": conf}
        elif searched := haiku_rate(name, web=True, ask=ask):
            out[name] = {"tier": searched[0], "source": "haiku+web", "sources": searched[1]}
    return out


def stale(store, names, now=None):
    """The names with no cached tier or one older than REFRESH_DAYS, never-rated first."""
    cutoff = (now or utcnow()) - timedelta(days=REFRESH_DAYS)
    todo, seen = {}, set()
    for name in (n for n in names if n):
        key = cache_key(name)
        if key in seen:
            continue
        seen.add(key)
        retry = store.get_enrichment(RETRY_KEY + key[len(KEY):])
        if retry:
            try:
                if datetime.fromisoformat(retry["after"]) > (now or utcnow()):
                    continue
            except (KeyError, TypeError, ValueError):
                pass
        cached = store.get_enrichment(key)
        try:
            fresh = cached and cached.get("v") == RATING_VERSION and cached.get("tier") in RANK and datetime.fromisoformat(cached["checked_at"]) >= cutoff
        except (KeyError, TypeError, ValueError):
            fresh = False
        if not fresh:
            todo[name] = cached is not None or retry is not None
    return sorted(todo, key=lambda name: todo[name])


class _Meter:
    """A worker-local allowance; never touch SQLite while a request is running."""
    def __init__(self, allowance, ask=None):
        self.remaining, self.ask = allowance, ask or _ask_haiku

    def __call__(self, prompt, web):
        reserve = len(prompt.encode()) + (49152 if web else 1024)
        if reserve > self.remaining:
            return "", 0, []
        self.remaining -= reserve
        text, tokens, urls = self.ask(prompt, web)
        # On transport failure keep the reservation: a timed-out request may have been billed.
        self.remaining += reserve - tokens
        return text, tokens, urls


def _reserve(store, dry_run):
    key = f"llm_budget:{_today()}"
    spent = (store.get_enrichment(key) or {}).get("tokens", 0)
    allowance = min(PASS_BUDGET, max(0, DEFAULT_DAILY_TOKEN_BUDGET - spent))
    if not dry_run:
        store.set_enrichment(key, {"tokens": spent + allowance})
    return key, allowance


def _save(store, names, rated, key, meter, dry_run):
    if dry_run:
        return
    current = (store.get_enrichment(key) or {}).get("tokens", 0)
    store.set_enrichment(key, {"tokens": max(0, current - max(0, meter.remaining))})
    for name in names:
        store.set_enrichment(RETRY_KEY + cache_key(name)[len(KEY):], {
            "after": (utcnow() + timedelta(days=1) if name not in rated else utcnow()).isoformat()})
    for name, value in rated.items():
        store.set_enrichment(cache_key(name), {**value, "model": MODEL, "haiku_model": HAIKU, "v": RATING_VERSION,
                                             "checked_at": utcnow().isoformat()})


def refresh(store, names, dry_run=False, **kw):
    """Rate names within the shared daily budget. Dry runs do not write the database."""
    names = list(names)
    key, allowance = _reserve(store, dry_run)
    meter = _Meter(allowance, kw.pop("ask", None))
    rated = rate(names, ask=meter, **kw) if allowance >= 4096 else {}
    _save(store, names if allowance >= 4096 else [], rated, key, meter, dry_run)
    return {name: value["tier"] for name, value in rated.items()}


def company_names(store, users=()):
    """Every company a tier matters for: those with postings and those on a watchlist."""
    rows = store.conn.execute("SELECT DISTINCT company FROM opportunities WHERE company != ''").fetchall()
    return [r[0] for r in rows] + [c.name for u in users for c in u.watchlist.companies]


async def run(store, users_of, stop, on_rated=None):
    """Background loop (production only): rate PASS_SIZE stale companies an hour."""
    while not stop.is_set():
        try:
            todo = stale(store, company_names(store, users_of()))[:PASS_SIZE]
            if todo:
                key, allowance = _reserve(store, False)
                meter = _Meter(allowance)
                rated = await asyncio.to_thread(rate, todo, ask=meter, stopping=stop.is_set) if allowance >= 4096 else {}
                _save(store, todo if allowance >= 4096 else [], rated, key, meter, False)
                if rated and on_rated:
                    on_rated()
        except Exception as exc:  # a bad pass must not stop the next one
            log.warning("tier pass failed: %s", type(exc).__name__)
        try:
            await asyncio.wait_for(stop.wait(), timeout=PASS_PAUSE_S)
        except asyncio.TimeoutError:
            pass


def tier_of(store, company):
    """The cached tier for a company, or None if it has not been rated."""
    cached = store.get_enrichment(cache_key(company))
    return cached.get("tier") if cached and cached.get("tier") in RANK else None


def learned_ranks(store, user_id):
    """{canonical lower company: rank} from the cached tiers and this user's actions."""
    ranks = {k[len(KEY):]: RANK[v["tier"]] for k, v in store.enrichment_with_prefix(KEY) if v.get("tier") in RANK}
    for company in store.actioned_companies(user_id):
        name = canonical_company(company).lower()
        ranks[name] = max(ranks.get(name, 0), ACTIONED_RANK)
    return ranks
