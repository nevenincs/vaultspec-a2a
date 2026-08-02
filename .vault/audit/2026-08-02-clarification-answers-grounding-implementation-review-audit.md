---
tags:
  - '#audit'
  - '#clarification-answers-grounding'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:7c0d851c48f6b816910629365332f0bf4d2dcefa2cdaa78e395a184345835a74'
related:
  - "[[2026-08-02-clarification-answers-grounding-plan]]"
  - "[[2026-08-02-clarification-answers-grounding-adr]]"
---

# `clarification-answers-grounding` audit: `answers grounding implementation review`

## Scope

The answered-questionnaire grounding fix was reviewed against its accepted
decision: the deterministic rendering owned by the thread contract, the gate's
answers-branch append, the skip-on-empty rule, and bounds composition from the
existing caps. The wider blast radius mattered most here because the change
alters what existing answer resumes put in front of downstream turns: the
research_adr topology suite, the endpoint round-trip suite, the relay suites,
and the preset declaration suite (59 tests) all passed alongside the contract,
graph, and live loop suites.

## Findings

### grounding-review-provenance | medium | the independent review pass is outstanding

Same provenance condition as the decline record landing in this lane: the
dispatched independent reviewer died on the shared session limit, so this is a
self-review pending independent re-check.

### grounding-replay-semantics | low | the append inherits the continuation's replay posture

The rendered turn is appended in the same resumed superstep that records
answers and clears pending state - the identical mechanism and replay posture
the shipped continuation outcome uses, and the concurrent-replay live test in
the loop suite exercises six racing replays without duplication. No new replay
surface is introduced.

### grounding-behaviour-change | low | existing presets now act on answers for the first time

Deliberate and the point of the record, noted for trace: any preset whose runs
previously recorded answers into inert state will now have those answers in
front of every downstream role. The one production preset declaring a
questionnaire is the deterministic certification variant, so no live-provider
preset changes behaviour until one declares a questionnaire.

## Recommendations

Close the provenance finding with an independent verdict alongside the decline
record's. When the consuming engine's brokered respond body is widened, extend
its conformance fixtures to cover a rendered-answers transcript read so the
product-side snapshot semantics are pinned where they are consumed.
