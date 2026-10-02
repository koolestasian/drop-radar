"""Shared seed-then-diff polling for ATS board-listing endpoints.

Each board is one request per poll. First poll (no stored cursor) seeds a
baseline of currently-listed, title-matching postings and emits seed Items
for the feed without alerting. Later polls diff the current id set against the stored
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

    async def fetch_postings(self, ctx):
        """(postings, complete), or None when the board is unchanged (304). One GET
        of the whole board; override for an ATS that needs several requests (Workday)."""
        data = await self._get_json(ctx, self.board_url())
        if data is None:
            return None
        try:
            parsed = self.parse(data)
        except (KeyError, TypeError, AttributeError, IndexError) as exc:
            raise SourceError(f"{self.name}: unexpected response shape: {exc}", kind="schema") from exc
        return parsed if isinstance(parsed, tuple) else (parsed, True)

    async def fetch(self, ctx) -> list[Item]:
        fetched = await self.fetch_postings(ctx)
        if fetched is None:
            return []  # 304: nothing changed since the last poll; baseline and ETag stay as they are
        raw, complete = fetched

        prior = json.loads(ctx.cursor) if ctx.cursor else None
        if not raw and prior:
            # A 200 with zero postings right after a non-empty baseline reads as a
            # glitch, not "every posting closed at once" -- never flood-close.
            raise SourceError(f"{self.name}: empty listing with a non-empty baseline", kind="transient")

        current = {eid: posting for eid, posting in raw.items() if matches_title(posting[0])}
        current_ids = set(current)

        if prior is None:
            # First poll: store what's already open, marked seed -- so a new user's feed
            # isn't empty on day one -- but the pipeline never alerts on a seed: it was
            # open before anyone was watching, so it isn't a drop.
            ctx.remember(cursor=json.dumps({eid: [url, title] for eid, (title, url, *_rest) in current.items()}))
            return [self._item(eid, current[eid], raw={"seed": True}) for eid in sorted(current_ids)]

        prior_ids = set(prior)
        items = [self._item(eid, current[eid]) for eid in sorted(current_ids - prior_ids)]
        if complete:
            for eid in sorted(prior_ids - current_ids):
                url, title = prior[eid]
                items.append(Item(
                    source=self.name, external_id=eid, url=url, title=title,
                    company=self.company.name, raw={"closed": True},
                ))
            next_ids = current_ids
        else:
            # ponytail: a partial search window can't tell a
            # closed posting from one pushed off-page, so keep the old baseline
            # around instead of guessing. Upgrade: paginate until exhausted.
            next_ids = current_ids | prior_ids
        next_baseline = {
            eid: ([current[eid][1], current[eid][0]] if eid in current else prior[eid]) for eid in next_ids
        }
        ctx.remember(cursor=json.dumps(next_baseline))
        return items

    def _item(self, eid, posting, raw=None):
        title, url, location, published_at = posting
        return Item(
            source=self.name, external_id=eid, url=url, title=title, company=self.company.name,
            location=location, published_at=published_at, raw=raw or {},
        )

    async def _get_json(self, ctx, url):
        """Conditional GET: None on a 304. Every supported ATS answers If-None-Match
        with a bodiless 304 (verified live 2026-10-02), so an unchanged board costs
        no download or parse. The ETag is sent only once a baseline exists, so a
        board can never 304 its way past seeding."""
        headers = {"If-None-Match": ctx.etag} if ctx.etag and ctx.cursor else {}
        response = await self._send(ctx.get, url, headers=headers)
        if response.status_code == 304:
            return None
        etag = response.headers.get("etag")
        if etag:
            ctx.remember(etag=etag)
        return self._json(response)

    async def _request_json(self, send, url, **kwargs):
        return self._json(await self._send(send, url, **kwargs))

    async def _send(self, send, url, **kwargs):
        try:
            return await send(url, **kwargs)
        except Exception as exc:
            raise SourceError(f"{self.name}: request failed: {exc}", kind="transient") from exc

    def _json(self, response):
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


class WindowedSource(AtsSource):
    """A career site searched newest-first, not listed whole: each poll sees only a
    window of the newest matches per query. So closed-detection stays off (a posting
    that leaves the window hasn't closed) and the baseline keeps every id it has seen,
    so a posting drifting back into view never re-alerts. Subclasses set `queries`
    and implement `search(ctx, query) -> {eid: (title, url, location, published_at)}`.
    ponytail: the baseline only grows; trim it by age if a cursor ever gets large."""
    queries = ("intern", "graduate")

    async def fetch_postings(self, ctx):
        postings = {}
        for query in self.queries:
            postings.update(await self.search(ctx, query))
        return postings, False

    async def search(self, ctx, query):
        raise NotImplementedError

    def _shape(self, fn, data):
        try:
            return fn(data)
        except (KeyError, TypeError, AttributeError, IndexError, ValueError) as exc:
            raise SourceError(f"{self.name}: unexpected response shape: {exc}", kind="schema") from exc
