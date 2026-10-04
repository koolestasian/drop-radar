"""Learned company priority (T16.5 part 2). The ladder, highest first:
an owner-set tier (never touched here) > the user's own actions > a cached Jev
tier guess > the default. Jev is asked only about companies with no owner tier
and no action history, with public data only; below the confidence gate nothing
is stored, so the current tier stands. Every failure leaves the tier as it was."""
from __future__ import annotations

import logging
import os

from radar.models import utcnow
from radar.pipeline.normalize import canonical_company

log = logging.getLogger(__name__)

URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
LEVELS = ("C", "B", "A", "S")          # Score levels 0..3, lowest first
RANK = {"S": 3, "A": 2, "B": 1, "C": 0}  # same scale as radar.api.app.TIER_RANK
ACTIONED_RANK = RANK["A"]               # a company the user has actioned ranks up to A
BATCH = 10
KEY = "company_tier:"
QUESTION = "How competitive and sought-after an early-career role at this company is"
CRITERIA = [
    "C: little demand; few applicants, easy to get",
    "B: a solid employer; a normal amount of competition",
    "A: well known and in demand; many strong applicants",
    "S: among the most sought-after employers; extremely competitive",
]
_warned = False


def cache_key(company):
    return KEY + canonical_company(company).lower()


def _post(payload, key):
    import httpx
    r = httpx.post(URL, json=payload, headers={"Authorization": f"Bearer {key}"}, timeout=30)
    r.raise_for_status()
    return r.json()


def rate(states, key=None, post=None):
    """{company: state} -> {company: (tier, confidence, model)}. Missing key, a transport
    error or a malformed answer yields {} (or skips that company) and logs once."""
    key = key if key is not None else os.environ.get("TYPESAFE_API_KEY", "").strip()
    if not key:
        return _fail("no TYPESAFE_API_KEY")
    out = {}
    names = list(states)
    for i in range(0, len(names), BATCH):
        batch = {f"c{j}": name for j, name in enumerate(names[i:i + BATCH])}
        payload = {
            "model": MODEL,
            "state": {name: states[name] for name in batch.values()},
            "questions": {qid: {"type": "score", "criteria": CRITERIA,
                                "instructions": {"company": name, "question": QUESTION + " (see `state` for its postings)"}}
                          for qid, name in batch.items()},
        }
        try:
            body = (post or _post)(payload, key)
            for qid, name in batch.items():
                answer = body["answers"][qid]
                score, confidence = float(answer["score"]), float(answer["confidence"])
                out[name] = (LEVELS[min(3, max(0, round(score)))], confidence, body["model"])
        except Exception as exc:
            _fail(f"{type(exc).__name__}: {exc}")
    return out


def _fail(why):
    global _warned
    if not _warned:
        _warned = True
        log.warning("Jev tier guess unavailable (%s); keeping current tiers", why)
    return {}


def company_state(store, company):
    """Public facts only: recent posting titles and places. Never notes, emails or actions."""
    rows = store.conn.execute(
        "SELECT title, location FROM opportunities WHERE company = ? ORDER BY first_seen DESC LIMIT 10", (company,)
    ).fetchall()
    return {"postings": [{"title": r["title"], "location": r["location"]} for r in rows]}


def learn_tiers(store, companies, gate, key=None, post=None, dry_run=False):
    """Ask about companies that have no cached guess; store those at or above `gate`.
    `companies` must already exclude owner-tiered and actioned ones. Returns {company: (tier, confidence)} stored."""
    todo = [c for c in dict.fromkeys(companies) if c and store.get_enrichment(cache_key(c)) is None]
    stored = {}
    for company, (tier, confidence, model) in rate({c: company_state(store, c) for c in todo}, key, post).items():
        if confidence < gate:
            continue
        stored[company] = (tier, confidence)
        if not dry_run:
            store.set_enrichment(cache_key(company), {"tier": tier, "source": "jev", "model": model,
                                                      "confidence": confidence, "checked_at": utcnow().isoformat()})
    return stored


def learned_ranks(store, user_id):
    """{canonical lower company: rank} from this user's actions and the cached Jev tiers.
    The caller lets owner tiers override it."""
    ranks = {k[len(KEY):]: RANK[v["tier"]] for k, v in store.enrichment_with_prefix(KEY) if v.get("tier") in RANK}
    for company in store.actioned_companies(user_id):
        name = canonical_company(company).lower()
        ranks[name] = max(ranks.get(name, 0), ACTIONED_RANK)
    return ranks


# ---- calibration (run offline with keys before `learn-tiers` is used) ------

def haiku_rate(states, ask=None):
    """The baseline for calibration: Claude Haiku picks a tier per company. It gives no
    confidence, so each answer carries 1.0. Failures skip the company."""
    out = {}
    for company, state in states.items():
        try:
            if ask is None:
                import anthropic
                r = anthropic.Anthropic(max_retries=1, timeout=20).messages.create(
                    model="claude-haiku-4-5", max_tokens=5,
                    messages=[{"role": "user", "content": (
                        f"{QUESTION}. Company: {company}. Recent postings: {state['postings']}.\n"
                        + "\n".join(CRITERIA) + "\nAnswer with one letter: C, B, A or S.")}])
                tier = r.content[0].text.strip()[:1].upper()
            else:
                tier = ask(company, state)
            if tier in RANK:
                out[company] = (tier, 1.0, "haiku")
        except Exception as exc:
            _fail(f"haiku {type(exc).__name__}: {exc}")
    return out


def agreement(labels, guesses, cutoffs=(0.0, 0.5, 0.6, 0.7, 0.8, 0.9)):
    """labels {company: tier}, guesses {company: (tier, confidence, ...)} ->
    [(cutoff, answered, exact, within_one)] counting only guesses at or above each cutoff."""
    rows = []
    for cutoff in cutoffs:
        pairs = [(RANK[labels[c]], RANK[g[0]]) for c, g in guesses.items() if c in labels and g[1] >= cutoff]
        rows.append((cutoff, len(pairs), sum(a == b for a, b in pairs), sum(abs(a - b) <= 1 for a, b in pairs)))
    return rows


def pick_gate(report, target=0.8):
    """The lowest cutoff whose within-one-tier agreement reaches `target`, or None."""
    for cutoff, answered, _exact, within in report:
        if answered and within / answered >= target:
            return cutoff
    return None
