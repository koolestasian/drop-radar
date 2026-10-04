# T20: personal opportunity action engine

Status: todo; owner-requested plan saved 2026-10-04. Not implemented or deployed.
Branch: claude/trim-drop-radar-plan. Foundation audit: T19-trusted-discovery.md.
The owner asked for a useful first version next week, plus longer-term brainstorming.
Competitor research and automation priorities were added 2026-10-04. Read the
[app-focused research report](../../reports/Drop%20Radar%20competitor%20automation%20review.md)
and the [autonomous networking report](../../reports/Drop%20Radar%20autonomous%20networking.md)
before implementing. The latest direction below supersedes conflicting review-only
defaults in the original planning history; packet/fact/answer foundations remain.

## Latest autonomy direction (2026-10-04)

The owner wants routine work executed so they mainly attend agreed coffee chats,
relevant events and genuine interviews/assessments. T20 now includes finding credible
contact routes, initiating outreach, interpreting replies, negotiating times, placing
agreed calendar meetings, preparing briefs, completing requested follow-through and
consented introductions, supported applications and preparation. This expands the
earlier approval-of-each-send preference. Once accounts and a concrete operating
policy are explicitly configured, permitted routine outreach, scheduling, follow-ups
and supported submissions may execute without another review click. Existing per-send
review remains optional. Missing facts or material commitments create exceptions;
counterpart time ambiguity normally triggers an automatic clarification reply.
This research does not connect accounts, activate a policy or authorize real sends.

## Product outcome

Owner clarified the sequence: personal workflow first, invite-only beta for close
friends once useful, then potential wider scale and monetization. The first release
is optimized for the owner's actual job search, not a public self-service platform.

Every promising new or existing job can produce an action packet: why it fits,
what is uncertain, the strongest referral routes, supported recruiter candidates,
a truthful resume and the next action. The app then executes the allowed route and
reconciles its outcome. People, company/event signals, replies and real relationship
commitments also trigger work without requiring a fresh job. Optimize useful human
progress and total saved effort, including attendance time and contact costs.

Owner confirmed best fit plus realistic interview reachability. Sender account,
calendar, master-resume format and recruiter-list provenance remain setup inputs.
Configure policy once; permit ordinary allowed actions and surface actual decisions.
Draft/export and per-send review are fallback modes. Gmail/Calendar are researched
adapter options, not connected accounts. No email/contact files were read and no
messages were sent in this planning pass.

## Achievable first-week slice

Target October 5-11, 2026 for a narrow executing prototype, contingent on approved
inputs, career facts and account setup. Aim for supplied verified contact → policy
check → real reply → negotiated agreement → calendar meeting → preparation brief.
Estimated prototype work is 5–7 focused engineering days; dependable failure handling
and a bounded live pilot are more realistically 8–12 total days, with provider setup
delays separate. These are assumptions, not delivery guarantees or proof of hiring ROI.
Draft/export fallback remains useful when authorization is unavailable, but does not
count as completion of the autonomous workflow.

Broad browser application support, unrestricted people crawling, automatic LinkedIn
scraping/messaging, trained interview probabilities and a full foundation rewrite
remain outside the first-week promise. Narrow touched-thread sync belongs in the
scheduling prototype. Routine policy-permitted follow-ups are part of autonomy.
The Day 1–7 headings below retain foundation sequencing, not a fixed release schedule;
combine T20.1/T20.3/T20.4 foundations with T20.7 before expanding all later phases.

### Day 1: evidence and inputs

- Fix existing/returning posting lifecycle needed to avoid packets for falsely closed
  or stale jobs; preserve IDs/actions/notes/pay. Explicitly mark unknown availability.
- Import a user-provided first-degree connections export and recruiter CSV with mapping,
  preview, deduplication and errors. No import sends messages or starts billable research.
- Establish user-reviewed career facts and goals from resume text: roles, dates, skills,
  achievements, projects, links and real metrics. Master text/structured facts for week
  one; polished document-template import follows if needed.
- Add a versioned approved-answer library for recurring application questions. Reuse
  factual answers only when meaning/context agree; company-specific responses reference
  career facts. Missing/conflicting answers require review, never a fabricated default.
- New description snapshots are fetched through guarded readers; never run against
  every historical job merely because the feature was enabled.

### Day 2: For you ranking

