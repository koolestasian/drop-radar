"""Private career evidence. Owner approval is an assertion, not external verification.

Revisions are immutable. Answers bind exact fact revisions; changed or retired
facts make an approved answer require review before downstream reuse.
"""
import json
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator


class FactReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=64)
    revision: int = Field(ge=1)


class CareerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    kind: Literal["fact", "answer"]
    label: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=10000)
    context: str = Field(default="", max_length=2000)
    source_note: str = Field(default="", max_length=2000)
    state: Literal["draft", "approved", "retired"] = "draft"
    fact_refs: list[FactReference] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def approval_evidence(self):
        if self.kind == "fact" and self.fact_refs:
            raise ValueError("facts cannot reference other records")
        if self.state == "approved" and not self.source_note:
            raise ValueError("approval requires a source or owner confirmation note")
        if self.kind == "answer" and not self.context:
            raise ValueError("answers require context explaining where they apply")
        if len({ref.id for ref in self.fact_refs}) != len(self.fact_refs):
            raise ValueError("duplicate fact references")
        return self


class CareerRevision(CareerInput):
    expected_revision: int = Field(ge=1)


class CareerRecord(CareerInput):
    id: str
    revision: int
    created_at: str
    reusable: bool = Field(description="Current owner-approved revision with current approved supporting facts; context matching and action authorization still required")
    review_reasons: list[str]


class CareerPage(BaseModel):
    records: list[CareerRecord]
    next_after: str | None = None


def router(store, current_user, now):
    routes = APIRouter(prefix="/api/career", tags=["career"])
    conn = getattr(store, "conn", None)  # schema export constructs the app without a store

    def latest(user_id, record_id):
        return conn.execute(
            "SELECT * FROM career_records WHERE user_id=? AND id=? ORDER BY revision DESC LIMIT 1",
            (user_id, record_id),
        ).fetchone()

    def reference_errors(user_id, body):
        errors = []
        for ref in body["fact_refs"]:
            fact = latest(user_id, ref["id"])
            data = json.loads(fact["body"]) if fact is not None else {}
            if fact is None or data.get("kind") != "fact":
                errors.append(f"supporting fact {ref['id']} is unavailable")
            elif fact["revision"] != ref["revision"] or data["state"] != "approved":
                errors.append(f"supporting fact {ref['id']} changed or is not approved")
        return errors

    def serialize(user_id, row):
        body = json.loads(row["body"])
        reasons = reference_errors(user_id, body)
        current = latest(user_id, row["id"])
        if current["revision"] != row["revision"]:
            reasons.insert(0, "record is not the current revision")
        if body["state"] != "approved":
            reasons.insert(0, "record is not approved")
        return CareerRecord(**body, id=row["id"], revision=row["revision"],
                            created_at=row["created_at"], reusable=not reasons, review_reasons=reasons)

    def save(user_id, record_id, body, expected):
        data = body.model_dump(exclude={"expected_revision"})
        previous = latest(user_id, record_id)
        if expected and previous is None:
            raise HTTPException(404, "career record not found")
        if previous is not None and json.loads(previous["body"])["kind"] != data["kind"]:
            raise HTTPException(422, "record kind cannot change")
        errors = reference_errors(user_id, data)
        if errors:
            raise HTTPException(422, "; ".join(errors))
        # The revision comparison and insert are one statement, including across connections.
        with conn:
            result = conn.execute(
                """INSERT INTO career_records (user_id, id, revision, body, kind, created_at)
                   SELECT ?, ?, ?, ?, ?, ? WHERE
                   coalesce((SELECT max(revision) FROM career_records WHERE user_id=? AND id=?), 0)=?""",
                (user_id, record_id, expected + 1, json.dumps(data, ensure_ascii=False),
                 data["kind"], now().isoformat(), user_id, record_id, expected),
            )
            if result.rowcount != 1:
                raise HTTPException(409, "record changed; reload before revising")
        return serialize(user_id, latest(user_id, record_id))

    @routes.get("", response_model=CareerPage)
    async def list_records(after: str = Query(default="", max_length=64),
                           limit: int = Query(default=50, ge=1, le=100), user=Depends(current_user)):
        rows = conn.execute(
            """SELECT r.* FROM career_records r WHERE user_id=? AND id>? AND revision=(
                   SELECT max(revision) FROM career_records WHERE user_id=r.user_id AND id=r.id)
               ORDER BY id LIMIT ?""", (user.id, after, limit + 1),
        ).fetchall()
        return CareerPage(records=[serialize(user.id, r) for r in rows[:limit]],
                          next_after=rows[limit - 1]["id"] if len(rows) > limit else None)

    @routes.post("", response_model=CareerRecord, status_code=201)
    async def create_record(body: CareerInput, user=Depends(current_user)):
        return save(user.id, uuid.uuid4().hex, body, 0)

    @routes.put("/{record_id}", response_model=CareerRecord)
    async def revise_record(record_id: str, body: CareerRevision, user=Depends(current_user)):
        return save(user.id, record_id, body, body.expected_revision)

    @routes.get("/{record_id}/history", response_model=list[CareerRecord])
    async def record_history(record_id: str, before: int | None = Query(default=None, ge=1),
                             limit: int = Query(default=50, ge=1, le=100), user=Depends(current_user)):
        if latest(user.id, record_id) is None:
            raise HTTPException(404, "career record not found")
        rows = conn.execute(
            """SELECT * FROM career_records WHERE user_id=? AND id=? AND (? IS NULL OR revision<?)
               ORDER BY revision DESC LIMIT ?""", (user.id, record_id, before, before, limit),
        ).fetchall()
        return [serialize(user.id, row) for row in rows]

    return routes
