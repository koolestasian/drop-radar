"""dedupe: same canonical URL -> same opportunity, earliest seen_at wins.

Store.upsert_item already reuses the opportunity_id a (source, external_id)
was first stored under (radar/store/__init__.py), so a source re-seeing its
own prior sighting already converges. The gap this closes is a *different*
source seeing an *already-known* URL for the first time (ATS + community
list + Instagram all posting the same apply link) -- Store has no reason to
look that up on its own.
"""
from __future__ import annotations


def resolve_opportunity_id(store, item, canonical_url: str):
    """opportunity_id to pass to Store.upsert_item, or None to let it decide."""
    if store.item_opportunity_id(item.source, item.external_id) is not None:
        return None  # already on file; Store keeps its existing id
    if not canonical_url:
        return None  # many opportunities legitimately share url=""; never match on blank
    return store.opportunity_id_for_url(canonical_url)
