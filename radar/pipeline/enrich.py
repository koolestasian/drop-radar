"""enrich: regex facts (always, free), then Claude only where it still earns its tokens.

ATS and community-list items are structured already (title/company/location
set by the source itself) and never reach the LLM. Instagram items are free
text, so the LLM runs on them even when regex happened to fill every field --
it is the insider, highest-priority source (00-overview.md) and the one place
accuracy is worth the spend. Results cache by content hash in the store's
`enrichment` table, so a repeat sighting costs nothing. A hard daily token
budget degrades to "regex-only" rather than failing once spent.

ponytail: job-page facts (spec's "job-page facts (existing), then LLM") and
"page 404 -> closed" stay out of this first cut -- `fetch_job_facts` is a
network call per new link with its own cache file (ENRICHMENT_PATH), and
wiring it through the store's `enrichment` table is its own piece of work.
Add when an opportunity needs a live page check, e.g. before T7 alerts on it.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from radar.legacy import opportunity_monitor as legacy

# fields[] keys match radar.views.FIELD_COLUMNS / the legacy tracker headers,
# so enrichment here shows up in the xlsx/Sheet view, not just the DB.
CATEGORY, ROLE_TRACK, SEASON_YEAR = "Category", "Role / Track", "Season / Year"

STRUCTURED_PREFIXES = ("ats.", "github_repo.")
DEFAULT_DAILY_TOKEN_BUDGET = 200_000


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def _regex_facts(item):
    text = item.text or ""
    links = [item.url] if item.url else []
    return {
        "organization": legacy.extract_organization(text, links),
        CATEGORY: legacy.extract_category(text),
        ROLE_TRACK: legacy.extract_roles(text),
        SEASON_YEAR: legacy.extract_season(text),
        "location": legacy.extract_location(text),
        "deadline": legacy.extract_deadline(text),
    }


def _ambiguous(facts):
    return not facts.get("organization") or not facts.get("deadline")


class Enricher:
    def __init__(self, store, extractor=None, daily_token_budget=None):
        self.store = store
        self._extractor = extractor
        self.daily_token_budget = DEFAULT_DAILY_TOKEN_BUDGET if daily_token_budget is None else daily_token_budget

    def extractor(self):
        if self._extractor is None:
            self._extractor = legacy.extractor()
        return self._extractor

    def _tokens_spent_today(self):
        return (self.store.get_enrichment(f"llm_budget:{_today()}") or {}).get("tokens", 0)

    def _spend(self, tokens):
        if tokens <= 0:
            return
        key = f"llm_budget:{_today()}"
        self.store.set_enrichment(key, {"tokens": self._tokens_spent_today() + tokens})

    async def _llm_facts(self, item):
        # legacy.LLM_ENABLED (ANTHROPIC_API_KEY set) only gates the *default*
        # extractor; an injected one (tests, or a future non-Anthropic client) runs regardless.
        if not (item.text or "").strip() or (self._extractor is None and not legacy.LLM_ENABLED):
            return None
        key = f"llm:{legacy.text_key(item.text)}"
        cached = self.store.get_enrichment(key)
        if cached is not None:
            return cached
        if self._tokens_spent_today() >= self.daily_token_budget:
            return None  # budget exhausted this UTC day (kill switch): degrade to regex, retry tomorrow
        extractor = self.extractor()
        before = extractor.usage["input_tokens"] + extractor.usage["output_tokens"]
        # extract() never raises (radar/legacy/llm_extraction.py); blocking network call, so off the loop.
        facts = await asyncio.to_thread(extractor.extract, item.text, item.url, "")
        self._spend(extractor.usage["input_tokens"] + extractor.usage["output_tokens"] - before)
        if facts:  # only cache a real result; a failed/refused call should retry next sighting
            self.store.set_enrichment(key, facts)
        return facts

    async def enrich(self, opportunity_id, item):
        """Fill in blank opportunity fields from this item's text. Mutates the store."""
        if item.source.startswith(STRUCTURED_PREFIXES):
            return
        facts = _regex_facts(item)
        if _ambiguous(facts) or item.source.startswith("instagram."):
            llm = await self._llm_facts(item)
            if llm:
                facts = {
                    **facts,
                    **{k: v for k, v in (("organization", llm.get("organization")), ("deadline", llm.get("deadline")),
                                          ("location", llm.get("location")), (CATEGORY, llm.get("category")),
                                          (SEASON_YEAR, llm.get("season"))) if v},
                }
                if llm.get("roles"):
                    facts[ROLE_TRACK] = ", ".join(llm["roles"])
        self._apply(opportunity_id, facts)

    def _apply(self, opportunity_id, facts):
        opp = self.store.get_opportunity(opportunity_id)
        if opp is None:
            return
        updates = {}
        for column, value in (("company", facts.get("organization")), ("location", facts.get("location")),
                               ("deadline", facts.get("deadline"))):
            if value and not opp.get(column):
                updates[column] = value
        extra = {k: facts[k] for k in (CATEGORY, ROLE_TRACK, SEASON_YEAR) if facts.get(k)}
        if extra:
            fields = dict(opp.get("fields") or {})
            changed = {k: v for k, v in extra.items() if not fields.get(k)}
            if changed:
                fields.update(changed)
                updates["fields"] = fields
        if updates:
            self.store.save_opportunity(opportunity_id, first_seen=opp["first_seen"], **updates)
