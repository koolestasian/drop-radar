"""Shared seed-then-diff polling for ATS board-listing endpoints.

Each board is one request per poll. First poll (no stored cursor) seeds a
baseline of currently-listed, title-matching postings and returns no Items
(no backlog flood). Later polls diff the current id set against the stored
baseline: new ids -> one Item each; ids that dropped off the listing -> a
closed-signal Item (same source/external_id, raw={"closed": True}) so T6 can
mark the opportunity closed.

Cursor format (JSON, persisted via ctx.remember(cursor=...)):
    {"<external_id>": [url, title], ...}   # only title-matching postings
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from radar.errors import SourceError
from radar.models import Item

TIER_INTERVAL_S = {"S": 120.0, "A": 120.0, "B": 300.0, "C": 900.0}

# Early-career terms, case-insensitive, word-ish boundaries. Runs before any
# user's profile, so it is the union of every user's industry: the spec's CS
# terms plus business/finance and university-hiring ones (a 2026-10-01 audit of
# live boards found "Summer Analyst", "Associate Consultant", "(University
# Grad)" all dropped here). Profiles do the real per-user filtering after this.
# ponytail: one hardcoded list; derive it from users' profiles if a third
# industry ever needs terms this doesn't have.
_TITLE_RE = re.compile(
    r"\b(intern(?:ship)?s?|new[- ]?grad(?:uate)?s?|early[- ](?:career|talent)|residenc(?:y|ies)|"
    r"fellowship|apprentice(?:ship)?|co-?op|202[6-9]|"
    r"summer|(?:under)?grad(?:uate)?s?|universit(?:y|ies)|campus|students?|entry[- ]level|off[- ]cycle|"
    r"rotational|trainees?|associate consultants?|"
    r"(?:analyst|associate|development|leadership) program(?:me)?s?|"
    r"spring (?:week|insight)|insight (?:days?|weeks?|programs?|series))\b",
    re.IGNORECASE,
)


def matches_title(title: str) -> bool:
    return bool(_TITLE_RE.search(title or ""))


def parse_date(value) -> datetime | None:
    """API date field (epoch seconds/ms, or an ISO-ish string) -> UTC datetime, or None."""
    if value in (None, "", 0):
        return None
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            seconds = value / 1000 if value > 10**11 else value
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, OverflowError, OSError):
        return None


class AtsSource:
    """Base for one company's board on one ATS. Subclasses implement
    `kind`, `board_url()` and `parse(data) -> dict[str, tuple[title, url, location, published_at]]`.
    `parse` may also return `(postings, complete)`; `complete=False` (e.g. a
    truncated page) suppresses closed-detection for that poll.
    """
    kind = "ats"

    def __init__(self, company):
        self.company = company
        self.name = f"ats.{self.kind}.{company.slug}"
        self.interval_s = TIER_INTERVAL_S.get(company.tier, 300.0)

    def board_url(self) -> str:
        raise NotImplementedError

    def parse(self, data):
        raise NotImplementedError

    async def fetch(self, ctx) -> list[Item]:
        data = await self._get_json(ctx, self.board_url())
        try:
            parsed = self.parse(data)
        except (KeyError, TypeError, AttributeError, IndexError) as exc:
            raise SourceError(f"{self.name}: unexpected response shape: {exc}", kind="schema") from exc
        complete = True
        if isinstance(parsed, tuple):
            raw, complete = parsed
        else:
            raw = parsed

        prior = json.loads(ctx.cursor) if ctx.cursor else None
        if not raw and prior:
            # A 200 with zero postings right after a non-empty baseline reads as a
            # glitch, not "every posting closed at once" -- never flood-close.
            raise SourceError(f"{self.name}: empty listing with a non-empty baseline", kind="transient")

        current = {eid: posting for eid, posting in raw.items() if matches_title(posting[0])}
        current_ids = set(current)

        if prior is None:
            ctx.remember(cursor=json.dumps({eid: [url, title] for eid, (title, url, *_rest) in current.items()}))
            return []

        prior_ids = set(prior)
        items = []
        for eid in sorted(current_ids - prior_ids):
            title, url, location, published_at = current[eid]
            items.append(Item(
                source=self.name, external_id=eid, url=url, title=title,
                company=self.company.name, location=location, published_at=published_at,
            ))
        if complete:
            for eid in sorted(prior_ids - current_ids):
                url, title = prior[eid]
                items.append(Item(
                    source=self.name, external_id=eid, url=url, title=title,
                    company=self.company.name, raw={"closed": True},
                ))
            next_ids = current_ids
        else:
            # ponytail: truncated page (e.g. SmartRecruiters' limit=100) can't tell a
            # closed posting from one pushed off-page, so keep the old baseline
            # around instead of guessing. Upgrade: paginate until exhausted.
            next_ids = current_ids | prior_ids
        next_baseline = {
            eid: ([current[eid][1], current[eid][0]] if eid in current else prior[eid]) for eid in next_ids
        }
        ctx.remember(cursor=json.dumps(next_baseline))
        return items

    async def _get_json(self, ctx, url):
        try:
            response = await ctx.get(url)
        except Exception as exc:
            raise SourceError(f"{self.name}: request failed: {exc}", kind="transient") from exc
        status = response.status_code
        if status == 429:
            raise SourceError(f"{self.name}: rate limited (429)", kind="blocked")
        if status >= 500:
            raise SourceError(f"{self.name}: server error {status}", kind="transient")
        if status != 200:
            raise SourceError(f"{self.name}: bad response {status}", kind="schema")
        try:
            return response.json()
        except Exception as exc:
            raise SourceError(f"{self.name}: unparseable JSON: {exc}", kind="schema") from exc
