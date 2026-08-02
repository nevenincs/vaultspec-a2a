---
tags:
  - '#adr'
  - '#clarification-answers-grounding'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:c381f01adaa5ceb78fa590a48bdb6473b8fa35a7fe6e73361ced92026640070d'
related:
  - "[[2026-08-02-clarification-answers-grounding-research]]"
  - "[[2026-08-02-clarification-decline-adr]]"
---

# `clarification-answers-grounding` adr: `answered questionnaires ground downstream turns` | (**status:** `accepted`)

## Problem Statement

An answered questionnaire is checkpointed and disclosed but influences no downstream
model turn - the ask-before-diverge stage's entire purpose is mechanically unfulfilled,
and the consuming product's clarification card submits answers nothing reads. This is
a behaviour change, not a repair: it alters what reaches a model turn, so it is
decided on its own record rather than folded silently into the decline change.
Grounding is in `2026-08-02-clarification-answers-grounding-research`.

## Considerations

- Only the message transcript reaches downstream turns; the state channel reaches
  nothing (`2026-08-02-clarification-decline-research`).
- One gate-side append covers every role; per-producer state reads are N drift-prone
  sites (`2026-08-02-clarification-answers-grounding-research`).
- Answers are the human's own submitted words - rendering them as a human turn is
  honest provenance, unlike fabricated prose.
- The rendered turn is bounded by construction from the existing contract caps.
- An all-optional questionnaire can resolve with an empty answer map.

## Considered options

- **Render the answered questionnaire into one human transcript turn at the gate
  (chosen).** One site, every role, durable and replay-safe through the existing
  reducer; same mechanism as continuation and decline.
- **Teach each turn composer to read the state channel.** Rejected: N sites that can
  drift or be forgotten - the omission class that shipped this gap.
- **Delete the state channel and keep only the transcript turn.** Rejected: the
  channel also feeds the wire receipts/disclosure surface and its removal is a
  separate contract event with no product need.
- **Leave it and file it.** Rejected: the decline outcome ships its meaning through
  the transcript, and shipping that on top of a decoratively-answered questionnaire
  builds on sand.

## Constraints

- The rendering is owned beside the resolution models in the domain contract, not
  composed ad hoc at the gate, so the transcript form cannot drift per call site.
- Rendering order follows the committed request's question order, never answer-map
  insertion order; only answered questions render.
- An empty effective answer map appends nothing - a contentless human turn in front
  of every role is worse than silence, and the receipt still records the resolution.
- The append happens in the same resumed superstep that records the answers and
  clears pending state, so transcript and state cannot diverge across a replay.
- The state channel, wire schema, receipts, and lease service are unchanged; the
  change is additive to the gate's answers branch only.
- Parent stability: the gate node, reducer, and contract caps are accepted shipped
  surfaces; the decline record (same gate) lands beside this one in the same lane.

## Implementation

Add a rendering helper beside the resolution models that formats an answered
questionnaire deterministically - one line per answered question, the question's
prompt paired with the human's answer, ordered by the committed request. The
clarification gate's answers branch, after computing the declared answers it already
records, additionally appends one `HumanMessage` carrying that rendering whenever at
least one declared answer is present. Tests prove the rendering order and bounds, the
skip-on-empty rule, the gate append alongside the recorded state, and the real
worker loop delivering the rendered turn into durable graph state.

## Rationale

The gate append is the only option that fixes the defect at one site with the
mechanism downstream turns actually read, keeps human provenance honest, and stays
within the accepted resolution flow - the questionnaire's answers finally do what the
compiled graph's design always claimed they did.

## Consequences

- Answering a questionnaire changes downstream behaviour for the first time; runs
  that previously ignored answers will now act on them, which is the intent but is a
  real behaviour change for existing presets.
- The transcript carries one additional human turn per answered questionnaire.
- The double representation (state channel + transcript) is deliberate; retiring the
  unread channel remains available as a future contract event.
- The consuming product's clarification card becomes functional end to end once the
  brokered edge carries resolutions through.
