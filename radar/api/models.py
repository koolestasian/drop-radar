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
    match: Match
    action: Action | None = Field(description="this user's status/notes; nobody else's")


class Page(BaseModel):
    items: list[Opportunity]
    next_cursor: str | None


class ActionPatch(BaseModel):
    status: ActionStatus | None = None
    notes: str | None = Field(default=None, max_length=10_000)


class Me(BaseModel):
    user: str
    sources: int
