# T6: Pipeline (dedupe, enrich, score)
**Context:** 00-overview.md; T1 store; legacy derive_fields/enrich_rows/job_pages/llm_extraction.
**Goal:** turn raw Items into clean, ranked Opportunities; spend LLM tokens only where they change the outcome.
**Deliver:**
- `normalize`: canonical URL (strip tracking), company canonicalization (existing ORG tables move to `config/orgs.yaml`).
- `dedupe`: exact canonical URL -> same opportunity; else fuzzy `company + normalized title + location` (rapidfuzz >= 92) within 14 days -> merge as another item. Earliest seen_at wins.
- `enrich`: job-page facts (existing), then LLM ONLY if fields are still ambiguous (missing company/title/deadline or source is free text: Instagram/Reddit/Telegram). ATS items skip the LLM entirely (structured already). Cache by content hash; batch up to 10 texts per call; hard daily token budget with a kill switch.
- `score` (0-100) from `config/profile.yaml`: role match, grad-year match, company tier, location, freshness, source trust (zero2sudo > ATS > list > reddit). Rules explained in `score_reasons` for UI.
- Closed detection: ATS removal signal or page 404 -> status closed.
**Accept:** table-driven tests for dedupe (same job via ATS + Instagram + list = 1 opportunity); score explains itself; LLM not called for ATS items (assert on fake client); budget exhaustion degrades gracefully to regex.
