# T12: first to act — product review and improvement spec

## Verdict (2026-10-01 Pacific)

I would use Drop Radar for discovery and application tracking, but would not
yet trust it as my only early-warning system. More boards is not the same as
faster, reliable delivery. This is an opportunity monitor with manual application
tracking, not an application submission system.

Live audit: 621 source states, 12 currently failing, zero alert records. Both
NTFY topics and HEARTBEAT_URL are unset. Instagram has no last_ok and seven
consecutive HTTP 429 failures. The service is active with zero automatic
restarts since its latest start. These are a snapshot, not availability claims.

## Findings, highest impact first

1. **P0: fast phone delivery is not live.** The legacy hourly job remains the
   alert path. A green SSE connection must not imply phone alerts work.
2. **P0: the highest-priority insider source is blind.** The stored Instagram
   user id did not fix the VM's 429s. Respect the cooldown; the next experiment
   is owner-authorized residential polling with authenticated relay, not more
   frequent requests from the blocked VM.
3. **P1: incomplete boards hide drops.** SmartRecruiters fetches only the first
   100 postings, even on larger boards. Preserving the old cursor prevents false
   closes but cannot discover jobs that never appear on page one.
4. **P1: user B can miss a live update.** Pipeline publishes only when the global
   opportunity is new. A later sighting by B's own source does not reach B's stream.
   Publishing waits for push delivery too; one slow phone channel also delays
   the other user's channel. The feed stops reconciling after its first backfill.
5. **P2: sharing a useful drop takes extra work.** Provide a share/copy action
   for the public application URL, without including API tokens or private topics.

## Implement now

Residential probe succeeded (39 Stories). Add an opt-in SSH relay and a macOS
LaunchAgent at the configured 300s cadence. The relay uses the existing owner's
authentication and the running server's pipeline (never a second alert dispatcher
process). The VM stops native Instagram polling in relay mode. First successful
relay backfills silently; repeats stay idempotent. Source health must flag missed
relay intervals when the Mac sleeps. Do not claim this makes a sleeping Mac always on.

- Paginate SmartRecruiters through its documented public Posting API. Every
  page uses FetchContext limits. Fetch all pages before advancing any cursor;
  fail on inconsistent totals, repeated/empty pages, or malformed shapes.
  Multi-page boards cannot use a page-one 304 as proof the whole board is unchanged.
- Announce a newly stored source sighting after enrichment and before push
  delivery, including sightings deduped onto an existing opportunity. Repeated
  sightings and seeds stay silent; API stream ownership/profile checks remain.
- Dispatch/retry users concurrently, preserving claim-before-send and per-user
  failure isolation. Slow owner delivery must not delay the friend's send.
  Process fresh drops before the pending retry sweep.
- Reconcile populated feeds periodically and on SSE reconnect. Backfill stays
  labeled already open; reconciliation does not synthesize drop events.
- Expose this user's phone configuration and own subscription URL through
  authenticated /api/me. Show disabled alerts plainly and provide subscription
  instructions. Configuration does not prove device delivery.
- Add share/copy on cards with cancellation and clipboard-error handling.
- Keep alert timing stats per recipient. Label unknown publication-time fallback
  honestly as first-seen timing, and distinguish push acceptance from device receipt.

## Acceptance and validation

Offline regressions must prove page-two drops and real closes, atomic cursor
failure, cross-source live events without repeat events, events before a stalled
send, concurrent fanout without duplicate sends, and notification isolation.
Run the complete unittest suite, pyflakes, generated OpenAPI/type checks and
desktop/phone Playwright checks for feed reconciliation, disabled-alert notice,
subscription link, and sharing. Deploy only validated changes; preserve live
config, cursors, permanent IDs, statuses and notes, with a DB backup first.

## Operational work and limits

