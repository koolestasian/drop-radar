# T20 agent automation research findings

Status: research-only; continues `T20-agent-automation-research-handoff.md` (Codex, 2026-10-04)
after Codex hit its usage limit. Done 2026-10-05 by Claude Cloud. No dependency was added to
`requirements.txt`, no account was connected, no model was called, nothing was sent or deployed.

## Answer in one paragraph

Model spend is not the lever: the handoff's own lean and illustrative workloads cost $9 to $24 a
month on Haiku at list price, and $1 to $9 on the cheapest options. The costs that matter are
engineering days, duplicate-send safety, and keeping the private career data where the owner
expects it. So the cheapest workflow is: **no agent platform; a direct in-process worker on the
existing Python/FastAPI/SQLite stack, an action ledger in Drop Radar's own tables, Haiku 4.5
(already bake-off-validated here) as the default model, and prompt caching plus the Batch API for
anything not urgent.** Add one small open-source library, **DBOS Transact** (MIT), only when the
ledger needs durable waits (a reply that may take days). Treat LangGraph, AgentScope, DeerFlow and
Dify as not needed for the first loop.

## What was measured here

Sandbox: Python 3.11.15 on a cloud container, **not the 954 MB box and not Python 3.12**. Import
RSS is after `import` only; a running agent will use more. These are smoke numbers, not a benchmark.

| Library (version, licence) | Site-packages | Import RSS | Notes |
|---|---|---|---|
| DBOS Transact 3.2.0, MIT | 91 MB | 63 MB | Pulls psycopg, SQLAlchemy asyncio, websockets |
| LangGraph 1.2.12 + SQLite checkpointer 3.1.1, MIT | 101 MB | 65 MB | Docs call `SqliteSaver` "local file-based storage for development" |
| Pydantic AI slim 2.54.0 + anthropic, MIT | 88 MB | 53 MB | Integrates DBOS, Temporal, Prefect, Restate as durable engines |
| AgentScope 2.0.9, Apache-2.0 | 296 MB | 19 MB (lazy imports; understates real use) | Needs Python 3.11+; pulls numpy and the dashscope SDK |

**DBOS crash-recovery smoke test** (`docs/specs/t20-dbos-crash-smoke.py`, SQLite system database):
a workflow of draft, send, calendar was killed with `os._exit` after the send step. On restart with
the same workflow ID it recovered, ran only the calendar step, and the send side effect appeared
**once**. Re-running the completed ID did not send again. This confirms checkpoint-and-resume and
ID-based idempotency work on SQLite.

Limits of that test:
- DBOS itself logs that SQLite "is for development and testing; PostgreSQL is recommended for
  production". Postgres on a 1 GB VM competes with the radar for memory, so this is a real cost.
- A crash **inside** a step, after the side effect but before the checkpoint, still re-runs that
  step. The spec's `reconcile-needed` state and provider message-ID check remain necessary; no
  library removes that window.
- LangGraph and AgentScope recovery were **not** tested, so "DBOS recovers" is not a comparison.

## Options considered

| Option | Fit for the first loop | Verdict |
|---|---|---|
| Direct worker + own ledger tables in the existing SQLite | Smallest footprint; policy checks, recipient identity, limits and receipts must live in Drop Radar code anyway | **Start here** |
| + DBOS Transact | Durable sleep/recv fit "wait for a reply, follow up in five business days"; MIT; one library; `system_database_url` can be SQLite or Postgres | Add when waits across restarts are needed; decide Postgres vs SQLite then |
| Pydantic AI | Typed structured output and deferred tool approval (human-in-the-loop) are useful for the draft and reply-interpretation workers; MIT; works with DBOS | Optional, adopt per worker if typed outputs save code |
| LangGraph | Mature checkpoints and interrupts, but SQLite saver is documented as development-grade and it brings the LangChain core dependency | Not needed first; revisit if the flow becomes a real graph |
| AgentScope 2.0 | Teams, permissions, scheduling, agent service; Apache-2.0; largest install here | Interesting, unproven for this loop; skip for MVP |
| DeerFlow 2.0 | Research and document sub-agents, sandboxes | Wrong owner for the outbound ledger (agrees with Codex) |
| Dify | Documented about 2 CPU and 4 GiB; extra licence conditions | Does not fit the 1 GiB VM (agrees with Codex) |
| Temporal / Restate | Real durable-execution servers; heavier to operate | Overkill at personal scale |
| LiteLLM (MIT, 1.104.0) or OpenRouter | Gateway for model routing. LiteLLM is free but wants its own proxy infra; OpenRouter charges about 5.5% on credits | Skip; a 20-line router function over two SDKs is enough |