- Separate candidate collection, eligibility, ranking and explanations. Closed/hidden
  jobs are gated out; explicit exclusions stay hard; unknown eligibility stays Review.
- Default heuristic score: role/level fit 30%, demonstrated skills/requirements 30%,
  user location/work-model/preferences 15%, current referral/recruiter route 10%,
  freshness/urgency 10%, explicit company preference 5%.
- Normalize each component to [0,1] with versioned rules; missing evidence is unknown,
  never false proof. The displayed score is ranking utility, not interview probability.
- Role/level uses reviewed target-role mapping. Skill coverage uses requirements
  mapped to career-fact IDs, must-have/optional weights 2:1, and aliases. Preferences
  score confirmed constraints, leaving missing facts marked uncertain. Connection
  access is at most a tie-breaking advantage: it cannot overcome eligibility.
- Freshness falls with age but has a floor for still-open old jobs. Known near deadlines
  add urgency; unavailable dates do not get fake urgency. Company priority is explicit;
  model-learned prestige never dominates demonstrated fit.
- Include a Best fit default, Newest toggle and Review. Fresh alerts stay independent
  of ranking so a promising job is not delayed behind old highly scored jobs.
- On the first page, cap any company at three cards and reserve up to three of 30
  slots for eligible roles from underexposed companies, chosen deterministically.
  Subsequent pages continue the same stable ranking snapshot; user filters still apply.
- Saved/applied feedback indicates interest; hide alone does not establish why. Only
  explicit reasons modify preferences. Views/impressions are recorded to interpret
  feedback; do not train on clicks as if they were independent relevance labels.
- Start with deterministic weighted rules. Evaluate BM25 retrieval using SQLite FTS5
  only when description matching requires it; no embeddings/vector service by default.
- Cache by user, goal/fact/profile revisions, posting version and algorithm version.
  GET feed requests never invoke models. Show top positive factors and unresolved gaps.

### Day 3: referral routes and recruiter candidates

- Match imported connections against the employer's verified identity/aliases, team,
  function, location and explicitly supplied relationship strength. Company similarity
  alone is not enough to assert current employment or an introduction path.
- Return up to three connection candidates with evidence/date and suggested ask.
  Shared school/previous employer only counts if supported by provided facts.
- LinkedIn CSV can be stale and lacks conversation strength. Add manual notes/tags;
  refresh by user re-import. Existing imported profile URLs may be opened manually.
- Recruiter discovery order: user's list, explicit posting contact, official recruiting
  pages/public professional sources that permit retrieval, then optional paid lookup.
- Separate confirmed owner of this requisition, relevant company/team recruiter and
  unconfirmed contact. Never promote an email-verification result into job ownership.
- Store contact name, employer, role, email, source, observed date, verification status
  and relationship notes. Imported bare emails are unverified until enriched.
- Merge by confirmed email or imported stable profile ID; never merge on name alone.
- Public research is bounded per company, cached, evidence-linked, and respects robots.
  No login-wall bypass or LinkedIn website scraping. Unknown stays unknown.
- Optional Hunter lookup/verification is run only on selected professional contacts;
  retain provenance, catch-all/unknown outcomes and identity confidence separately.
  Pattern-generated emails are guesses and cannot become sendable by syntax alone.

### Day 4: evidence-backed resume tailoring

- Create a reviewed career-fact bank beyond the one-page resume: truthful bullet
  alternatives, projects, verified skills and accomplishments with source IDs.
- Extract job requirements to structured evidence. Select/reorder supporting bullets,
  suggest wording and report unsupported requirements; never invent skills, tenure,
  numbers, employers, degrees or achievements.
- Model output is a structured edit proposal referencing existing fact IDs. Dates,
  names and metrics are locked; novel factual claims require user review and cannot
  enter the auto-export path. Sources are untrusted content, not agent instructions.
- Produce readable single-column PDF from a controlled HTML template, with a reusable
  base variant per role family and job-specific changes. Use trusted local rendering;
  external URLs cannot become renderer network requests or file-system paths.
- Prefer a suitable approved base without rewriting when it already presents the right
  evidence. Generate selective changes when evidence emphasis actually differs.
- Show before/after changes and claim provenance. Verify extracted PDF text, contact
  details, links, page count/overflow and reading order. No promise of an ATS score.
- Keep original resume immutable and version artifacts by job/facts/generation versions.
  Resume tailoring cannot change shared job records.

