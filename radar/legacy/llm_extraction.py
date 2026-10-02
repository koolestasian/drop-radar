#!/usr/bin/env python3
"""Structured extraction of an opportunity post with Claude.

Turns noisy caption/OCR text (plus the job page, when it could be read) into
validated fields. `extract` never raises: any API problem returns None and the
monitor keeps its regex-based fields.
"""
import json
import os
import re
import threading

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-5-5").strip() or "claude-opus-5-5"

SYSTEM_PROMPT = """You read posts from @zero2sudo, an Instagram account that shares \
career opportunities with university students: internships, new-grad roles, \
fellowships, scholarships, hackathons, recruiting events and similar.

The post text combines the caption and OCR of the Story image, so expect OCR \
noise, broken lines, and fragments of the account's own commentary. When the \
job page behind the post's application link could be read, its facts are given \
too; they are authoritative for title, organization, location and deadline.

Extract facts about the opportunity itself:
- is_opportunity: true only when the post offers something a student can \
apply to, register for or RSVP to. Advice, memes, offer celebrations, \
"has anyone heard back" questions and recaps are false.
- organization: the employer or host (for example "Scale AI"), never the \
job board, the link shortener or zero2sudo. Empty when unknown.
- title: the opportunity's own name without the organization, for example \
"Software Engineer Intern, Summer 2027". Empty when unknown.
- deadline: YYYY-MM-DD only when an application or registration deadline is \
stated. Resolve a date without a year relative to the post date. Empty otherwise.
- season: for example "Summer 2027". Empty when not stated.
- location: city/state or "Remote", comma separated. Empty when not stated.
Use empty strings rather than guessing."""


def schema(categories, roles):
    return {
        "type": "object",
        "properties": {
            "is_opportunity": {"type": "boolean"},
            "confidence": {"type": "number"},
            "organization": {"type": "string"},
            "title": {"type": "string"},
            "category": {"type": "string", "enum": list(categories)},
            "roles": {"type": "array", "items": {"type": "string", "enum": list(roles)}},
            "season": {"type": "string"},
            "location": {"type": "string"},
            "deadline": {"type": "string"},
        },
        "required": [
            "is_opportunity", "confidence", "organization", "title", "category",
            "roles", "season", "location", "deadline",
        ],
        "additionalProperties": False,
    }


class Extractor:
    """Thread-safe wrapper that also totals token usage for the run report."""

    def __init__(self, categories, roles, client=None):
        self.categories = list(categories)
        self.roles = list(roles)
        self.schema = schema(self.categories, self.roles)
        self._client = client
        self._lock = threading.Lock()
        self.usage = {"calls": 0, "failures": 0, "input_tokens": 0, "output_tokens": 0}

    @property
    def client(self):
        if self._client is None:
            import anthropic

            self._client = anthropic.Anthropic()
        return self._client

    def _record(self, **counts):
        with self._lock:
            for key, value in counts.items():
                self.usage[key] += value

    def prompt(self, text, link="", posted="", page=None):
        parts = [f"Post date: {posted or 'unknown'}", f"Application link: {link or 'none'}"]
        if page:
            facts = {
                key: page[key]
                for key in ("title", "organization", "location", "deadline", "posted")
                if page.get(key)
            }
            if facts:
                parts.append("Job page facts: " + json.dumps(facts, ensure_ascii=False))
            if page.get("description"):
                parts.append("<job_page>\n" + page["description"] + "\n</job_page>")
        parts.append("<post>\n" + text + "\n</post>")
        return "\n\n".join(parts)

    def extract(self, text, link="", posted="", page=None):
        import anthropic

        try:
            response = self.client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": self.prompt(text, link, posted, page)}],
                output_config={
                    "effort": "low",
                    "format": {"type": "json_schema", "schema": self.schema},
                },
                # Re-run a safety-classifier decline on Anthropic's recommended
                # fallback model instead of losing the extraction.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
            self._record(failures=1)
            print(f"::warning::Claude extraction failed: {type(exc).__name__}: {exc}")
            return None
        usage = getattr(response, "usage", None)
        self._record(
            calls=1,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
        )
        if response.stop_reason == "refusal":
            self._record(failures=1)
            return None
        text_block = next((block.text for block in response.content if block.type == "text"), "")
        try:
            return self.validate(json.loads(text_block))
        except (ValueError, TypeError):
            self._record(failures=1)
            return None

    def validate(self, data):
        if not isinstance(data, dict):
            raise ValueError("not an object")
        deadline = str(data.get("deadline") or "").strip()
        return {
            "is_opportunity": bool(data.get("is_opportunity")),
            "confidence": max(0.0, min(1.0, float(data.get("confidence") or 0))),
            "organization": str(data.get("organization") or "").strip()[:80],
            "title": str(data.get("title") or "").strip()[:120],
            "category": data.get("category") if data.get("category") in self.categories else "",
            "roles": [role for role in data.get("roles") or [] if role in self.roles],
            "season": str(data.get("season") or "").strip()[:40],
            "location": str(data.get("location") or "").strip()[:120],
            "deadline": deadline if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", deadline) else "",
            "model": MODEL,
        }
