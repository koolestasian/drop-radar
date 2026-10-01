"""Pipeline: Item -> Opportunity. Plugs in as the Scheduler's `sink` (00-overview.md).

async because enrich() may make a blocking Claude call (radar/legacy/llm_extraction.py);
Scheduler._run_one already awaits the sink when it returns an awaitable.
"""
from __future__ import annotations

import logging
from dataclasses import replace

from radar.pipeline.dedupe import resolve_opportunity_id
from radar.pipeline.enrich import Enricher
from radar.pipeline.filter import matches_profile
from radar.pipeline.normalize import canonical_company, canonical_url

log = logging.getLogger(__name__)

__all__ = ["Pipeline", "matches_profile"]


class Pipeline:
    def __init__(self, store, profile=None, enricher=None):
        self.store = store
        self.profile = profile
        self.enricher = enricher or Enricher(store)

    async def __call__(self, source, items):
        for item in items:
            await self._process(item)

    async def _process(self, item):
        if item.raw.get("closed"):
            self._close(item)
            return
        url = canonical_url(item.url)
        company = canonical_company(item.company) or item.company
        if url != item.url or company != item.company:
            item = replace(item, url=url, company=company)
        opportunity_id = resolve_opportunity_id(self.store, item, url)
        opportunity_id, _ = self.store.upsert_item(item, opportunity_id=opportunity_id)
        await self.enricher.enrich(opportunity_id, item)

    def _close(self, item):
        """T3's closed-signal contract: same (source, external_id), raw={"closed": True}."""
        opportunity_id = self.store.item_opportunity_id(item.source, item.external_id)
        if opportunity_id is None:
            return  # a close for an item this store never saw open; ignore rather than invent it
        opp = self.store.get_opportunity(opportunity_id)
        self.store.save_opportunity(opportunity_id, first_seen=opp["first_seen"], status="Closed")
        self.store.mark_seen(item.source, item.external_id, at=item.seen_at)