### Day 5: outreach packet, policy and execution

- Different drafts for a warm connection (small clear referral ask) and recruiter
  (job/requisition, two evidence-based fit points, a concise relevant plan, one ask).
- Default 80-120 words; use a plain subject, no fabricated familiarity, no guessed
  statements about the person's ownership, no unnecessary flattery or tracking pixel.
- The plan should connect a real project/skill to a documented job need; no elaborate
  speculative company advice or unsupported promises.
- Attach exactly the selected approved resume version. Provide copy and .eml export;
  send permitted messages through the connected account once policy is enabled.
  Send-only access cannot process replies; touched-thread sync requires read access.
  In-app drafts remain the fallback when accounts/policy are inactive.
- Every action binds exact recipient, content, job/fact versions, attachment hash and
  policy revision. Review-mode approval invalidates after edits; autonomous actions
  revalidate changed inputs against policy. Before sending, check closure, suppression,
  relationship evidence and prior send.
- Proposed configurable send limit 10/day, one active outreach thread per person, seven-day
  cooldown across jobs. Contact at most one person per company at a time unless the
  owner explicitly selects a second. Referral route is offered first, not required.
- Follow-up timing/attempts are part of policy; five business days is an unvalidated
  baseline, not a universal optimum. Permitted follow-ups execute automatically;
  review mode keeps them as drafts. Replies alter the next action, and declines,
  bounces and opt-outs suppress further outreach.
- Send state is durable with Message-ID/provider ID. Ambiguous network outcomes enter
  reconcile-needed; do not blindly retry and duplicate mail. No exactly-once promise.
- Automatic sending is the requested end-state under explicit account/policy activation
  with recipients/criteria, limits, approved facts, pause control and kill switches.
  This document describes that capability without activating real external actions.

### Day 6: continuous workflow

- New drops create cheap local candidates after persistence; models/research never
  delay ingestion or push. Existing jobs use the same explicit Prepare action.
- Automatically prepare at most five strong-match packets/day from the user's watched
  employers once enabled. Full refresh/version changes invalidate older packets.
- Unknown availability can generate a draft with a warning, but cannot be auto-sent.
  Recheck selected old jobs before outreach. Current contacts list employment may
  require manual confirmation even when the email verifies.
- Add tracker states for packet ready, referral requested, outreach sent, replied,
  application submitted and next action; keep application statuses compatible.
- Supplied messages/manual markers bootstrap tests; the scheduling prototype needs
  connected touched-thread sync. Gmail read permissions are broader than send
  permissions even if the app filters. Normal replies/slot clarification progress
  automatically; unresolved owner decisions enter the exception queue.
- Candidate generation is resumable/idempotent; one active packet per user/job/input
  version. Partial success is retained: missing recruiter must not block resume.
- Suggested initial preparation budget: $50/week owner-configurable, separately
  approved before activation, plus existing shared model cap. Estimate/reserve before
  calls, cache by content, and stop gracefully at limits. This is not a price quote.

### Day 7: validation and owner release

- Evaluate 50 representative jobs with owner pairwise rankings; measure top-ten utility
  and compare with chronological/regex baseline. Do not claim trained prediction.
- Check connection/company collision cases, stale imports, aliases, same-name contacts,
  generic recruiters, missing contacts and verification failure.
- Check unsupported resume claims, locked metrics/dates, prompt injection, long content,
  PDF extraction/overflow, attachment identity, isolation and deletion.
- Check duplicate sends, approval invalidation, closure after approval, timeouts,
  rate/budget caps, provider revocation, suppression and pause controls.
- Check policy enforcement, recipient/account identity, malicious reply instructions,
  counterpart clarification, timezone/DST conflicts, duplicate provider events,
  mutual agreement versus invite/acceptance, manual calendar edits, reschedules,
  cancellation and unknown-outcome reconciliation before any real networking pilot.
- Backend discovery/pyflakes, web build/full e2e and affected real-data desktop/mobile
  checks on the final diff. Offline provider/model fakes; live send test to owner's
  own address only after explicit authorization. No tests send to recruiters.
- Approved schema write descriptions and backup before live migration; owner-only
  feature flags, shadow ranking first, manual preparation then capped background.

## Integration shape

