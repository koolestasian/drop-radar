# Drop Radar: competitor research and automation priorities

Researched October 4, 2026. This extends T20, the personal opportunity action engine.
The product starts with the owner's workflow, then an invited friend beta. It is a
research and implementation plan, not an implemented release.

## Product decision

Build an app that moves a real opportunity through the hiring process with little
repeated work: find it, establish fit, prepare the application, identify a supported
contact route, obtain approval, execute, verify what happened, and prepare the next
step. The useful unit is a completed action for a promising job, not a generated
document or another dashboard card.

Resume tailoring, answer reuse, application review, contact lookup and mock interviews
already exist in competing products. The opportunity is to make the connected workflow
more dependable and useful for this owner. Public research does not establish that
the competitors lack every proposed integration or that Drop Radar outperforms them.

The first differentiating hypothesis to test is: **accurate job discovery plus a
personal evidence library and next-action automation saves more effort and produces
more useful hiring conversations than a volume-oriented application queue.** This
is a hypothesis, not a demonstrated hiring advantage.

## What the competitors actually document

These are official product and support claims checked on the research date. No paid
accounts, private dashboards or actual submissions were tested. Adzuna's ApplyIQ is
the product used for the requested ApplyIQ comparison; a similarly named login site
is not treated as the same service.

| Product | Documented capabilities | What this means for Drop Radar |
| --- | --- | --- |
| JobCopilot | Direct company-career-page discovery; automatic or reviewed applications; answers learned from edits; optional per-job resume tailoring; tracker; hiring-manager contacts; mock interviews. | Copying this feature list would establish parity, not differentiation. |
| AIApply | Full application forms; Auto, Hybrid and Review modes; submitted materials visible; application inbox; resume/cover-letter tools and interview tools. | Approval, history and an inbox are already part of the category. |
| Adzuna ApplyIQ | Matching and automated applications; a free Basic plan; Pro adds approval, form filling, richer targeting and company blocking. | Quality-oriented targeting and user control are also established approaches. |
| Sonara | Continuous matching and application automation, daily matches, and a pitch centered on reducing application effort. | Broad automation is the baseline promise. Detailed execution support was less observable in accessible public pages. |

