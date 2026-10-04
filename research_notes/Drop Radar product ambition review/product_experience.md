# Drop Radar product experience and ambition gaps

## What exists in the actual product, and where does it stop?

### Takeaway
The implemented product is a discovery and manual tracking interface. It has useful collection, filters, alerts and accessibility features, but the visible interaction stops at an external Apply link and a small status/notes record. A much larger vision needs a decision-and-action workspace rather than merely more features attached to the feed.

### Cited Findings
- Read-only real Chrome production inspection on 2026-10-04 opened as guest, with no existing signed-in browser session. Guest feed showed 4,081 For you, 11,704 found, and five new items; these are guest counts, not owner-feed counts. Inspected desktop and a 390px mobile viewport. Screenshot file saves were rejected by the browser tool because its configured workspace roots differ; no screenshot artifacts exist. — Browser accessibility snapshots observed during this audit; corroborated interface structure in [Feed implementation](../../web/src/screens/Feed.tsx).
- Selected detail was GE Aerospace “Dowty- Accounting Finance Degree Apprenticeship 2027 intake.” Its match explanation was exactly `role: 'finance'` and `level: 'apprentice'`, with location, posted/found time, season, source and an external Apply link. No description or substantive candidate requirement comparison appeared. — [Detail implementation](../../web/src/components/Detail.tsx)
- Implemented navigation is Jobs, Tracker, Sources, Settings. Guest navigation offers only Jobs. There is no Today, Inbox, Network, Documents, Preparation or campaign workspace in current routes. — [App routes](../../web/src/App.tsx)
- Feed sorts are `posted` and `prestige`; profile fields are roles, title-level keywords, exclusion terms, locations and target season year. This is preference/title matching, not a structured candidate model. — [Filters](../../web/src/filters.ts); [Profile form](../../web/src/screens/Settings.tsx); [API schema](../../web/src/api/schema.d.ts)
- Tracker columns are Saved, Applied, Interview, Offer, Rejected; card controls provide status and blur-saved notes. It fetches at most 200 rows per column, without cursor traversal. There are no structured next-action/date, assessment, submitted-resume, interview-stage, contact or offer-term fields in the Action contract. — [Tracker](../../web/src/screens/Board.tsx); [Statuses](../../web/src/format.ts); [Action schema](../../web/src/api/schema.d.ts)
- Guest screen says “Roles that match your profile,” even though sign-in is offered to obtain an own feed/profile. This is a concrete semantic trust issue, not proof of inaccurate owner matching. — [Feed blurb](../../web/src/screens/Feed.tsx)
- Welcome copy asserts “The earlier you apply, the better your odds.” This is an unqualified claim in current UI; this pass did not establish supporting evidence or causal effect. — [Welcome](../../web/src/components/Welcome.tsx)

### Inferences
- The user still performs the hardest decisions: Is this actually eligible? How does my evidence fit? Which route should I take? What should I do next? The app supplies access and organization but currently provides little decision leverage.
- “Why it matched” presently means why a title filter accepted it, not why this person is a strong candidate. A major product upgrade should distinguish those concepts in both data and copy.
- A stronger daily home should combine urgent decisions, agent exceptions, ready packets, messages requiring a reply, imminent deadlines, upcoming meetings and preparation. A flat chronological feed cannot represent that work.
- Application workflow should preserve authoritative submission evidence, form answers, exact resume/attachment version and stage history. A status button is insufficient to ground autonomous work.

### Gaps
- Owner is signing in separately. Signed-in production screens were not yet inspected as of this note; signed-in capability claims above are verified in current source, not asserted as live owner observations.
- No production mutation, token entry, account connection, send, profile update or status change was performed.
- Phone view is Chrome viewport emulation, not a real owner phone/device audit.

## Which missing capabilities are already planned, and which ambitions need strengthening?

### Takeaway
T20 already contains substantial ambition: facts, ranking, referrals, outreach, scheduling, applications, preparation, events and outcome reporting. Recommending these as brand-new ideas would misread the project. The stronger critique is that it describes many individual workflows more clearly than the unified operating experience and strategy above them.

### Cited Findings
- T20 remains todo, implementation not started; proposed foundations include career-fact revisions, approved reusable answers, packets, ranking, contact evidence, resume selection/tailoring and durable permitted execution. — [Progress](../../docs/specs/PROGRESS.md); [T20](../../docs/specs/T20-opportunity-action-engine.md)
- T20 explicitly expands beyond jobs into relationships before openings, company hiring signals, proof-of-work, skill-gap actions, events, relationship CRM, interview preparation continuity and outcome learning. These are roadmap capabilities, not existing shipped product. — [T20 larger ideas](../../docs/specs/T20-opportunity-action-engine.md)
- T20.7/T20.8 cover ordinary permitted outreach/reply handling, agreed scheduling, event/introduction workflows and meeting briefs. The spec distinguishes real sends/account-policy activation from research. — [T20 delivery slices](../../docs/specs/T20-opportunity-action-engine.md)
- T19 already proposes provenance, uncertain eligibility, source availability lifecycle, next-action dates, contacts, resume references, saved posting snapshots, import/export, trusted counts and readiness/delivery metrics. — [T19](../../docs/specs/T19-trusted-discovery.md)

### Inferences
- **Unifying model:** candidate, evidence, company, team, requisition, person, relationship, conversation, commitment, artifact and event should connect into one navigable workspace. This is a product information model, not a recommendation to add a graph database.
- **Campaigns:** a deliberate target such as a selected internship role family at named employers should coordinate collection, relationship work, evidence building, applications and preparation. Current role keyword lists do not represent that campaign.
- **Company/team intelligence:** compile official team work, verified needs, previous interactions, relevant alumni/contact routes and the candidate's evidence into a living account brief. A company logo or prestige tier is not company understanding.
- **Candidate improvement loop:** turn recurrent missing requirements and interview errors into concrete practice/project tasks, ingest verified completed results back into evidence, and show which future opportunities they unlock. T20 mentions skill-gap tasks, but the feedback loop deserves to be a central product behavior.
- **Autonomy control plane:** make planned/executing/waiting/reconcile-needed/blocked/completed work inspectable, show what each agent knows and intends, and allow global/individual pause and correction. Policy plus background execution needs visible operational control to earn trust.
- **Real learning:** preserve timestamps, cohorts, route used, versioned materials, human versus automatic invitations and outcomes. Suggest adjustments with uncertainty; avoid unjustified interview probabilities from sparse data. This strengthens existing T20 outcome reporting.
- **Offer decisions:** current Offer is one status. A complete opportunity engine eventually needs terms, deadlines, location, manager/team, learning upside, negotiation correspondence and explicit personal tradeoffs, with evidence and uncertainty.
- **Mobility:** rapid mobile review/approval, calendar/brief access before meetings, and a concise digest/action queue should express the same state as desktop. This is not yet a claim of a current accessibility defect.

### Gaps
- No evidence in this pass establishes comparative hiring uplift for any proposed capability.
- “No route currently exists” establishes UI absence; it does not establish that no backend helper exists anywhere in the repository.
- Bigger vision is synthesis/recommendation, not an observed product fact or attributed Thiel/Karp doctrine.