Choose separate private topics if the legacy topic cannot be retrieved without
exposing it. Preserve the documented full-day gate before the alert cutover:
enable new pushes and disable legacy pushes together, keep the hourly data job.
Verify an actual phone notification after subscription; HTTP acceptance alone
does not prove it reached a device. Never claim universal "first": S/A boards
poll at 120s, B at 300s, C at 900s, plus request queuing and source failures.
Unknown publication times and day-granular dates do not prove release latency.

Next priorities: repair Instagram collection; measure actual successful-poll
gaps and request demand (267 Workday boards make multiple requests per poll);
confirm the friend's geography/season/undergrad eligibility; then improve
application preparation using saved profile/resume facts and human review.
Do not submit guessed eligibility answers or applications automatically.
T11 remains deferred; this task addresses concrete review findings.

## Source references

- [SmartRecruiters public Posting API endpoints](https://developers.smartrecruiters.com/docs/endpoints)
- [ntfy phone subscription instructions](https://docs.ntfy.sh/subscribe/phone/)

## Results

Implementation complete and live (2026-10-02, ~10:00 UTC).

- 385 offline tests pass on Python 3.14 and on an isolated Python 3.12 environment.
  Pyflakes and diff checks pass. OpenAPI and generated frontend types match.
  Production build and 12 desktop/phone Playwright checks pass.
- Core fixes deployed after a SQLite backup. Friend's independently generated
  topic is enabled and visible only through their authenticated Settings page.
  Owner's separately generated topic is staged, mode 600, for the full-day cutover.
  The legacy push gate remains unchanged. No subscription or phone receipt is verified.
- Relay live. Earlier attempts were interrupted by restarts. After one coordinated
  redeploy, a manual run stored all 39 Stories as silent backfill in 2m21s (no
  alerts, `last_ok` set, `fail_count` 0). Then the LaunchAgent
  (`~/Library/LaunchAgents/com.dropradar.instagram-relay.plist`, RunAtLoad, 300s,
  logs in `~/Library/Logs/DropRadar/`) took over; its runs return `new: 0`.
- Found on the live run and fixed (3f9b864, 1be39b3):
  - Tesseract's default OpenMP threads made one Story's OCR take ~25s on the
    2-vCPU VM. With one thread it takes 4-7s; `radar.service` now sets
    `OMP_THREAD_LIMIT=1`.
  - The relay's 240s timeout could not fit a first backfill, and its retries
    would have stacked handlers on the server. It now waits up to 2400s, with SSH
    keepalives so a run the Mac sleeps through fails in ~90s.
  - After a restart, every stored Story was re-OCRed before the already-stored
    check. The check now runs first.
  - Story titles came out as Instagram's "Visit Link" sticker label or its alt
    text. They now use the legacy tracker's title rule (link slug, else the best
    opportunity line, else category/role/season), which improved all 39 live titles.
    With the user's OK, the 39 already-stored Stories were retitled (backup
    `radar-20261002T100936Z.db`); 9 merged into job-board postings keep the board's title.
- One server-side Python 3.12 test hit its 10s process-start deadline while the VM
  was busy; the same full suite passes in the isolated 3.12 environment. Do not
  run the full test suite alongside first-backfill OCR on this small production VM.

Ponytail debt check: nine comment markers remain, one with no upgrade trigger.
They cover the 1s scheduler tick, Python feed filtering, in-memory alert backoff,
bounded SSE queues, US-city heuristics (no trigger), hardcoded source-title terms,
partial-window baselines, Instagram fallback cooldown, and its unbounded OCR cache.
No new shortcut marker was introduced. SmartRecruiters' first-page shortcut was removed.

Remaining risks: Story availability depends on the Mac being awake and online
(Sources flags the relay stale after two missed intervals); no new Story has yet
gone end to end to a push; neither device is subscribed/verified here. Polling intervals and rate-limited sources preclude
guaranteeing "first for every drop." Claim-before-send prevents ordinary concurrent
duplicates, but a crash after remote push acceptance and before sent_at is saved
can still cause a retry duplicate; exactly-once transport is not proven.