**JobCopilot deserves the closest comparison.** Its automation page describes searches
every two hours, screening-answer setup, review mode and learning from answer edits.
The pricing page lists Premium at up to 20 matches daily and Elite at up to 50; Elite
includes resume tailoring and contact credits. Advertised starting daily prices are
$0.93 and $1.05 with weekly, monthly and quarterly plans, not a complete checkout quote.
[Automation](https://jobcopilot.com/automate-job-applications/),
[pricing](https://jobcopilot.com/pricing/),
[answer personalization](https://jobcopilot.com/ai-apply/).

Its contact feature searches people by function, management level and location and
uses credits to reveal email and LinkedIn profiles. That does not establish that
every returned person owns the specific requisition. Its tracker documents saved and
applied jobs, application-step history and manually moved stages; the interview tool
takes a target title/description and produces roleplay and feedback.
[Contacts](https://jobcopilot.com/contact-hiring-managers/),
[tracker](https://jobcopilot.com/job-application-tracker/),
[mock interviews](https://jobcopilot.com/ai-mock-interviewer/).

**AIApply is broader than an auto-apply button.** Its August 31 support article describes
daily limits of 10–100, approval for every job in Review mode, and automatic submission
at a 75% fit threshold in Hybrid mode. Exact submitted resumes, letters and question
answers are available afterward. These fit percentages are not independently verified
interview probabilities.
[Application workflow](https://support.aiapply.co/en/articles/15692829-how-auto-apply-works).

Its inbox labels confirmations, incomplete applications, interview and assessment
messages, rejections and offers, and supports replies. A support page describes queue
stalls from pending approvals, processing delays, unreadable resumes and limits. This
makes independent job progress and clear failure recovery useful design targets, but
does not prove their current product is unreliable.
[Inbox](https://support.aiapply.co/en/articles/16762226-how-to-use-the-auto-apply-inbox),
[documented failure cases](https://support.aiapply.co/en/articles/15382265-why-isn-t-the-auto-apply-feature-working-as-expected-in-aiapply).

**ApplyIQ now has a paid tier.** Its current US page shows free Basic and Pro at
$5.99/week, with approval and richer controls in Pro. It also describes a maximum of
two applications to the same employer in 60 days and a 60-day active-search check-in.
Older official articles describing an entirely free product should not override this
current page. A universal company cap is a design choice to test, not a hiring rule.
[Current product page](https://www.adzuna.com/apply-iq-pro).

**Sonara's observable promise is continuous search and applying.** Its homepage sells
application volume and daily matching. The linked how-it-works page returned little
readable content in both retrieval methods, so detailed approval, resume, pricing and
failure behavior remain unverified here. That is an observation limit, not evidence
that those features are absent.
[Homepage](https://www.sonara.ai/), [linked setup page](https://www.sonara.ai/how-it-works).

Competitor slogans and testimonials do not establish causal interview uplift.
JobCopilot's interview multiplier and AIApply's outcome percentages need definitions,
denominators, comparison groups and follow-up periods before they can support an ROI
claim. Their feature documentation remains useful even when outcome claims are unproven.
[JobCopilot](https://jobcopilot.com/), [AIApply](https://aiapply.co/).

## The smallest automations with the best expected return

The order below is engineering judgment about frequency, effort saved and avoided
lost opportunities. No study ranks these exact features for this app. Estimates are
focused implementation time after basic packet/fact storage exists; they are not
additive delivery promises and exclude provider authorization and final release checks.

| Priority | Feature inside Drop Radar | What happens automatically | Main challenge / measure |
| --- | --- | --- | --- |
| 1 | Approved answer library | Reuse confirmed identity, education, dates and recurring screening answers; prepare context-specific answers from reviewed facts; request only missing or conflicting facts. | Similar questions can mean different things. Measure repeated fields and review time saved, plus factual corrections. |
| 2 | Resume selection and export checks | Pick a relevant approved base, select supported project/bullet evidence, propose only useful changes, render and check the final attachment. | Rewriting can make a good resume worse. Measure accepted changes, wrong claims, readable exports and time saved. |
| 3 | Submission verification and incomplete-application recovery | Link submission evidence/receipts, detect explicit incomplete-application notices, preserve uncertain outcomes and prepare the precise repair action. | No receipt is not proof of failure. Measure confirmed submissions, unresolved attempts and recoveries. |
| 4 | Assessment and reply deadline handling | Extract exact required actions and deadlines from supplied recruiting messages; deduplicate updates, create private reminders and surface unresolved invitations. | Automatic assessments are not human interviews; ambiguous times stay uncertain. Measure actionable invitations captured and missed deadlines. |
| 5 | Referral and recruiter packet | Match private imported connections and the existing recruiter list to the company/job; assemble a forwardable fit summary, resume and short approved-send draft. | Relevant employee is not confirmed job owner. Measure candidate accuracy, draft acceptance and actual replies. |
| 6 | Old-job and duplicate preflight | Recheck a selected posting, detect the same requisition/application history, and avoid preparing duplicate packets or contacting the same person again. | Reopened roles can be legitimate; changed URLs can hide duplication. Measure avoided wasted work and false duplicate flags. |
| 7 | Interview packet from the actual application | Assemble employer instructions, the submitted resume/answers, official preparation sources and targeted independent practice when an invitation arrives. | Generic mocks already exist. Measure preparation time and performance on unseen related tasks. |
| 8 | Reusable proof from existing work | Index user-selected project descriptions and verified repository changes; suggest the strongest relevant artifact and interview story for each job. | A commit is not proof of sole ownership or production impact. Measure supported evidence reused and review burden. |

The answer library and resume checks are roughly 0.5–2 day additions each, constrained
message extraction and interview packets about 1–3 days each, and contact routing about
1–3 days with clean inputs. Reliable browser execution takes a separate measured pilot.
If the owner currently spends most time filling forms, move the form pilot ahead of
deeper contact discovery. If invitations are being missed, message/action capture comes
first. Instrument that bottleneck instead of assuming it.

Full automation applies to routine preparation and internal bookkeeping. The owner
already chose approval of each external send; this plan preserves that. One missing
recruiter or an unfamiliar form must not stop unrelated packets from progressing.

## For you should rank useful next actions

Keep the job feed, but let a selected job show its best supported next action:
**application ready**, **ask this connection**, **complete this assessment**,
**reply to this recruiter**, or **review these unknowns**. Separate invitations and
deadlines from discovery so a fresh low-confidence job cannot bury an active interview.

For discovery, rank confirmed role/level fit and demonstrated requirement coverage
first. Then consider user preferences, supported access routes, verified availability,
deadline urgency and explicit company preferences. A friend at an employer is useful
context, not a reason to override eligibility. Old-but-open jobs retain a chance;
missing evidence is visible rather than treated as failure.

For active applications, prioritize an explicit employer request and deadline before
speculative new outreach. Choose between referral and direct application using the
known process and urgency. Do not delay a closing application indefinitely while
waiting for a connection. Any referral wait limit is an owner-adjustable policy, not
a research-backed universal optimum.

Expose evidence such as “two requirements supported by these projects; one unresolved;
known connection at this employer; application not confirmed.” Start with sortable
utility bands and pairwise owner judgments. A numeric utility score may assist sorting,
but do not display “87% chance of an interview” without calibrated outcome data.

The previous T20 weights are a baseline experiment. Compare them against newest-first
and simpler fit-only ordering on 50 owner-labelled jobs. Reserve a small exploration
slot for eligible adjacent roles and record what was shown, so outcomes are not
mistaken for an unbiased sample. Do not build a reinforcement-learning system for
a personal workflow with sparse feedback.

## Experiments that go beyond a standard auto-apply bundle

These combinations are worth testing. They are not claimed inventions or proven
absences from competing products.

1. **Choose an application route per job.** Compare direct apply, a genuine referral,
   supported recruiter outreach and a reply to an existing conversation. Prepare the
   route with the strongest evidence and least duplicated effort; hold alternate
   drafts so the same company does not receive conflicting simultaneous approaches.
   Counterargument: route scoring will initially be subjective. Test draft acceptance
   and useful conversations before treating it as a prediction model.
2. **Prepare before the opening, act when it arrives.** A public, permitted target-company
   hiring signal can prepare a reusable company packet and refresh contact evidence.
   A real matching opening triggers a small update instead of fresh research from
   scratch. Counterargument: funding and engineering posts are noisy hiring signals.
   Require an actual posting before recommending an application, and cap watchlist expansion.
3. **Reuse existing proof instead of generating endless new projects.** Match a job need
   to a real demo, benchmark, pull request or design explanation from the user's work;
   prepare a short context paragraph and the right link. Counterargument: mismatched
   artifacts can distract a recruiter. New bespoke work stays optional with a strict
   time cap; irrelevant links stay out of the application.
4. **Turn an invitation into a preparation plan without re-entry.** Use the exact submitted
   materials, recruiter instructions and actual time available. Schedule attempts,
   review errors, and adapt the next exercise to demonstrated weaknesses. Counterargument:
   generated questions can be inaccurate and assisted answers can hide weakness.
   Use official format guidance, tests and independent attempts; do not promise exact questions.
5. **Learn where the owner's search loses opportunities.** Report whether the current
   bottleneck is usable jobs, completion, human responses, assessments or interviews;
   suggest one change to targeting or preparation. Counterargument: tiny and delayed
   samples produce misleading patterns. Show counts and cohort age, separate automated
   invitations from human screens, and do not equate silence with rejection.
6. **Capture an event or recruiter lead once, reuse it across relevant openings.** Import
   a public recruiting event, an explicitly supplied conversation or a forwarded lead;
   connect it to watched companies, pending applications and future drops. Prepare
   meeting briefs and later follow-up drafts. Counterargument: stale context becomes
   fake familiarity. Retain date/source, use real relationship notes and preserve approval.

## What the research changes about implementation

Resume clarity has direct causal support in a large freelance-platform writing-assistance
experiment, with an 8% relative hiring increase. It does not establish the same effect
for US CS applications or per-job generative rewriting. Build readable, truthful
exports and evidence selection before a universal tailoring generator.
[Paper](https://arxiv.org/html/2301.08083v1).

Large LinkedIn experiments support a role for weak ties in job mobility. They tested
connection recommendations, not automated cold recruiter mail. Prioritize real network
routes while testing outreach; do not invent a referral multiplier.
[Study](https://www.science.org/doi/10.1126/science.abl4476).

Recommendation trials have mixed results, including a large personalized-advice null
result. Learning evidence favors retrieval practice, but that is not a measured offer
uplift. Product implications are owner-labelled ranking tests and scheduled independent
practice, rather than causal promises about a feature bundle.
[Advice trial](https://www.nber.org/papers/w29914),
[retrieval-practice meta-analysis](https://pdf.retrievalpractice.org/transfer/Pan_Rickard_2018.pdf).

Avoid ATS keyword percentages as an acceptance guarantee. Greenhouse documents parsing
problems, which are not equivalent to automatic rejection. A local PDF check tests
extractable content, reading order and factual consistency, not every employer's rules.
[Greenhouse parsing guidance](https://support.greenhouse.io/hc/en-us/articles/200989175-Unsuccessful-resume-parse).

## Application execution: feasible, but a distinct engineering problem

Public listing access does not grant application-submission API access. Greenhouse's
GET job data is public, but its submission endpoint requires a Job Board API key.
Lever's submission API also requires an employer-account key and does not expose all
custom questions through its listing API. Do not plan on sending applications through
these APIs without the needed authorization.
[Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html),
[Lever Postings API](https://github.com/lever/postings-api#apply-to-a-job-posting).

A candidate-side implementation therefore needs supported hosted forms or a browser
integration. Start with one portal family observed in the owner's actual applications.
Read the current form, map fields to approved facts, fill supported controls, show
the final answers/attachment, and submit only after approval. Unexpected required
questions, login, verification or CAPTCHA produce a specific handoff. Preserve progress;
do not attempt hidden-endpoint shortcuts or claim universal ATS coverage.

Use a worker on the owner's workstation initially; the small production box continues
discovery and queue coordination. Later move it to a measured separate browser worker.
A disconnected workstation is a visible queue state. Keep per-user credentials and
browser sessions separate. Never mark Applied solely because a button was clicked;
store explicit confirmation when available and reconcile uncertain network outcomes.

Simplify already offers free autofill/tracking and documented question-answer reuse.
Use it as a benchmark or temporary handoff while Drop Radar builds the valuable parts
around it. Do not spend the first week rebuilding broad form support merely to match
a feature available elsewhere.
[Simplify Copilot](https://simplify.jobs/copilot),
[answer reuse and supported-page behavior](https://help.simplify.jobs/help/articles/2415391-using-copilot-to-autofill-applications).

## Fit this into the current app

The relevant source reads confirm these existing foundations:

- `radar/alerts/__init__.py` owns source/profile visibility, including the curated Story
  bypass and community-list level treatment. Ranking should order eligible candidates,
  preserving these collection/alert semantics until a separately approved change.
- `radar/api/app.py` supplies owner-scoped job serialization, hidden/closed defaults,
  sorting and card grouping. `radar/api/models.py` separates posting state from user
  actions. A clicked link or user action is not verified submission evidence.
- `radar/store/__init__.py` preserves permanent IDs and user-scoped notes/actions.
  Add private packet/attempt/event records alongside them; do not replace shared jobs
  or overload a status string with all workflow history.
- `radar/api/diagnostics.py` and `radar/pipeline/pagefacts.py` provide guarded read-only
  posting checks. Reuse them for selected-job preflight and source facts, with bounded
  public research and explicit inconclusive results.

Add only the persistence needed by each slice: versioned user facts/answers, packet
artifacts, action attempts/approvals and incoming recruiting events. Derive a current
next-action view from durable records. Avoid a generic workflow platform, vector
database or trained ranker before there is evidence that the simpler approach fails.

Research/model/render calls run after persistence in a bounded queue. Cache public
posting evidence by source/content and private artifacts by user, fact revision and
posting version. A feed request never starts a model call. Contact lookup is per
selected company, not per every historical job. Exact recipient/content/attachment
approval invalidates when inputs change. Unknown send/submission outcomes need
reconciliation before another attempt.

LinkedIn connections enter through a user-provided export, not a supposed unrestricted
API or account scraper. Gmail send-only and inbox access have different scopes; start
message processing with supplied message text/files and add an inbox adapter after
separate connection consent. Email verification and public employment evidence remain
separate from actual requisition ownership.
[LinkedIn export](https://www.linkedin.com/help/recruiter/answer/a566336),
[API access](https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access),
[Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes),
[contact lookup and verification](https://hunter.io/api-documentation/v2).

## Revised delivery order and proof of value

**First week:** ship the owner-only loop: reviewed facts/answer library; explainable
For you ranking; supported contact matching; reusable resume selection/QA; automatic
packet preparation; per-send approval; and next-action tracking. Include a constrained
supplied-message pilot for receipts and deadlines if the core passes checks in time.
Move deeper public contact crawling out rather than stretching every slice.

**Next slice:** message import/deadline handling hardened against actual examples,
then one supported form execution pilot and submission evidence. Browser support is
not part of the first-week commitment. Interviews automatically assemble preparation
packets once incoming-event handling is dependable. T19 lifecycle/identity fixes are
dependencies where they affect stale postings or duplicate execution, not a mandatory
rewrite before any useful feature.

For two weeks, record active review time, packet acceptance, factual corrections,
confirmed submissions, incomplete recoveries, actionable replies, assessment completion
and human interviews. Show actual model/research cost and unresolved failures. Measure
interviews per owner-hour alongside absolute useful opportunities; neither applications
nor a single lucky interview is enough to declare success. Delayed outcomes stay pending.

Before claiming superiority, compare like-for-like tasks: the same target roles,
locations, postings, user facts and observation period. Public crawls cannot establish
competitor matching precision, successful-submission rate or causal hiring lift.
A paid-product benchmark can be proposed later; none was purchased in this research.

## Durable handoff

Branch: `claude/trim-drop-radar-plan`. Research-only changes: this report, the T20
research addendum and PROGRESS.md. Public Firecrawl crawls, official documentation and
targeted existing-code reads informed the plan. T20 stays todo; T19 and T16.7 retain
their status. No application, message, deployment, schema write, subscription or account
connection occurred. Next action: implement T20's owner-only packet/fact/answer foundation
and ranking slice, then validate which automation removes the owner's real bottleneck.