## Model cost

Prices: Anthropic and DeepSeek from their official pages (checked 2026-10-05); the others from the
benchlm.ai aggregator (checked 2026-10-01), so confirm on the vendor page before relying on them.
Workloads are the handoff's: lean 6M input + 0.6M output tokens a month, illustrative 15M + 1.8M.

| Model ($/M in / out) | Lean | Illustrative |
|---|---|---|
| Claude Haiku 4.5, list ($1 / $5) | $9.00 | $24.00 |
| GPT-5.4 mini ($0.75 / $4.50) | $7.20 | $19.35 |
| Gemini 3.5 Flash-Lite ($0.30 / $2.50) | $3.30 | $9.00 |
| DeepSeek Flash, peak ($0.30 / $1.20) | $2.52 | $6.66 |
| GPT-5.4 nano ($0.20 / $1.25) | $1.95 | $5.25 |
| DeepSeek Flash, off-peak ($0.15 / $0.60) | $1.26 | $3.33 |
| Mistral Small 4 ($0.15 / $0.60) | $1.26 | $3.33 |

Haiku levers (Anthropic pricing page): cache reads $0.10/M and the Batch API at 50% off input and
output. If 70% of lean input is a stable cached prefix, Haiku drops from $9.00 to about $5.22
before batching. These are arithmetic scenarios, not measured usage.

Cautions on the cheap rows:
- **Privacy:** career facts, contacts and reply text are private data. DeepSeek's API is hosted by
  a Chinese provider; sending it that data is the owner's policy call, not a default.
- **Quality is unmeasured here.** Aggregator scores are not Drop Radar's tasks. The 16.3 bake-off
  found Haiku, Sonnet, and two Gemini Flash-Lite models tied on this repo's data, and Haiku never
  stalled. Route to a cheaper model only after it matches Haiku on the ten synthetic outreach cases.
- The Gemini free tier stalled 60 to 180 s on about 5% of calls in that bake-off.

## Recommended workflow, cheapest first

1. **Ledger first** (handoff gate 5): additive tables for action, approval, send attempt,
   provider message ID, suppression and receipt, user-scoped, in the existing SQLite store.
2. **One loop:** verified contact, evidence-backed draft, reply, agreed meeting, brief. Draft and
   review mode, then an allowlist with a pause switch and daily limits.
3. **Models:** Haiku for drafts, classification and reply interpretation; cached policy and
   evidence prefix; Batch API for non-urgent research; stronger model only for ambiguous replies.
4. **Contacts:** owner-supplied or imported. No paid lookup, no guessed address as sendable.
5. **Public pages:** the existing guarded reader; try Tavily or Firecrawl only where it fails.
6. **Add DBOS** when follow-up timers and reply waits must survive restarts.

## Still open (not done here)

- The ten-case synthetic outreach benchmark across a direct worker, DBOS and LangGraph (handoff
  gates 1 and 2), including GPT-5.4 mini and DeepSeek Flash against Haiku. Needs API credit and a
  case set; no model was called.
- DBOS on Postgres under the 1 GiB box, and Python 3.12 on the actual box.
- Email and calendar scopes and the operating policy (handoff gate 4).

## Sources

- https://github.com/dbos-inc/dbos-transact-py and https://docs.dbos.dev/python/reference/configuration
- https://ai.pydantic.dev/durable_execution/overview/, `/durable_execution/dbos/`, `/deferred-tools/`
- https://docs.langchain.com/oss/python/langgraph/persistence
- https://pypi.org/project/{dbos,langgraph,langgraph-checkpoint-sqlite,pydantic-ai,agentscope,litellm}/
- https://platform.claude.com/docs/en/about-claude/pricing
- https://api-docs.deepseek.com/quick_start/pricing/
- https://benchlm.ai/llm-pricing
- https://www.requesty.ai/blog/best-llm-routing-platforms-compared-2026-requesty-portkey-litellm-openrouter
