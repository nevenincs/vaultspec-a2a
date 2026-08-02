---
tags:
  - '#exec'
  - '#clarification-answers-grounding'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:89403ba46d1e1a5fbeecd92572ebd75eac39bea09c2c1763f9956ec0bb073bed'
step_id: 'S02'
related:
  - "[[2026-08-02-clarification-answers-grounding-plan]]"
---

# Prove rendering bounds, skip-on-empty, gate append, and the real worker delivery

## Scope

- `src/vaultspec_a2a/thread/tests/test_clarification.py`
- `src/vaultspec_a2a/graph/tests/nodes/test_clarification.py`
- `src/vaultspec_a2a/api/tests/test_clarification_loop_live.py`

## Description

- Prove question-order rendering, only-answered inclusion, and the blank-answer skip.
- Prove four maximal prompt/answer pairs stay inside the run-message ceiling.
- Prove an answered questionnaire appends the exact rendered turn beside its recorded state and receipt.
- Prove an all-optional questionnaire resolved empty appends no transcript turn.
- Prove the real gateway, worker app, and Executor loop delivers the rendered turn into durable graph state.

## Outcome

Contract, graph, and live-worker suites are green (75 contract and graph tests,
4 live loop tests), and the wider clarification blast radius - endpoint, edge,
relay, research_adr topology, and preset declaration suites - passed (59 tests)
with the rendering in place.

## Notes

The stitched service-level loop remains environment-gated (it requires a live
authoring engine plus this branch's gateway and worker per its runbook) and was
skipped, exactly as it is for the answer and continuation outcomes; the ASGI
live loop is the proof lane for this change.
