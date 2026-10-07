---
tags:
  - '#adr'
  - '#clarification-answers-grounding'
date: '2026-08-02'
modified: '2026-10-07'
body_schema: 'body-v1'
body_hash: 'sha256:8adcc841f24d43f38320a3ca0999279171a77050f982a95cd14f758f08657198'
related:
  - "[[2026-08-02-clarification-answers-grounding-research]]"
  - "[[2026-08-02-clarification-decline-adr]]"
  - '[[2026-10-06-codebase-remediation-audit]]'
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

## Amendment (2026-10-07): the write-only `clarification_answers` channel is removed

Accepted 2026-10-07 under the owner's remediation direction (drop unrequired code, remove duplication, delegate ADR amendments).

The rendered human turn is the only carrier of an answered questionnaire (`src/vaultspec_a2a/graph/nodes/clarification.py:396-404`). The `clarification_answers` state channel (`src/vaultspec_a2a/thread/state.py:159-173,358-362`), written at `src/vaultspec_a2a/graph/nodes/clarification.py:393-395`, has no production reader; only tests read it. Grounding: R4-F19 in `2026-10-06-codebase-remediation-audit`; decision D17 in `2026-10-06-codebase-remediation-plan`.

The considered option "Delete the state channel and keep only the transcript turn" was rejected on a false premise. Superseded rationale: "the channel also feeds the wire receipts/disclosure surface and its removal is a separate contract event with no product need." Correction: the receipts are `clarification_resolution_receipts` (`src/vaultspec_a2a/thread/state.py:363-368`). The gate writes them beside the answers (`src/vaultspec_a2a/graph/nodes/clarification.py:389-391`), and the clarification service reads them (`src/vaultspec_a2a/control/clarification_service.py:290-305`). Disclosure reads the parked `clarification_request` interrupt from the checkpoint (`src/vaultspec_a2a/thread/clarification.py:567-595`). No served field reads the channel, so its removal is not a contract event. That option is now the ruling: the channel, its reducer and the gate write are removed, and the transcript turn is the single carrier.

This replaces three clauses:

- Constraints, "The state channel, wire schema, receipts, and lease service are unchanged". Replacement: the wire schema, receipts and lease service are unchanged; the state channel is removed.
- Consequences, "The double representation (state channel + transcript) is deliberate; retiring the unread channel remains available as a future contract event." Withdrawn: the transcript is the single representation.
- The rejection of the delete-the-channel option, corrected above.

Old checkpoints are handled through the checkpoint store owner, `database/checkpoints.py`, under strict serde (`strict_checkpoint_serde`, `src/vaultspec_a2a/database/checkpoints.py:111-131`). A stored channel value is a plain mapping of strings, inside the strict safe set. Under the locked langgraph 1.2.12, hydration builds only declared channels (`langgraph/pregel/_checkpoint.py:265-276`), and a pending write to an undeclared channel is ignored with a warning (`langgraph/pregel/_algo.py:308-313`). The removal Step proves on a real checkpoint store that a run checkpointed with the old key still resumes and still reads.
