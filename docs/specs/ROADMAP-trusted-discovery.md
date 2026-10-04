# Drop Radar: trusted discovery first, excellent tracking next

Saved 2026-10-04 from the owner's requested principal-engineer audit.
Status: proposed roadmap, not implemented. This is not a replacement for current
task status in PROGRESS.md. Assigned branch: claude/trim-drop-radar-plan.

## Direction and chosen defaults

Build the best tracker for the owner and a small group: discover relevant openings
early, explain eligibility honestly, deliver dependable alerts, and make acting on
jobs easy. Prioritize missed/noisy jobs; uncertain matches go into a separate review
queue; push every strong match immediately; spend for meaningful quality improvements;
allow bounded automatic routine source repairs. Preference changes and application
submissions stay under the user's control.

The existing foundation includes shared polling, permanent IDs, private actions,
guarded posting readers, persistent alert claims, explicit exclusion approval, and
a fast feed index. Retain these rather than rewrite the app.

## Audit evidence and limits

Architecture, ingestion, matching, storage, alerts, API, frontend state, CI, deployment,
and read-only production aggregates were inspected. Temporary tests reproduced
lifecycle failures. This was not an exhaustive adversarial security test or a fresh
visual audit of every screen. Prior release validation: 504 backend tests and 68 e2e
tests; these were not rerun for the read-only audit.

Production snapshot: 12,411 opportunities, 13,441 items, 621 source records, eight
blocked source records, no pending alerts. 514 identical company/title/location groups
contain 631 additional rows; these can be legitimate separate requisitions and must
not be blindly merged. Service had no restarts since the deployment, and backup
service result was successful. The audit made no production changes.

| Priority | Finding | Required change |
|---|---|---|
| P0 | Same-ID title/location changes emit no items; nonblank stored facts remain indefinitely. Reproduced. | Distinguish new, updated, unchanged, closed and reopened sightings; refresh authoritative facts while preserving identity. |
| P0 | One source closes the whole shared opportunity; returning requisition stays closed. Reproduced. | Source-level availability and opportunity status derived from authority and freshness. |
| P0 | Fixed ATS title gate and limited Workday windows can miss jobs before profile matching. Code evidence; omission rate not measured. | Measure collection recall separately and expand within request budgets. |
| P1 | API groups company/title/location; UI also groups company/title. Hidden/closed representatives can suppress other requisitions. | Server-owned groups with explicit members and consistent counts. |
| P1 | Ingestion awaits notification sends; retries follow polling cadence. | Independent durable outbox worker using existing claims. |
| P1 | Missing location can pass eligibility; role/level depend largely on title terms. | Evidence-based match/uncertain/excluded verdicts. |
| P1 | Tracker fetches at most 200 per column without following cursors. | Paginate and expose accurate totals. |
| P1 | Whole-query optimistic rollback and blur-saved notes can race. | Per-job mutation serialization and revision conflicts. |
| P1 | Story image reader differs from guarded page reader; DNS safety check and connection resolution are separate. | Consolidated fetching, destination pinning and bounded workers. |
| P2 | Liveness-only health, no frontend CI, earliest-source latency attribution and on-host backups. | Readiness, quality metrics, frontend CI, accurate timing and off-host restore tests. |

Correction from source verification: polling history already excludes seed/closed
items. Its remaining limitations are detection-time bias and refresh on runtime reload.

## Release A: lifecycle, identity and counts

- Record each source's availability, last successful observation, authoritative
  identity and content fingerprint. Emit edits without treating them as new drops.
- Preserve permanent IDs, first-seen times, actions, notes and alert history.
- Absence in partial search/community lists is not confirmed closure. Complete
  authoritative ATS closure outweighs stale references; later authoritative
  reappearance reopens the same job. No new push on reopening by default.
- Apply passed deadlines in shared eligibility with explicit date precision.
- Add field provenance: source, observation time, method and evidence.
  Authoritative updates may replace stale facts; enrichment fills blanks unless a
  correction is separately approved. Employer pay and estimates remain separate.
- Group related requisitions without title-based record merges; return member IDs,
  filter eligible members before choosing representatives. Jobs, summary, previews
  and Tracker share semantics; individually actioned requisitions remain visible.
- Acceptance: edits update, reopening works, partial polls do not falsely close,
  counts agree with complete pagination.

## Release B: measurable coverage and matching

- Version an evaluation set of at least 200 reviewed postings spanning matches,
  exclusions, ambiguous roles, unknown/foreign locations, Stories and lifecycle edits.
  Include samples rejected by collection rules, not just collected rows.
- Use broad candidate collection based on supported roles/levels; retain obvious
  franchise/store noise filtering. Frequent fast polls plus bounded daily deep
  reconciliation for windowed sources; adapt from omissions and source limits.
- Record completeness and query revisions; expanded coverage seeds silently.
- Match verdicts: match, uncertain, excluded, each with evidence/reasons. Missing
  eligibility facts enter Review. Do not infer sponsorship, grad eligibility or
  remote availability from missing evidence. Preserve and label Story bypass.
- Deterministic rules first; model extraction only for unresolved facts with quotes,
  caching and bounded spend. Recent non-seed polling observations refresh daily;
  exploration polls prevent quiet-hour blind spots. Explicit company priority leads
  scheduling; learned prestige is secondary.
