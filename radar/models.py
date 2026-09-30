"""Core dataclasses shared by sources, pipeline, store and API."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Item:
    """What a Source emits: one sighting of an opportunity in one source."""
    source: str
    external_id: str
    url: str
    title: str
    company: str = ""
    location: str = ""
    text: str = ""
    published_at: datetime | None = None
    seen_at: datetime = field(default_factory=utcnow)
    raw: dict = field(default_factory=dict)

    @property
    def opportunity_id(self) -> str:
        return opportunity_id(self.url, self.company, self.title, self.location)


def opportunity_id(url: str = "", company: str = "", title: str = "", location: str = "") -> str:
    """sha256(canonical_url or company|title|location)[:20]."""
    basis = url.strip() or "|".join(part.strip().lower() for part in (company, title, location))
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:20]


@dataclass
class Opportunity:
    """A deduplicated opportunity; may be backed by many Items."""
    id: str
    title: str
    url: str = ""
    company: str = ""
    location: str = ""
    first_seen: datetime | None = None
    published_at: datetime | None = None
    score: float = 0.0
    sources: list[str] = field(default_factory=list)

    @property
    def drop_latency_s(self) -> float | None:
        """alert_time - source_published_time is computed at alert time; this is
        first_seen - published_at, the floor on how fast we could have alerted."""
        if self.first_seen and self.published_at:
            return (self.first_seen - self.published_at).total_seconds()
        return None
