"""Company name -> web domain, for logos.

Resolved once per name and cached in the store's `enrichment` table; the browser
then loads the domain's icon. Rungs, first verified one wins: the posting's own
JSON-LD (hiringOrganization), Wikidata's official website, Clearbit's company
autocomplete, then Claude Haiku given the posting as context (ANTHROPIC_API_KEY;
Gemini only as its fallback). A candidate is kept only when its homepage names the company in whole words, or,
for a domain a real source gave (not the LLM, which invents name-shaped domains),
when the domain is the name on a commercial ending ("Rocket Lab USA" ->
rocketlabusa.com) (a stranger's logo is worse than a monogram); an unreachable
homepage is trusted only for Clearbit's name-matched answer. Clearbit prefers a global domain over a
country one. A miss is retried after a week. Lookups run in the background,
never on a request or alert path.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

SUGGEST_URL = "https://autocomplete.clearbit.com/v1/companies/suggest"
WIKIDATA_URL = "https://query.wikidata.org/sparql"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
COMMERCIAL_TLDS = {"com", "ai", "io", "co", "net", "tech", "inc", "app", "dev", "us"}
RETRY_MISS = timedelta(days=7)
# a company's own site, never the board or social page that merely mentions it
NOT_A_COMPANY_SITE = ("linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com",
                      "github.com", "wikipedia.org", "linktr.ee", "greenhouse.io", "lever.co", "ashbyhq.com",
                      "myworkdayjobs.com", "workday.com", "smartrecruiters.com", "workable.com", "icims.com",
                      "oraclecloud.com", "bamboohr.com", "jobvite.com", "taleo.net")
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
    exact = [s for s in ok if norm(s.get("name", "")) == want or name_is_domain(name, s["domain"])]
    if exact:
        return exact[0]["domain"]
    # "Anduril" is "Anduril Industries": our name, then more whole words
    longer = [s for s in ok if re.match(rf"{re.escape(name.strip())}\s", s.get("name", ""), re.I)]
    return longer[0]["domain"] if longer else None


def registrable(url: str) -> str | None:
    """"https://www.careers.quora.com/jobs" -> "quora.com"; None for a social or job-board host."""
    host = (urlparse(url if "//" in url else "//" + url).hostname or "").lower().removeprefix("www.")
    labels = host.split(".")
    if len(labels) < 2:
        return None
    keep = 3 if len(labels) > 2 and labels[-2] in ("co", "com", "org", "ac", "gov", "edu") and len(labels[-1]) == 2 else 2
    domain = ".".join(labels[-keep:])
    return None if domain in NOT_A_COMPANY_SITE else domain


def _words(text: str) -> list[str]:
    text = re.sub(r"\(.*?\)", " ", (text or "").lower()).replace("&", " ")
    return re.findall(r"[a-z0-9]+", _SUFFIX.sub(" ", re.sub(r"['\u2019]", "", text)))


def name_on_page(name: str, text: str) -> bool:
    """The company's name appears in the page title as whole words ("ABB" is not in "AbbVie")."""
    want, words = _words(name), _words(text)
    return bool(want) and any(words[i:i + len(want)] == want for i in range(len(words)))


def name_is_domain(name: str, domain: str) -> bool:
    """rocketlabusa.com for "Rocket Lab USA"; not on .edu/.org/.gov, where a name is shared (dtcc.edu)."""
    parts = domain.lower().split(".")
    return len(parts) >= 2 and parts[-1] in COMMERCIAL_TLDS and re.sub(r"[^a-z0-9]", "", parts[-2]) == norm(name)


