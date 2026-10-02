# T6: Pipeline (dedupe, enrich, filter)
**Context:** 00-overview.md; T1 store; legacy derive_fields/enrich_rows/job_pages/llm_extraction.
**Goal:** turn raw Items into clean Opportunities; spend LLM tokens only where they change the outcome.
**Deliver:**
- `normalize`: canonical URL (strip tracking), company canonicalization (existing ORG tables move to `config/orgs.yaml`).
- `dedupe`: same canonical URL -> same opportunity (another item on it). Earliest seen_at wins.
- `enrich`: job-page facts (existing), then LLM ONLY if fields are still ambiguous (missing company/title/deadline or source is free text: Instagram).
  ATS and list items skip the LLM entirely (structured already). Cache by content hash; hard daily token budget with a kill switch.
- `matches_profile(opp) -> (bool, reasons)` from `config/profile.yaml`: role keyword, grad year when stated, location, not excluded. T7 alerts on it.
- Closed detection: ATS removal signal or page 404 -> status closed.
**Accept:** table-driven tests for dedupe (same apply URL via ATS + list + Instagram = 1 opportunity); filter returns reasons;
LLM not called for ATS items (assert on fake client); budget exhaustion degrades gracefully to regex.
**Deferred:** fuzzy dedupe (rapidfuzz, add when duplicates with different URLs show up in practice); 0-100 score (add with a UI that sorts by it); multi-text LLM batching.
