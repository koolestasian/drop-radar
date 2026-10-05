import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx

from radar.api.app import create_app
from radar.config import Profile, User, Watchlist
from radar.models import Item
from radar.store import MIGRATIONS, SCHEMA, Store


NOW = datetime(2026, 10, 4, tzinfo=timezone.utc)
FACT = {"kind": "fact", "label": "Project contribution", "text": "Built a guarded job reader."}


class CareerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "radar.db"
        self.store = Store(self.path)
        self.addCleanup(self.store.close)
        runtime = SimpleNamespace(users={uid: User(id=uid, watchlist=Watchlist(), profile=Profile())
                                         for uid in ("owner", "friend")}, owned={})
        app = create_app(self.store, runtime, tokens={"o" * 24: "owner", "f" * 24: "friend"}, now=lambda: NOW)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.addAsyncCleanup(self.client.aclose)
        self.auth = {"Authorization": "Bearer " + "o" * 24}
        self.friend = {"Authorization": "Bearer " + "f" * 24}

    async def create(self, body=None):
        response = await self.client.post("/api/career", json=body or FACT, headers=self.auth)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    async def revise(self, record, **changes):
        body = {k: record[k] for k in FACT}
        body.update({k: record[k] for k in ("context", "source_note", "state", "fact_refs")})
        body.update(expected_revision=record["revision"], **changes)
        return await self.client.put("/api/career/" + record["id"], json=body, headers=self.auth)

    async def test_drafts_require_explicit_approval_and_provenance(self):
        record = await self.create()
        self.assertFalse(record["reusable"])
        response = await self.revise(record, state="approved")
        self.assertEqual(response.status_code, 422)
        response = await self.revise(record, state="approved", source_note="Owner confirmed repository contribution")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["reusable"])
        self.assertEqual(response.json()["revision"], 2)

    async def test_changed_fact_invalidates_answer_until_reapproved_with_current_evidence(self):
        fact = await self.create({**FACT, "state": "approved", "source_note": "Owner confirmed"})
        answer = await self.create({"kind": "answer", "label": "Describe a project", "text": "I built the reader.",
                                    "context": "Questions about my own project contribution",
                                    "state": "approved", "source_note": "Owner reviewed answer",
                                    "fact_refs": [{"id": fact["id"], "revision": 1}]})
        self.assertTrue(answer["reusable"])
        changed = await self.revise(fact, text="Built and maintained the guarded reader.")
        self.assertEqual(changed.status_code, 200)
        records = (await self.client.get("/api/career", headers=self.auth)).json()["records"]
        stale = next(r for r in records if r["id"] == answer["id"])
        self.assertFalse(stale["reusable"])
        self.assertIn("changed", stale["review_reasons"][0])
        rejected = await self.revise(answer)
        self.assertEqual(rejected.status_code, 422)
        updated = await self.revise(answer, fact_refs=[{"id": fact["id"], "revision": 2}])
        self.assertTrue(updated.json()["reusable"])

    async def test_retirement_invalidates_answers_and_keeps_history(self):
        fact = await self.create({**FACT, "state": "approved", "source_note": "Owner confirmed"})
        answer = await self.create({"kind": "answer", "label": "Project", "text": "My contribution",
                                    "context": "Project questions", "state": "approved", "source_note": "Reviewed",
                                    "fact_refs": [{"id": fact["id"], "revision": 1}]})
        self.assertEqual((await self.revise(fact, state="retired")).status_code, 200)
        history = (await self.client.get(f"/api/career/{answer['id']}/history", headers=self.auth)).json()
        self.assertFalse(history[0]["reusable"])
        fact_history = (await self.client.get(f"/api/career/{fact['id']}/history", headers=self.auth)).json()
        self.assertEqual([r["state"] for r in fact_history], ["retired", "approved"])
        self.assertFalse(fact_history[1]["reusable"])

    async def test_stale_edit_cannot_overwrite_current_revision(self):
        record = await self.create()
        self.assertEqual((await self.revise(record, text="First edit")).status_code, 200)
        self.assertEqual((await self.revise(record, text="Stale edit")).status_code, 409)
        history = (await self.client.get(f"/api/career/{record['id']}/history", headers=self.auth)).json()
        self.assertEqual([r["text"] for r in history], ["First edit", FACT["text"]])

    async def test_cross_user_reads_writes_and_references_do_not_leak(self):
        record = await self.create({**FACT, "state": "approved", "source_note": "Owner confirmed"})
        self.assertEqual((await self.client.get("/api/career", headers=self.friend)).json()["records"], [])
        self.assertEqual((await self.client.get(f"/api/career/{record['id']}/history",
                                              headers=self.friend)).status_code, 404)
        response = await self.client.put(f"/api/career/{record['id']}",
                                         json={**FACT, "expected_revision": 1}, headers=self.friend)
        self.assertEqual(response.status_code, 404)
        response = await self.client.post("/api/career", headers=self.friend, json={
            "kind": "answer", "label": "Question", "text": "Answer", "context": "Context",
            "fact_refs": [{"id": record["id"], "revision": 1}]})
        self.assertEqual(response.status_code, 422)
        self.assertIn("unavailable", response.text)

    async def test_all_routes_require_authentication(self):
        for method, path, body in (("GET", "/api/career", None), ("POST", "/api/career", FACT),
                                   ("PUT", "/api/career/unknown", {**FACT, "expected_revision": 1}),
                                   ("GET", "/api/career/unknown/history", None)):
            response = await self.client.request(method, path, json=body)
            self.assertEqual(response.status_code, 401)

    async def test_validation_prevents_ambiguous_reuse_and_injected_ownership(self):
        for body in ({**FACT, "label": "  "}, {**FACT, "user_id": "friend"},
                     {**FACT, "kind": "answer"}, {**FACT, "state": "verified"},
                     {**FACT, "text": "x" * 10001},
                     {**FACT, "fact_refs": [{"id": "another", "revision": 1}]}):
            response = await self.client.post("/api/career", json=body, headers=self.auth)
            self.assertEqual(response.status_code, 422, body)

    async def test_answer_cannot_use_unapproved_or_answer_record_as_evidence(self):
        draft = await self.create()
        answer = await self.create({"kind": "answer", "label": "Question", "text": "Answer", "context": "Context"})
        for ref in (draft, answer):
            response = await self.client.post("/api/career", headers=self.auth, json={
                "kind": "answer", "label": "Question", "text": "Answer", "context": "Context",
                "fact_refs": [{"id": ref["id"], "revision": 1}]})
            self.assertEqual(response.status_code, 422)

    async def test_list_and_history_paginate_without_losing_revisions(self):
        record = await self.create()
        other = await self.create({**FACT, "label": "Other"})
        page = (await self.client.get("/api/career?limit=1", headers=self.auth)).json()
        second = (await self.client.get("/api/career", params={"limit": 1, "after": page["next_after"]},
                                        headers=self.auth)).json()
        self.assertEqual({r["id"] for r in page["records"] + second["records"]}, {record["id"], other["id"]})
        self.assertIsNone(second["next_after"])
        edited = (await self.revise(record, text="Revision two")).json()
        await self.revise(edited, text="Revision three")
        history = (await self.client.get(f"/api/career/{record['id']}/history?limit=1&before=3",
                                         headers=self.auth)).json()
        self.assertEqual(history[0]["revision"], 2)

    async def test_reopening_store_keeps_private_history_and_existing_job_data(self):
        self.store.upsert_item(Item(source="test", external_id="job", url="https://example.org/job",
                                    title="Intern", seen_at=NOW))
        before = {table: [tuple(row) for row in self.store.conn.execute(f"SELECT * FROM {table}")]
                  for table in ("opportunities", "items", "actions", "alerts")}
        record = await self.create()
        with Store(self.path) as reopened:
            body = reopened.conn.execute("SELECT body FROM career_records WHERE user_id=? AND id=?",
                                         ("owner", record["id"])).fetchone()[0]
            self.assertEqual(json.loads(body)["text"], FACT["text"])
            for table, rows in before.items():
                self.assertEqual([tuple(row) for row in reopened.conn.execute(f"SELECT * FROM {table}")], rows)
            self.assertEqual(reopened.conn.execute("PRAGMA quick_check").fetchone()[0], "ok")

    async def test_record_kind_cannot_change_across_revisions(self):
        record = await self.create()
        response = await self.revise(record, kind="answer", context="Question context")
        self.assertEqual(response.status_code, 422)

    async def test_migration_from_live_schema_version_preserves_existing_rows(self):
        import sqlite3

        path = Path(self.directory.name) / "version5.db"
        conn = sqlite3.connect(path)
        conn.executescript(SCHEMA.read_text())
        for number, sql in enumerate(MIGRATIONS[:5], start=1):
            conn.executescript(f"BEGIN; {sql}; PRAGMA user_version={number}; COMMIT;")
        conn.execute("INSERT INTO opportunities (id, first_seen, title, fields) VALUES (?, ?, ?, ?)",
                     ("permanent", NOW.isoformat(), "Intern", '{"Pay":"$42/hr"}'))
        conn.execute("INSERT INTO actions (opportunity_id, user_id, status, notes, updated_at) VALUES (?, ?, ?, ?, ?)",
                     ("permanent", "owner", "applied", "Private note", NOW.isoformat()))
        conn.commit()
        before = {table: list(conn.execute(f"SELECT * FROM {table}"))
                  for table in ("opportunities", "items", "actions", "alerts", "enrichment", "accounts", "credentials", "sessions")}
        conn.close()
        with Store(path) as migrated:
            self.assertEqual(migrated.conn.execute("PRAGMA user_version").fetchone()[0], 6)
            self.assertEqual(migrated.conn.execute("SELECT count(*) FROM career_records").fetchone()[0], 0)
            for table, rows in before.items():
                self.assertEqual([tuple(r) for r in migrated.conn.execute(f"SELECT * FROM {table}")], rows)
