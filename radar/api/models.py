"""API shapes. These are the OpenAPI schema the web app generates its types from."""
from typing import Literal

from pydantic import BaseModel, Field

ActionStatus = Literal["new", "saved", "applied", "interview", "offer", "rejected", "ignored"]


class CareersURL(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class BoardDiscovery(BaseModel):
    name: str
    ats: str
    slug: str
    postings: int


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
    location: str = Field(description='display form: "City, ST" in the US, "City, Country" elsewhere; "; " between several')
    location_raw: str = Field("", description="the place exactly as the source wrote it")
    url: str
    deadline: str
    status: str = Field(description="the posting itself: New, Closed, ...")
    first_seen: str
    published_at: str | None
    category: str
    role_track: str
    level: str = Field("", description='"intern", "new_grad", or "" for anything else (see radar.pipeline.roles)')
    track: str = Field("Other", description="Quant, Software, Finance...; \"Other\" when no rule matches")
    season: str
    pay: str = Field("", description='the pay range the posting states, e.g. "$62–$72/hr" or "$120,000–$165,000/yr"; '
                                      'empty when it states none')
    pay_estimate: str = Field("", description="US-wide occupation wage benchmark, only when employer pay is blank")
    pay_estimate_basis: str = Field("", description="occupation, source, vintage and percentiles behind the benchmark")
    sources: list[str] = Field(description="this user's sources that saw it")
    backfill: bool = Field(description="already open when your sources first looked (never alerted), not a live drop")
    match: Match
    action: Action | None = Field(description="this user's status/notes; nobody else's")
    company_domain: str | None = Field(None, description="the company's web domain, for its logo; "
                                                          "None until looked up, or when no confident match")


class Page(BaseModel):
    items: list[Opportunity]
    next_cursor: str | None


class Counts(BaseModel):
    total: int
    level: dict[str, int] = Field(description="intern / new_grad -> how many")
    track: dict[str, int] = Field(description="track name -> how many")


class Summary(BaseModel):
    you: Counts = Field(description="what matches your profile (the For you scope)")
    everything: Counts = Field(description="everything your sources found (the Everything scope)")


class ActionPatch(BaseModel):
    status: ActionStatus | None = None
    notes: str | None = Field(default=None, max_length=10_000)


class Me(BaseModel):
    user: str
    sources: int
    alerts_enabled: bool = Field(description="a delivery channel is configured; device receipt is not verified")
    notification_url: str | None = Field(description="this user's private ntfy subscription URL; no API token")
    guest: bool = Field(False, description="true for a visitor who is not logged in: read-only, default profile")
    username: str | None = Field(None, description="the name this user signs in with, if they have set one")
    account: bool = Field(False, description="made through sign-up (kept in the database), not listed in users.yaml")


class Credentials(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class AuthResult(BaseModel):
    token: str = Field(description="send as 'Authorization: Bearer <token>'; shown once, kept only as a hash")
    me: Me


class Login(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=256)


class InstagramRelay(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    stories: list[dict] = Field(max_length=1000)


# Config shapes mirror the YAML files; radar.config.parse_watchlist/parse_profile
# still do the real validation (allowed ATS kinds, the Instagram cap...).
class CompanyConfig(BaseModel):
    name: str
    ats: str = Field(description="greenhouse | lever | ashby | smartrecruiters | workday")
    slug: str = Field(description="board slug; workday: tenant.wdN/site")


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