class LogoResolver:
    """`domain(name)` answers from the cache and queues misses; `run(stop)` drains the queue."""

    def __init__(self, store, pause_s=1.0):
        self.store, self.pause_s = store, pause_s
        self.pending: set[str] = set()
        self._wikidata_off_until = 0.0  # Wikidata answers 429 under load; skip the rung for a while
        self._llm_off_until = 0.0

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
        if cached.get("domain") is None and self._stale(cached):
            self.pending.add(name)
        return cached.get("domain")

    @staticmethod
    def _stale(cached) -> bool:
        checked = cached.get("checked_at")
        return not checked or datetime.now(timezone.utc) - datetime.fromisoformat(checked) > RETRY_MISS

    # the rungs below are blocking; resolve() runs each in a worker thread
    def _posting(self, name: str):
        """(url, title) of the company's newest posting, the context that tells "Arc" boats from "Arc" dev."""
        return self.store.conn.execute("SELECT url, title FROM opportunities WHERE company = ? AND url LIKE 'http%' "
                                       "ORDER BY first_seen DESC LIMIT 1", (name,)).fetchone()

    def _site_hint(self, name: str) -> str | None:
        from radar.pipeline import pagefacts
        row = self._posting(name)
        site = pagefacts.org_site(row[0]) if row else None
        return registrable(site) if site else None

    def _llm(self, name: str) -> str | None:
        """Claude Haiku guesses the domain from the posting; Gemini only if Haiku fails (too few calls for its quota)."""
        if time.monotonic() < self._llm_off_until:
            return None
        row = self._posting(name)
        prompt = (f"A job posting names the employer {name!r}." + (f" Posting link: {row[0]} Job title: {row[1]!r}." if row else "")
                  + " What is that employer's official website domain (registrable domain only, like 'stripe.com')? "
                    "Use null if you are not sure which company it is.")
        schema = {"type": "object", "properties": {"domain": {"type": ["string", "null"]}},
                  "required": ["domain"], "additionalProperties": False}
        for ask in (self._ask_haiku, self._ask_gemini):
            try:
                answer = ask(prompt, schema)
            except Exception as exc:
                log.warning("logo llm %s for %r failed: %s", ask.__name__, name, exc)
                continue
            if answer is not None:
                domain = answer.get("domain")
                return registrable(domain) if domain else None
        return None

    @staticmethod
    def _ask_haiku(prompt, schema):
        if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
            return None
        import anthropic
        r = anthropic.Anthropic(max_retries=1, timeout=20).messages.create(
            model=os.environ.get("LOGO_LLM_MODEL", "claude-haiku-4-5"), max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": schema}})  # Haiku 4.5 rejects `effort`
        return json.loads(next(b.text for b in r.content if b.type == "text"))

    def _ask_gemini(self, prompt, schema):
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            return None
        body = {"contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json", "responseJsonSchema": schema,
                                     "thinkingConfig": {"thinkingLevel": "low"}}}
        r = httpx.post(GEMINI_URL.format(model="gemini-3.5-flash-lite"), headers={"x-goog-api-key": key}, json=body, timeout=30)
        if r.status_code == 429:  # free-tier quota: pause the rung, the rest of the ladder keeps working
            log.warning("gemini quota hit; llm logo rung paused 10 min")
            self._llm_off_until = time.monotonic() + 600
            return None
        r.raise_for_status()
        return json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
    def _wikidata(self, name: str) -> str | None:
        if time.monotonic() < self._wikidata_off_until:
            return None
        label = name.replace("\\", " ").replace('"', " ").strip()
        query = ('SELECT ?w WHERE { ?c rdfs:label|skos:altLabel "%s"@en; wdt:P856 ?w; '
                 'wdt:P31/wdt:P279* wd:Q4830453 } LIMIT 3' % label)
        r = httpx.get(WIKIDATA_URL, params={"query": query, "format": "json"}, timeout=20,
                      headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"})
        if r.status_code == 429:
            self._wikidata_off_until = time.monotonic() + 600
            return None
        r.raise_for_status()
        for row in r.json()["results"]["bindings"]:
            if domain := registrable(row["w"]["value"]):
                return domain
        return None

    def _clearbit(self, name: str) -> str | None:
        r = httpx.get(SUGGEST_URL, params={"query": name}, headers={"User-Agent": USER_AGENT}, timeout=15)
        r.raise_for_status()
        return pick(name, r.json())

    def _title(self, domain: str) -> str | None:
        """The homepage's <title> and og:site_name, or None when it can't be read (blocked, down, robots)."""
        from radar.pipeline import pagefacts
        url = f"https://{domain}/"
        if not pagefacts._robots_allows(url):
            return None
        r = pagefacts._get(url, accept="text/html")
        if r is None or r.status_code != 200:
            return None
        page = r.content.decode("utf-8", errors="replace")
        found = re.findall(r"<title[^>]*>(.*?)</title>|property=[\"']og:site_name[\"'][^>]*content=[\"']([^\"']+)", page, re.S | re.I)
        return html.unescape(" ".join(a or b for a, b in found)) or None

    async def resolve(self, name: str) -> dict:
        """{"domain", "source", "verified"}; domain is None when no rung produced a verified answer."""
        rungs = (("posting", self._site_hint), ("wikidata", self._wikidata), ("clearbit", self._clearbit), ("llm", self._llm))
        for source, rung in rungs:
            try:
                domain = await asyncio.to_thread(rung, name)
            except Exception as exc:  # one rung down must not stop the others
                log.warning("logo rung %s for %r failed: %s", source, name, exc)
                continue
            domain = registrable(domain) if domain else None
            if not domain:
                continue
            if name_is_domain(name, domain) and source != "llm":  # a model can invent a name-shaped domain; it must show its homepage
                return {"domain": domain, "source": source, "verified": True}
            title = await asyncio.to_thread(self._title, domain)
            if title is not None and name_on_page(name, title):
                return {"domain": domain, "source": source, "verified": True}
            if title is None and source == "clearbit":  # unreadable homepage: only Clearbit's name match is trusted
                return {"domain": domain, "source": source, "verified": False}
        return {"domain": None, "source": None, "verified": False}

    async def run(self, stop: asyncio.Event):
        while not stop.is_set():
            while self.pending and not stop.is_set():
                name = self.pending.pop()
                try:
                    result = await self.resolve(name)
                except Exception as exc:  # a miss now is retried the next time the name is shown
                    log.warning("logo lookup for %r failed: %s", name, exc)
                else:
                    result["checked_at"] = datetime.now(timezone.utc).isoformat()
                    self.store.set_enrichment(f"logo:{norm(name)}", result)
                await asyncio.sleep(self.pause_s)
            try:
                await asyncio.wait_for(stop.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