Reuse Python/FastAPI, SQLite, React/shadcn, guarded posting readers and permanent
opportunity IDs. Add modules by responsibility for ranking, contact evidence, resume
proposals and preparation tasks; do not embed all this in create_app or the pipeline.
Heavy fetch/model/render work runs behind bounded workers outside the ingestion loop.
Do not run local models/browser research on the small VM. PDF rendering may run on
the owner's workstation in week one; production renderer needs measured memory.

Private persistence: user career facts and versions, contacts/contact evidence,
feedback/impressions, work packets/task state, artifact metadata, approvals and
outreach history/suppression. Store resume artifacts outside Git with access checks;
credentials in protected storage, no PII/secrets in logs. Every key/query/job is
user-scoped; shared job facts never expose private contact or resume information.

Interfaces: additive sort=recommended for For you, rank reasons/version and stable
rank cursors; contact CSV import preview/confirm; career-fact review; POST prepare
for existing/new jobs; GET packet status/results; authenticated artifact download;
policy/review authorization and action endpoints; outcome/suppression updates. Poll durable
task status initially; SSE can notify without becoming the source of truth.
Regenerate OpenAPI/types. Failure results distinguish no evidence, provider blocked,
budget exhausted, missing facts, stale packet and send outcome unknown.

## Personal use, friend beta and commercial gates

- **Personal first:** calibrate roles, ranking, career facts, contacts and templates
  against the owner's real inputs. Flexible imports and manual corrections are fine;
  generalized onboarding, billing, growth features and a trained universal ranker
  do not belong in the first-week scope.
- Measure time to prepare a useful application packet, owner acceptance of top-ten
  recommendations, unsupported resume claims, contact accuracy and actual conversations.
  Record weekly outcomes for at least two weeks before broadening the beta. Interviews
  are an outcome metric, not a fixed short-term promise.
- **Friend beta:** start with three to five manually invited friends. Each supplies
  their own goals, career facts, contacts and mail authorization. Close friendship
  does not imply permission to share resumes, contacts, relationship notes or outcomes.
  Rank per user; share permitted public job facts, never personal networks by default.
- User ownership/access checks are required from day one, even while there is one
  active user. Invite-only enrollment is a planned beta control, not a current app change.
  No public paid launch or signup expansion until explicitly chosen.
- Track per-user research/model/render cost, queue delay and limits from the first
  release. Separate cached public evidence from private artifacts. These simple
  boundaries enable later scale without requiring new infrastructure now.
- Beta gate: packet/resume/send isolation tests pass, policy/review authorization works, costs are bounded,
  and each invited user has completed an assisted workflow with feedback. Review after
  two weeks: regular voluntary use, measured time savings, quality defects and support
  burden determine whether to expand or fix the experience first.
- **Commercial experiment:** after repeat usage and demonstrated value, interview
  beta users about willingness to pay and offer a small explicitly agreed paid pilot.
  Define the paid unit and price from observed cost/value; do not assume willingness
  to pay from compliments or registrations. Keep monetization separate from outreach
  behavior; sending more messages is not the success metric.
- Before a public paid launch, complete tenant isolation review, portable export/deletion,
  provider production authorization, backup/restore checks, usage metering, billing,
  support/retention policies and measured load validation. Sequence these later rather
  than making them prerequisites for the owner's prototype.

## Larger high-agency ideas, ranked for later experiments

1. **Relationship before the opening:** prepare a weekly shortlist of people at
   target companies, using real mutual context. Build trust before requesting help.
2. **Referral kit:** one forwardable paragraph, job link/req, two fit bullets and
   resume, reducing effort for a connection. No fake referral or unauthorized names.
3. **Small proof of work:** suggest a 60-90 minute artifact tied to a documented team
   need and existing skills. User chooses; do not do free multi-day speculative work.
4. **Company hiring signals:** permitted official engineering posts, public team
   pages, careers changes and opt-in recruiting events create watchlist suggestions.
   Label hypotheses; funding/activity is not proof a role exists.
5. **Application timing coach:** distinguish useful fresh roles, approaching deadlines
   and old-but-open jobs, and suggest whether to apply now or seek a referral first.
   Avoid referral pursuit delaying a closing application.
6. **Outcome learning:** user-recorded replies/interviews identify productive role
   families, channels and proof points. Small samples yield suggestions, not causal
   claims or precise probabilities. Limit repetitive outreach rather than optimize volume.
