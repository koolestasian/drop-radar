# Ambitious operational product architecture

## What bigger product is missing beyond T20?

### Takeaway
The compelling larger vision is a personal opportunity operating system: it understands the opportunities you want, the person you currently are, the people and organizations around you, the commitments already made, and the best feasible next actions. The gap is coordinated decision-making across those things, rather than merely adding more isolated automations.

### Cited Findings
- T20 already plans career facts/answers, fit ranking, contact routes, resume QA, policy-governed outreach, reply interpretation, scheduling, event workflows, proof of work, skill-gap tasks, outcome feedback and cross-route ranking. These are planned capabilities, not missing ideas and not implemented functionality. [T20](../../docs/specs/T20-opportunity-action-engine.md)
- T19 proposes source-level availability and field provenance, lifecycle edits/reopening, uncertain eligibility, consistent requisition grouping and durable alerts. These correctness needs already have a plan. [T19](../../docs/specs/T19-trusted-discovery.md)
- The current central schema models opportunities, source items, source state, alert claims, private status/notes, enrichment, accounts and sessions. The reviewed core dataclasses model job sightings and deduplicated jobs. This is a solid job collection foundation, not yet an integrated model of relationships, capabilities, commitments and competing actions. [Schema](../../radar/store/schema.sql), [models](../../radar/models.py), [migrations](../../radar/store/__init__.py)
- Current company tiers use a shared CS-student desirability rubric: broad company categories and exemplars, including a dream tier. Such a rubric does not express an individual team's quality, current learning opportunity, realistic route or your distinctive contribution. [Company priority](../../radar/pipeline/priority.py)
- Palantir describes its Ontology as an operational layer connecting data assets to real-world objects, with properties/links plus actions/functions and governance. This is an architectural analogy, not evidence that Drop Radar should buy Palantir or that its founders endorse this roadmap. [Ontology overview](https://www.palantir.com/docs/foundry/ontology/overview)

### Inferences
- Ruthless product verdict: a comprehensive list of jobs and AI actions can still leave the user doing all the important coordination. A product earns the operating-system claim when a change in the world changes its plan, its commitments remain internally consistent, and progress compounds across workflows.
- Proposed north-star journey: “I want a strong quant internship next summer. I have eight hours weekly, these constraints, these verified strengths, these gaps and these relationships.” The system maintains campaigns, discovers opportunities, proposes and executes permitted routes, prepares the owner, reconciles outcomes and updates the next week's plan. No fabricated success probability is necessary.
- Founder-level differentiation is the combination of private history, actual artifacts, relationship context, timing and reliable execution. Public job data and generic AI-written documents alone are easy to substitute. This is a product judgment, not a verified competitive moat.
- A useful entity model is Goal, Person, Company, Team, Opportunity, Event, Requirement, CareerFact, Artifact, Interaction, Commitment, Action and Outcome. Relationships should carry evidence, observed time, effective time, uncertainty, visibility and revision. Store a person's employer as an evidenced time-bounded claim, not an eternal string. Derived conclusions should point to their supporting claims.
- Begin with additive private SQLite tables and explicit foreign keys; a graph database is not required. Keep permanent shared opportunity IDs and user isolation. A relational model can supply connected workflows without a speculative infrastructure migration.

### Gaps
- This review did not measure the live owner funnel or reproduce the entire app. No numerical prediction of interview uplift or savings is justified.
- T20 is detailed on individual workflows but lacks a concrete contract for a global plan, competing resource allocation, dependency scheduling, commitment conflicts and target-team campaigns.

## Which eight capabilities would materially expand the product?

### Takeaway
Build capabilities that allow intelligence to compound across decisions. Several extend ideas already named in T20; their additional scope is the missing coordination, user experience and explicit decision contract.

### Cited Findings
- Palantir documents scenarios for evaluating modeled operating conditions and actions; this supports the mechanism of scenario comparison, not the accuracy of any proposed hiring model. [Scenarios](https://www.palantir.com/docs/foundry/vertex/scenarios-overview)
- Palantir Automate combines scheduled/object conditions with action and notification effects. [Automate](https://www.palantir.com/docs/foundry/automate)
- Research on learning from logged bandit feedback explicitly addresses selection through propensity scoring and estimator variance. Historical observations from chosen actions cannot automatically establish the value of a different policy. [Swaminathan and Joachims, 2015](https://arxiv.org/abs/1502.02362)

### Inferences
All eight below are recommendations, with no measured performance claims.

1. **A decision desk that allocates your actual week.** Journey: an assessment due Friday, an application closing Tuesday, a warm intro and a useful event compete for eight available hours. Show a feasible plan with estimated effort, uncertainty, deadline, purpose and what can run autonomously. T20 ranks jobs/routes but does not specify this global allocation. Increment: action candidates plus calendar capacity, hard constraints and an explainable deterministic scheduler. Failure: a high-ranked job consumes all time while committed assessments or preparation lapse. Avoid false mathematical certainty; expose assumptions and alternative plans.

2. **Company and team campaigns before an opening exists.** Journey: open one target company and see relevant teams, verified people, work themes, recruiting cycles, actual conversations, reusable proof and next actions; a new opening activates existing context. T20 names relationship-before-opening and company signals. Missing: persistent campaign object, milestones, evidence refresh, route topology and explicit dependency plan across weeks. Increment: private campaign linked to public company/team facts, contacts and opportunities. Failure: speculative team needs are presented as hiring facts, or two agents contact the same organization incoherently.

3. **Route orchestration with preservation of options.** Journey: a referral request is pending, but a deadline approaches; submit via the permitted route before closure, then update the connection with the exact submitted requisition and artifact. Conversely, avoid parallel contradictory messages to a recruiter and teammate. T20 already offers routes; missing: route dependencies, exclusion rules, handover timing and state shared by competing workflows. Increment: action dependencies, company/person concurrency keys, expiry and explicit route transitions. Failure: autonomy waits indefinitely for an intro, duplicates applications or creates inconsistent narratives.

4. **A capability engine that makes the candidate stronger.** Journey: repeated target roles require probabilistic reasoning; schedule bounded independent practice, retain mistakes and explanations, run a later unfamiliar test, then link demonstrated improvement to preparation and career evidence. T20 names skill tasks and delayed practice. Missing: longitudinal skill evidence, independent performance, target-demand coverage and a learning queue that competes with application time. Increment: competency rubric, practice attempts, feedback, later retest and user-reviewed artifact claims. Failure: reading an AI answer is recorded as mastery, or mock-interview scores masquerade as hiring probabilities.

5. **An evidence studio for distinctive work.** Journey: select owned repositories/projects and create a reusable packet of defensible architecture decisions, measured tradeoffs, demos and contributions. The system identifies what evidence would make a target-team case credible and helps scope the next artifact. T20 names proof of work and fact import. Missing: artifact lifecycle, proof quality, contribution ownership, reproducibility, public/private export and link to target demands. Increment: artifact manifest, claim/evidence mapping, role-specific presentation, verification status. Failure: unlimited bespoke free work or polished claims unsupported by what the owner actually built.

6. **Relationship memory that respects reciprocity.** Journey: a conversation creates a promise to send a repository, a consented introduction and an interest in a topic. Track exact promises and evidence; prompt or perform permitted follow-through; recommend genuinely relevant material later. T20 explicitly names CRM and requested follow-through. Missing: commitments as first-class entities, reciprocity context, route relevance over time and stale employment handling. Increment: thread/encounter-sourced commitments, due dates, consent and manual relationship notes. Failure: contact count substitutes for relationship quality, invented familiarity, or repeated asks despite a decline. Do not infer warmth from message volume alone.

7. **A personal experiment and outcome lab.** Journey: distinguish submission receipts, automated tests, real human interviews, useful held meetings, referrals, time spent and eventual offers. Compare role-family cohorts and artifact/route variants with pending outcomes visible. T20 already proposes funnel metrics. Missing: durable exposure/action-selection logs, policy and artifact versions, outcome delay, reasons for choosing a route and uncertainty-aware comparison. Increment: append-only events and readable cohort reports; owner-controlled exploration of suitable actions. Failure: selectively chosen easy roles make a method look effective, or ghosted pending cases are treated as final failures. Sparse personal data should support decisions and hypothesis generation, not precise causal models.

8. **An offer and long-term option engine.** Journey: two offers arrive with different deadlines, compensation, team quality, location constraints and learning potential. Compare verified terms and owner-valued scenarios; request missing facts, prepare questions, track deadlines and owner-approved responses. T20 concentrates on reaching interviews and action workflows; this decision layer is materially outside its detailed specification. Increment: versioned offer facts, preferences, deadline timeline and qualitative/interval scenarios. Failure: prestige dominates the actual team, uncertain estimates become contractual facts, or autonomy accepts/declines a material commitment without appropriate owner authorization. Longer horizon: preserve relationships and artifacts into the next recruiting cycle.

### Gaps
- No evidence establishes which of these creates the largest personal uplift. They can be sequenced as additive connected capabilities without pretending every hypothesis is proven.
- Team quality, relationship relevance, recruiting timing and future career optionality often lack trustworthy structured data. Manual owner knowledge plus labeled uncertainty is needed.
- Offer eligibility, contract terms and immigration considerations require precise source-backed treatment; this review supplies no legal advice or eligibility verdicts.

## What makes ambitious autonomy operationally credible?

### Takeaway
The product should continuously observe, plan, act and reconcile. Its operational memory and execution boundary should be more trustworthy than the language model producing suggestions.

### Cited Findings
- Temporal documents durable workflows retaining progress through failure; its activity documentation separately recommends idempotent activities so retries do not duplicate side effects. A durable workflow is not a blanket guarantee of exactly-once external email or form submission. [Temporal](https://docs.temporal.io/temporal), [Activities](https://docs.temporal.io/activities)
- LangGraph persistence checkpoints graph state and enables recovery and interaction. This does not remove the need to verify external effects. [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- Palantir submission criteria evaluate contextual business conditions before permitting actions and provide failure explanations. [Submission criteria](https://www.palantir.com/docs/foundry/action-types/submission-criteria)
- T20 already specifies one AI interpretation/planning worker and a deterministic executor, exact inputs/policy revisions, durable action states, uncertain-send reconciliation and exceptions. Treat these as existing design strengths. [T20](../../docs/specs/T20-opportunity-action-engine.md)

### Inferences
- Incremental architecture: shared opportunity facts → private temporal context → goals/constraints → action candidates → selected plan → policy preflight → provider adapter → receipt/reconciliation → updated context/outcome. Every recommendation and write should explain its source, version and purpose.
- Extend T20's executor with cross-workflow reservations and dependency rules, owner time as a resource, stale-plan invalidation and distinct expected versus observed outcomes. An agent saying “done” is not evidence that the outside world changed.
- Example: calendar edit during a pending scheduling action invalidates a proposed slot; a recruiter decline cancels queued follow-ups; an artifact correction invalidates unsent attachments; changed job availability updates route choices without deleting history.
- An exception desk should explain identity uncertainty, material commitments, absent facts, ambiguous results and deadline conflicts. It should offer a concrete next action rather than generic error text. Successful routine work should leave concise receipts without requiring constant supervision.
- There is no need to import enterprise platforms wholesale. Start with explicit durable states, bounded background workers and narrow adapters on the existing stack. Adopt a workflow service only if measured long-running complexity and recovery burden justify it.
- The ambitious end state is that each week increases both useful external opportunities and the owner's demonstrated ability, while the software remembers enough to avoid repeating work or damaging relationships. A larger catalog of AI features alone does not create that result.

### Gaps
- Infrastructure choices need actual workload and resource measurements, particularly the small production VM. This review does not authorize new accounts, paid infrastructure, data migrations or external actions.
- Read-only research; no app implementation, production edits, tests or sends performed.