- Targets: 95% precision/recall on reviewed supported-domain set, reported separately
  for collection and matching; no universal internet-coverage claim.

## Release C: delivery and maintenance

- Extend existing alert claims with attempts, next retry, last error and terminal
  disposition; independent bounded worker, persistent schedules across restarts.
- Record triggering source/rule; recheck hidden/closed state before send and record
  cancellations. Strong matches and curated Stories push; Review does not.
- Optional Review/missed-activity digest; default remains immediate strong-match push.
- Expose failures/subscription state and verify real phone receipt. Delivery is
  at-least-once unless provider idempotency can close the accepted-before-crash gap.
- Canary checks scheduler progress, freshness, backlog and delivery, not merely silence.
- Automatic repairs begin after seven days observing. Only same-company supported-ATS
  board URL/slug replacement: two probes, identity agreement, prior-value snapshot,
  audit history, rollback, silent seed. Conflicts require review. No automatic company
  deletion, preference widening, robots bypass or code deploy.
- Acceptance: failed delivery cannot delay collection; retries survive restarts;
  repairs are reversible and cannot generate false drops.

## Release D: API performance and frontend consistency

- Retain SQLite/bitmap initially; batch row/sighting/action reads, immutable generations
  from consistent snapshots, shared SQL/bitmap/summary/preview semantics.
- Bound/deduplicate enrichment queues; slots remain held until timed-out workers finish.
- Shared token-budget reservations for Story/pay/ratings; record actual usage and errors
  without resetting spending.
- Request cancellation, per-job mutation serialization, affected-row rollback and
  expected revisions. Conflict returns latest state rather than overwriting notes.
- Reconcile list/summary on action/profile/reconnect/missed-event signals. Tracker
  pagination, preserved drafts and saving/saved/retry states.
- Release-aware bounded PWA asset caching; honest offline state, no offline writes.
- Targets: warm feed/filter p95 <200ms; cold startup <15s on production-size data;
  no foreground stalls from enrichment. Measure rather than claim.

## Release E: daily action workflow

- Confirmed Jobs, accessible Review/Everything, saved searches, explicit company priority,
  deadline reminders, reversible not-relevant feedback.
- Details: match/uncertainty evidence, verification time, source history, related reqs,
  pay provenance. Tracker adds application/next-action/follow-up dates, contacts,
  interview events and resume-version reference.
- Save description snapshots for saved/applied jobs. User-requested URL import is separate
  from read-only diagnostics. Export applications/notes portably.
- Comparison/preparation precede autofill; application submission requires the user.
- Real owner desktop/mobile screen checks: keyboard, focus, touch targets, screen readers,
  long content, slow networks.

## Release F: security, recovery and maintainability

- One guarded page/image/discovery reader: redirect validation, destination pinning,
  size limits, robots policy and total deadlines.
- Explicit public guest source set instead of union of private watchlists.
- Secure HttpOnly browser sessions with same-origin protections; scoped automation bearer
  access remains separate. Session revocation/cleanup, account export/deletion/retention.
- Frontend build/e2e and generated-contract drift CI; locked backend dependencies.
- Readiness, structured logs, request IDs, queue/freshness metrics and release IDs.
- Encrypted off-host backups/monthly restore drills; initial RPO 24h and RTO 1h.
- Correct outdated deploy/shutdown/exporter docs. Split modules by changed responsibility,
  remove verified obsolete settings, preserve legacy import compatibility.
- Spend on host capacity when measured queue/memory/CPU violates targets; no speculative
  service or database rewrite.

## Interfaces, validation and rollout

Add opportunity verdict/reasons/availability/provenance/revision/group members;
Review filters and summary; complete Tracker pagination; expected revisions with 409
latest-state conflicts; notification preferences/status; repair audit/rollback;
application timeline. Preserve old fields and regenerate OpenAPI/frontend types.

Tests: lifecycle edits/reopening, multi-source closure, partial/widened searches,
cross-page grouping, hidden representatives, deadlines, uncertainty, approval previews,
isolation, edit races, notification crashes, budget contention, guarded-fetch failures,
restore. Randomized SQL/bitmap parity; source/DB/model/delivery/queue/restart fault injection.
Final diff: backend discovery, pyflakes, web build/full e2e, affected real-data screens.
Preserve IDs/actions/notes/pay/unrelated blank fields; explain each intended change.

Order A -> B -> C -> D -> E -> F, pulling security/CI prerequisites into affected releases.
Observation-only first, owner then group. Schema/data/config writes need exact description
and backup under existing deploy rules. Assigned branch only; no PR/tag unless requested.
T16.7 moves after foundations, T16.8 becomes evidence-backed display normalization, T14
becomes dependable strong-match delivery with optional digest. Implementation starts A.

Success: collection recall, match precision, source freshness/blocked duration,
detection-to-alert latency separate from imprecise posted dates, time to save/apply,
Review usefulness, completed follow-ups, cost per verified relevant discovery.

## External references checked 2026-10-04

- SQLite WAL: https://www.sqlite.org/wal.html
- Teal tracker: https://help.tealhq.com/en/articles/14435727-how-to-track-your-job-applications
- Huntr tracker: https://help.huntr.co/en/articles/9883324-job-tracker
- Simplify Copilot: https://simplify.jobs/copilot

These support the strategic distinction: dependable discovery plus the action loop;
tracking/notes/extensions/autofill alone are established capabilities elsewhere.