7. **Skill-gap action queue:** convert repeated unsupported requirements into one
   credible portfolio task; re-use the result in future resumes once user verifies it.
8. **Interview preparation continuity:** source-linked company/team brief, resume
   stories, likely technical themes and questions from the saved job version.
9. **Recruiting-event radar:** official campus/alumni/open-house pages, opt-in alerts
   and prepared introduction packets; no private attendee scraping.
10. **Personal relationship CRM:** follow-ups and helpful sharing with people you know;
    relationship notes are manually supplied, never inferred from fabricated familiarity.

The initial executing pilot combines private facts/network input with permitted
outreach, actual reply handling and agreed scheduling. The experiments above now feed
that workflow; broad source/form coverage expands after it works. These are priority
judgments, not measured return rankings.

## App-focused research addendum (2026-10-04)

This is the same T20 task, not a separate personal-advice task. The owner explicitly
asked to study ApplyIQ, AIApply, Sonara and especially JobCopilot and push the app's
automation further. The report linked above records public official-site crawls,
support documentation, research limits and source-checked implementation feasibility.

JobCopilot already documents learned answers, approval, tailored resumes, a tracker,
hiring-manager contact lookup and mock interviews. AIApply additionally documents
an application inbox with confirmation, incomplete-application, assessment and
interview labels. ApplyIQ has free Basic and paid Pro with approval/targeting controls.
Sonara documents continuous matching/applying; its accessible setup details were
inconclusive. None of these public pages establishes comparative successful-submission
rates or causal hiring uplift. Do not describe copied category features as inventions.

### Priority order for small automated features

1. Approved facts and reusable answers reduce repeated application work and anchor
   truthful resume/outreach proposals. Preserve context and version changes.
2. Resume selection, selective evidence changes and export/attachment checks run for
   every packet. Rewriting every resume is not a requirement.
3. Submission evidence and incomplete-application notices create specific recovery
   actions. A clicked Apply link is not submission; no receipt is not proof of failure.
4. Recruiting-message action/deadline extraction creates private reminders and unresolved
   next actions. Explicit deadlines retain their timezone/source; ambiguous ones need
   review. Automatic assessments stay distinct from human interviews.
5. Private connection/recruiter matching prepares a forwardable packet and concise
   outreach draft. Company relevance, email deliverability and requisition ownership
   are separate evidence claims.
6. Selected old-job availability and duplicate preflight prevent wasted preparation
   and repeated contact, with explicit reopened-role/uncertain-identity handling.
7. An interview invitation assembles employer instructions, actual submitted artifacts,
   real career examples and targeted independent practice without repeated setup.
8. User-selected project/repository evidence can supply reusable proof and interview
   stories, after ownership/claims are reviewed.

These are expected-return judgments, not measured rankings. Track the owner's actual
time bottleneck; move constrained form automation earlier if filling forms dominates.
No application volume, keyword percentage or opaque fit score proves interview ROI.

### Delivery slices within T20

- **T20.1:** private fact/answer revisions, packet artifacts and durable action/approval
  records. Keep existing user actions/notes and permanent shared job IDs intact.
- **T20.2:** cached For you ranking, explainable fit/unknowns and automatic preparation
  for a bounded shortlist. Original weights are a baseline to compare with simpler
  ordering, not calibrated interview probabilities.
- **T20.3:** imported-network/recruiter matching, approved resume selection/QA and exact
  policy/review authorization. One missing contact does not block other components/jobs.
- **T20.4:** supplied recruiting-message receipt/deadline pilot, then opt-in inbox
  integration. No mailbox access was authorized or connected in this research pass.
- **T20.5:** one hosted-form portal pilot with approved answers, exact attachment and
  confirmation evidence. Unknown fields/account verification yield a clear handoff;
  ambiguous submission outcomes reconcile before retry. Browser work stays off the
  small production box. Universal ATS support is outside the first-week commitment.
- **T20.6:** invitation-triggered preparation, delayed independent practice and
  transparent funnel/outcome reporting once recruiting-event handling is dependable.
- **T20.7:** autonomous networking and scheduling. Connect one owner-authorized
  account/calendar; configure recipients, purposes, disclosures, follow-ups, scheduling
  bounds and pause controls once. Use one AI interpretation/planning worker and a
  deterministic executor. Persist trigger/route/reply/agreement/action evidence;
  clarify counterpart ambiguity automatically. Separate private holds, exact mutual
  agreement, invitation delivery and acceptance. Recheck conflicts; reconcile uncertain
  writes before retry; handle reschedules/cancellation and deliver a private brief.
  Review only unresolved identity/facts, material commitments or out-of-policy actions.
  First prototype: supplied verified contact → policy checks → real reply → agreed
  calendar meeting → brief, activated only after explicit setup.
