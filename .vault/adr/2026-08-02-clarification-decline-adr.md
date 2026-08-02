---
tags:
  - '#adr'
  - '#clarification-decline'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:3d3f97a8b1531f3f184f762b28e125af5274c4b4144c40ce16945c49a502fe6d'
related:
  - "[[2026-08-02-clarification-decline-research]]"
  - "[[2026-08-02-clarification-continuation-adr]]"
---

# `clarification-decline` adr: `typed decline resolution for parked questions` | (**status:** `accepted`)

## Problem Statement

A user shown a parked questionnaire has three product outcomes - answer it, chat
instead, or refuse to answer and let the run proceed on its own judgement - but the
resolution contract expresses only the first two. Refusal today means either
cancelling the whole run or leaving it parked forever, and the consuming product
cannot honour its "refuse to answer" affordance. Grounding is in
`2026-08-02-clarification-decline-research`.

## Considerations

- The verb question is settled: a new outcome of the same resource transition rides
  the same respond verb as a body alternative
  (`2026-08-02-clarification-continuation-adr`).
- Every type-aware seam a new variant touches is enumerated, and the durable
  lease/journal service is not among them
  (`2026-08-02-clarification-decline-research`).
- Only the message transcript reaches downstream model turns; a decline invisible to
  them is indistinguishable from a question never asked
  (`2026-08-02-clarification-decline-research`).
- A decline is not a cancel: the run must continue through the same fixed proceed
  target, and it is not an answer: required-question validation must not apply to it.
- Checkpoint request identity remains authoritative for every resolution.

## Considered options

- **Third exactly-one-of body alternative with its own resume discriminator
  (chosen).** Additive, preserves answer/prompt clients, reuses the whole leased
  dispatch path unchanged.
- **A dedicated decline verb or route.** Rejected by the continuation record for the
  same outcome class; re-opening it expands two repositories for no new semantics.
- **Encode decline as empty answers.** Rejected: required-question validation
  correctly refuses it, and weakening that validation would make silence and refusal
  indistinguishable for genuine answer submissions.
- **Encode decline as a canned continuation prompt.** Rejected: it fabricates user
  prose, and a continuation's meaning is "new instruction", not "no instruction".
- **Silent proceed (no transcript trace).** Rejected for a mechanical reason, not
  taste: downstream turns read only the transcript, so a silent decline is
  indistinguishable from a question never asked - the agent may re-ask or treat the
  question as still open, and "declined" never becomes a fact the run can act on.
- **Record decline in a new state channel instead of the transcript.** Rejected: no
  production reader exists or is planned; it would ship the zero-caller emitter
  defect the repository's clarification rule names.

## Constraints

- The respond body accepts exactly one of `answers`, `prompt`, or `decline`; the
  decline alternative carries no free text (a boolean presence, not a payload), so
  nothing user-authored needs bounding.
- The resume payload carries a distinct discriminator and the committed request id,
  parsed by the same strict parser; a decline for a different request id is refused.
- The gate clears pending state, writes the standard resolution receipt, and appends
  exactly one fixed-text marker message; it writes no `clarification_answers` entry.
- The marker text is a constant owned beside the resolution models - single-line,
  within the existing prompt ceiling - so the transcript trace cannot drift per call
  site.
- Parent stability: the continuation union, the leased dispatch journal, and the
  checkpoint disclosure are accepted, shipped surfaces; this record adds a variant to
  a closed union and changes none of their semantics.
- Engine-side carry-through (brokered body widening) is consumer work sequenced after
  this producer lands, per the cross-repository edge discipline.

## Implementation

Add a bounded `ClarificationDecline` resume model beside the answers and continuation
models, extend the resolution union, the strict parser, and the exactly-one-of respond
schema, and map the new body alternative to the new discriminator in the HTTP route.
The clarification gate, on parsing a decline bound to the committed request id, clears
the pending request, records the resolution receipt through the existing fingerprint,
appends one fixed marker `HumanMessage` stating that the user declined and the run
should proceed on its own judgement, and routes to the same proceed target. The leased
dispatch service is untouched: the decline's distinct fingerprint gives idempotent
replay and conflict refusal through the existing journal.

## Rationale

The third body alternative is the only option that honours the settled verb decision,
keeps refusal distinct from both answering and instructing, leaves required-question
validation intact, and gives downstream turns an honest trace through the one
mechanism they actually read. The marker message states the user's real action in
fixed words rather than fabricating prose the user never wrote.

## Consequences

- The product's three-way affordance (answer / chat / refuse) is fully expressible
  against a parked run; cancel stops being the only refusal.
- Answer-only and prompt-capable clients remain compatible; the change is additive.
- Downstream stages see one fixed marker turn on decline; personas need no schema
  awareness of the decline to act on it.
- The consuming engine must widen its brokered respond body before the product can
  reach any alternative beyond answers; that carry-through covers continuation and
  decline together.
- A declined questionnaire is not re-asked: the preset-declared producer runs once per
  pass, so refusal is durable for the run - which is the intended meaning of decline.
- The pre-existing zero-reader status of recorded answers remains open and is
  explicitly out of scope here.
