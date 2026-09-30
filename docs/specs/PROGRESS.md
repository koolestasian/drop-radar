# Task progress

Update this file in the same commit that finishes a task. One line per task.
Status: `todo` | `doing` | `done` (with commit hash and date).

| Task | Status | Notes |
|---|---|---|
| T0 foundations | done (6244818, 2026-09-30) | Suite is 87 legacy + 11 new = 98 (spec said 88; baseline was already 87). Root shims alias legacy modules. |
| T1 store | todo | |
| T2 scheduler | todo | |
| T3 ats-sources | todo | |
| T4 community-sources | todo | |
| T5 instagram | todo | |
| T6 pipeline | todo | |
| T7 alerts | todo | |
| T8 api | todo | |
| T9 web | todo | |
| T10 deploy-scale | todo | |
| T11 hardening | todo | |

## Decisions (defaults until the user changes them)
- Deploy target: Docker on a ~$5 VPS (decide final host at T10; home server is best for Instagram).
- Sources beyond the spec: none yet. Seed watchlist with ~300 companies at T3.
- Run independent tasks (T3, T4, T5) in fresh subagents; run the rest sequentially.
