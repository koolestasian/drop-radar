"""API shapes. These are the OpenAPI schema the web app generates its types from."""
from typing import Literal

from pydantic import BaseModel, Field

ActionStatus = Literal["new", "saved", "applied", "interview", "offer", "rejected", "ignored"]


class Action(BaseModel):
    status: str = Field(description="this user's status; legacy imports may say 'actioned'")
    notes: str


class Match(BaseModel):
    ok: bool = Field(description="would alert this user (the same rule the phone uses)")
    reasons: list[str]


class Opportunity(BaseModel):
    id: str
    title: str
    company: str
    location: str
    url: str
    deadline: str
    status: str = Field(description="the posting itself: New, Closed, ...")
    first_seen: str
    published_at: str | None
    category: str
    role_track: str
    season: str
    sources: list[str] = Field(description="this user's sources that saw it")
    backfill: bool = Field(description="already open when your sources first looked (never alerted), not a live drop")
    match: Match
    action: Action | None = Field(description="this user's status/notes; nobody else's")
    company_domain: str | None = Field(None, description="the company's web domain, for its logo; "
                                                          "None until looked up, or when no confident match")


class Page(BaseModel):
    items: list[Opportunity]
    next_cursor: str | None


class ActionPatch(BaseModel):
    status: ActionStatus | None = None
    notes: str | None = Field(default=None, max_length=10_000)


class Me(BaseModel):
    user: str
    sources: int
    alerts_enabled: bool = Field(description="a delivery channel is configured; device receipt is not verified")
    notification_url: str | None = Field(description="this user's private ntfy subscription URL; no API token")


class InstagramRelay(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    stories: list[dict] = Field(max_length=1000)


# Config shapes mirror the YAML files; radar.config.parse_watchlist/parse_profile
# still do the real validation (allowed ATS kinds, tiers, the Instagram cap...).
class CompanyConfig(BaseModel):
    name: str
    ats: str = Field(description="greenhouse | lever | ashby | smartrecruiters | workday")
    slug: str = Field(description="board slug; workday: tenant.wdN/site")
    tier: str = Field("B", description="S | A | B | C (S/A polled every 2 min)")


class InstagramConfig(BaseModel):
    username: str
    interval_s: float = 300.0
    priority: int = 5
    user_id: str = Field("", description="numeric id; skips the throttled profile lookup")


class FeedConfig(BaseModel):
    url: str
    kind: str = "rss"


class RepoConfig(BaseModel):
    name: str = Field(description="owner/name")
    path: str = ""


class WatchlistConfig(BaseModel):
    companies: list[CompanyConfig] = []
    instagram: list[InstagramConfig] = []
    feeds: list[FeedConfig] = []
    repos: list[RepoConfig] = []


class ProfileConfig(BaseModel):
    roles: list[str] = Field([], description="the track: a title needs one of these...")
    keywords: list[str] = Field([], description="...and one of these (the level)")
    exclude: list[str] = Field([], description="any of these in the title rules it out")
    grad_year: int | None = Field(None, description="target season year, e.g. 2027")
    locations: list[str] = []
    company_tiers: dict[str, str] = {}


class SourceHealth(BaseModel):
    name: str
    disabled: bool
    running: bool
    next_run: str
    last_ok: str | None
    fail_count: int
    last_error: str | None
    items_24h: int
    stale: bool = False


class SourceLatency(BaseModel):
    source: str
    n: int
    p50: float
    p95: float


class Metrics(BaseModel):
    latency: list[SourceLatency] = Field(description="drop latency per source, your sources only")
    items_per_day: dict[str, int] = Field(description="last 7 days, items your sources saw first that day")
    llm_tokens_today: int = Field(description="shared by every user")
    llm_daily_budget: int