- **T20.8:** event, introduction and outcome workflows. Monitor permitted official
  company/event signals; complete supported registrations under policy, distinguish
  waitlist/confirmation and arrange relevant meetings before recommending attendance.
  Complete requested artifacts and consensual introductions using actual thread or
  encounter evidence; no fabricated recap, endorsement or private attendee scraping.
  Rank people/routes/actions alongside eligible jobs and active hiring steps. Measure
  held useful conversations, completed referrals, interviews, total owner time/cost,
  corrections and unwanted contact. Extend supported applications/preparation without
  replacing genuine assessments. Full direction and evidence limits are in the
  [autonomous networking report](../../reports/Drop%20Radar%20autonomous%20networking.md).

The first-week target is now the narrow executing networking prototype described at
the top; the broader vision is staged rather than reduced to approval packets.
T20.7 can follow the necessary T20.1/T20.3/T20.4 foundations before all T20.5/T20.6 work.
Deeper contact discovery, event registrations and browser coverage need separate
iterations. These slice labels organize T20; no implementation/completion is implied.

Public Greenhouse and Lever listing APIs do not grant candidate-side submission access:
their application POST endpoints require employer keys. Plan a supported browser/form
integration instead of assuming those endpoints are publicly writable. Simplify's free
autofill/tracking and answer reuse provide a useful benchmark or temporary handoff.
See the linked report for official documentation and limits.

### Further experiments and measurement

Test choosing a supported application/referral/recruiter/reply route per job; preparing
company packets before real openings; reusing existing proof artifacts; automatically
assembling preparation from actual invitations; and detecting the owner's current funnel
bottleneck. These combinations are hypotheses, not claimed novel inventions or verified
competitor omissions. Hiring signals need an actual opening before recommending an
application, and sparse/delayed outcomes do not justify a trained probability model.

For two weeks measure owner review time, packet acceptance, factual corrections,
confirmed submissions, unresolved attempts, recoveries, actionable replies, assessment
completion, human interviews and actual preparation costs. Retain cohort age/pending
outcomes and distinguish automated invitations. Compare against the current workflow
and simpler ranking. The latest autonomy direction replaces the earlier per-send
default: routine permitted actions execute after explicit account/policy activation;
review mode remains optional and material decisions enter the exception queue.

## Research checked 2026-10-04

- LinkedIn connections export, email limitations, first-degree scope:
  https://www.linkedin.com/help/recruiter/answer/a566336
- LinkedIn prohibited scraping/automated activity:
  https://www.linkedin.com/help/linkedin/answer/a1341387/prohibited-software-and-extensions
- Open API permissions do not provide a general connections feed:
  https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access
- Gmail sending/attachments:
  https://developers.google.com/workspace/gmail/api/guides/sending
- Gmail send versus restricted compose/read scopes:
  https://developers.google.com/workspace/gmail/api/auth/scopes
- OAuth external testing refresh-token expiry considerations:
  https://developers.google.com/identity/protocols/oauth2
- Contact finder/verifier provenance and status:
  https://hunter.io/api-documentation/v2
- Optional native lexical retrieval:
  https://sqlite.org/fts5.html

External testing OAuth setup is not a permanently unattended integration by default;
recheck current Google publishing requirements during setup. No provider account,
API access, accurate recruiter assignment or next-week authorization is assumed.

## Handoff

Docs-only planning/research save on claude/trim-drop-radar-plan; competitor/autonomous
networking reports, research notes, this spec and PROGRESS.md updated. Public source,
evidence qualification and documentation link/whitespace checks only; no app
implementation, live schema/config write, account connection, outreach, deployment,
PR or tag. Sender/resume/contact inputs remain implementation prerequisites through
the normal secure flow. Next prototype combines necessary T20.1/T20.3/T20.4 inputs
with T20.7: verified contact → enabled policy → reply → agreed meeting → brief,
before broad ranking, contact discovery and form coverage.
Existing T16.7 task status is unchanged until the owner explicitly chooses a new task.
