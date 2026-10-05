# T20 agent automation research handoff

Status: research-only, incomplete; no framework, account, model, contact-data
provider or outbound action was activated. Prepared 2026-10-04 for continuation
by Claude Cloud.

## Current recommendation

Keep Drop Radar's Python/FastAPI/SQLite system as the source of truth. Add a
small coordinator that proposes the next action, focused workers for research,
drafting, reply interpretation and preparation, and a durable action/workflow
ledger owned by Drop Radar. The model may reason; application code must own
policy checks, recipient identity, evidence revisions, send limits, opt-outs,
idempotency, reconciliation and receipts. Begin with one complete loop:

`verified contact -> evidence-backed outreach -> reply -> agreed meeting -> brief`

Do not begin by installing a large agent platform or letting a general-purpose
agent control email. The existing database and guarded readers are the cheapest
place to establish durable state and truthful evidence.

## Candidates to benchmark

- **LangGraph**: strongest first framework candidate for Python orchestration
  and checkpoints. Its documentation distinguishes in-memory checkpointers from
  persistent Postgres and SQLite options. SQLite is suitable for development;
  production migration should be decided from measured concurrency and recovery
  needs. https://github.com/langchain-ai/langgraph
- **AgentScope 2.0**: credible Chinese-origin alternative. Its repository
  advertises teams, model routing, tool permissions, persistence, scheduling and
  an agent service, and states Apache-2.0 licensing. Benchmark it rather than
  adopting the feature list. https://github.com/agentscope-ai/agentscope
- **DeerFlow 2.0**: ByteDance's open super-agent harness with memory, skills,
  sandboxes and sub-agents. It is better suited to research and document workers
  than to owning Drop Radar's outbound action ledger.
  https://github.com/bytedance/deer-flow
- **Dify**: visual workflow/RAG/agent platform, but its documented minimum is
  about 2 CPU and 4 GiB RAM and its open-source license has additional
  conditions. It does not fit the current 1 GiB VM without an upgrade.
  https://github.com/langgenius/dify

The key comparison is not “which project has the most agents”; it is recovery
after a crash, tool-level permission hooks, structured outputs, persistent
state, license fit, and how much custom code remains at the email boundary.

## Cost hypotheses to verify with a small benchmark

Use model routing: a cheap model for classification, extraction and first drafts;
the stronger model only for ambiguous replies, high-value personalization and
final review. Cache the stable policy/evidence prefix, compress context, and
batch non-urgent research. Keep contact discovery optional: imported or
owner-supplied contacts are cheaper and more trustworthy than broad enrichment.

Useful current reference prices found during research:

- GPT-5.4 mini: published at $0.75/M input and $4.50/M output.
- Claude Haiku 4.5: published at $1/M input and $5/M output, with cache/batch
  discounts described by Anthropic.
- DeepSeek Flash: official pricing page lists off-peak $0.15/M cache-miss
  input, $0.003/M cache-hit input and $0.60/M output; peak rates are higher.
- Tavily: free 1,000 credits/month; pay-as-you-go $0.008/credit.
- Firecrawl: free 1,000 credits/month; Hobby shown as $19 monthly or $16/month
  with annual billing.
- Hunter: free 50 credits/month; Starter shown as $34/month with annual pricing
  also displayed. Do not make it a required dependency.
- Gmail API standard use and Google Calendar API use are documented as no
  additional API charge, but Gmail scopes and OAuth/data policies still govern
  access. Personal use can affect verification requirements but does not remove
  security obligations.

For the earlier illustrative workload (15M input + 1.8M output/month), model
cost is approximately $19.35 on GPT-5.4 mini or $24 on Haiku before cache/batch
savings. A lean workload (6M + 0.6M) is approximately $7.20 or $9.00. These are
budget scenarios, not measured usage or promises of equal quality. Contact
lookup, page retrieval, hosting upgrades and email-provider limits are separate.

## Next research and decision gates

1. Benchmark LangGraph, AgentScope and a direct in-process worker against the
   same ten synthetic outreach cases: factuality, tool errors, recovery,
   duplicate-send prevention, latency, tokens and operator interventions.
2. Benchmark GPT-5.4 mini, Haiku 4.5 and DeepSeek Flash on those cases; retain a
   difficult-case escalation path and record cost per useful reply/meeting.
3. Test public-page retrieval with the existing guarded reader first; compare
   Tavily/Firecrawl only when coverage or parsing fails.
4. Define the exact email/calendar scopes and operating policy before any OAuth
   connection. No scraping of login-walled networks and no guessed address is
   sendable evidence.
5. Implement the action ledger and receipts before autonomous sends. The first
   pilot should run in draft/review mode, then a bounded allowlist with a pause
   switch and daily limits.

## Primary sources consulted

- https://docs.langchain.com/oss/python/langgraph/persistence
- https://github.com/agentscope-ai/agentscope
- https://github.com/bytedance/deer-flow
- https://github.com/langgenius/dify
- https://developers.openai.com/api/docs/models/gpt-5.4-mini
- https://www.anthropic.com/claude/haiku
- https://api-docs.deepseek.com/quick_start/pricing/
- https://www.tavily.com/pricing
- https://www.firecrawl.dev/pricing
- https://hunter.io/pricing
- https://developers.google.com/workspace/gmail/api/reference/quota
- https://developers.google.com/workspace/calendar/api/guides/quota
