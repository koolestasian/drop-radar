"""Company name -> web domain, for logos.

Resolved once per name through Clearbit's public company autocomplete and cached
in the store's `enrichment` table; the browser then loads the domain's icon. A
domain is kept only when Clearbit's own name for it is ours (or ours plus more
words, "Anduril" -> "Anduril Industries"), preferring a global domain over a
country one, so a generic name never borrows a stranger's logo: no confident
match means the monogram stays. Lookups run in the background, never on a
request or alert path.
"""
from __future__ import annotations

import asyncio
import logging
import re

import httpx

log = logging.getLogger(__name__)

SUGGEST_URL = "https://autocomplete.clearbit.com/v1/companies/suggest"
USER_AGENT = "DropRadar/1.0 (personal job alerts)"
_SUFFIX = re.compile(r"\b(inc|llc|ltd|limited|corp|corporation|co|company|group|holdings|technologies|technology|"
                     r"the|plc|lp|llp|and)\b")
# Names Clearbit misses or gets wrong, checked by hand.
OVERRIDES = {
    "boozallen": "boozallen.com",
    "johnshopkinsappliedphysicslaboratory": "jhuapl.edu",
    "sierranevada": "sncorp.com",
    "hewlettpackard": "hp.com",
    "rivianvolkswagen": "rivianvw.tech",
    "lexisnexisrisksolutions": "lexisnexis.com",
    "bny": "bny.com",
}


def norm(name: str) -> str:
    """"The Walt Disney Company" -> "waltdisney"; parenthesized asides are dropped."""
    name = re.sub(r"\(.*?\)", " ", (name or "").lower()).replace("&", " ")
    return re.sub(r"[^a-z0-9]", "", _SUFFIX.sub(" ", name))


def _country_domain(domain: str) -> bool:
    """caci.co.uk, wellmark.co.kr, mastercard.com.au -- not io/ai/co/so-style global ones."""
    tld = domain.rsplit(".", 1)[-1]
    return bool(re.search(r"\.(co|com|org|net)\.[a-z]{2}$", domain)) or (
        len(tld) == 2 and tld not in {"io", "ai", "co", "so", "me", "us", "tv", "gg", "sh", "xyz"})


def pick(name: str, suggestions: list[dict]) -> str | None:
    want = norm(name)
    if not want:
        return None
    if want in OVERRIDES:
        return OVERRIDES[want]
    ok = [s for s in suggestions if s.get("domain") and not _country_domain(s["domain"])]
    exact = [s for s in ok if norm(s.get("name", "")) == want]
    if exact:
        return exact[0]["domain"]
    # "Anduril" is "Anduril Industries": our name, then more whole words
    longer = [s for s in ok if re.match(rf"{re.escape(name.strip())}\s", s.get("name", ""), re.I)]
    return longer[0]["domain"] if longer else None


class LogoResolver:
    """`domain(name)` answers from the cache and queues misses; `run(stop)` drains the queue."""

    def __init__(self, store, client=None, pause_s=1.0):
        self.store, self.client, self.pause_s = store, client, pause_s
        self.pending: set[str] = set()

    def domain(self, name: str) -> str | None:
        key = norm(name)
        if not key:
            return None
        if key in OVERRIDES:
            return OVERRIDES[key]
        cached = self.store.get_enrichment(f"logo:{key}")
        if cached is None:
            self.pending.add(name)
            return None
        return cached.get("domain")

    async def resolve(self, name: str) -> str | None:
        r = await self.client.get(SUGGEST_URL, params={"query": name}, headers={"User-Agent": USER_AGENT}, timeout=15)
        r.raise_for_status()
        return pick(name, r.json())

    async def run(self, stop: asyncio.Event):
        own = self.client is None
        self.client = self.client or httpx.AsyncClient()
        try:
            while not stop.is_set():
                while self.pending and not stop.is_set():
                    name = self.pending.pop()
                    try:
                        domain = await self.resolve(name)
                    except Exception as exc:  # a miss now is retried the next time the name is shown
                        log.warning("logo lookup for %r failed: %s", name, exc)
                    else:
                        self.store.set_enrichment(f"logo:{norm(name)}", {"domain": domain})
                    await asyncio.sleep(self.pause_s)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass
        finally:
            if own:
                await self.client.aclose()
