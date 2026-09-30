# T8: Backend API
**Context:** 00-overview.md; T1 store repository; T7 alerts table.
**Goal:** small, typed API the web app and scripts use.
**Deliver (FastAPI, Pydantic models, bearer-token auth from env):**
- `GET /api/opportunities` (filters: q, status, min_score, source, company, since, closing_within; cursor pagination),
  `GET /api/opportunities/{id}`, `PATCH /api/opportunities/{id}` (status: new|saved|applied|interview|offer|rejected|ignored, notes),
  `GET /api/stream` (Server-Sent Events: new opportunity, status change), `GET /api/sources/health`, `GET /api/metrics` (latency p50/p95 per source, items/day, LLM spend),
  `GET/PUT /api/config/watchlist` and `/profile` (validated, hot-reloaded by scheduler).
- Serves the built SPA from `web/dist` at `/`.
- OpenAPI schema committed to `docs/openapi.json` (frontend types generated from it).
**Accept:** httpx TestClient tests per endpoint; auth required; SSE delivers within 1s of insert; invalid config PUT rejected with field-level errors.
