# T9: Frontend (web app, installable on phone)
**Context:** 00-overview.md; `docs/openapi.json` only (do not read backend code).
**Goal:** clean, fast UI to triage drops in seconds and track applications.
**Stack:** React + Vite + TypeScript + Tailwind; TanStack Query; types generated from openapi; PWA (installable, Web Push optional later).
**Screens:**
1. **Live feed**: newest first, SSE-updating, score badge + reasons, company, title, deadline countdown, source + "seen Xs after posted", one-tap Apply, Save/Ignore keyboard shortcuts (j/k/s/i/a).
2. **Pipeline**: kanban saved -> applied -> interview -> offer/rejected, drag to change status, notes.
3. **Search/filters**: company, role, location, min score, closing soon, source; saved views.
4. **Sources**: health table (last ok, errors, latency p50/p95), enable/disable, add company/account/feed.
5. **Settings**: profile (roles, grad year, locations, tiers), alert rules, quiet hours, token.
**Quality bar:** mobile-first, dark mode, Lighthouse perf >= 90, no layout shift on SSE insert, empty/error/loading states everywhere, a11y labels, Playwright smoke test of feed + status change.
