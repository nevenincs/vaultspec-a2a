---
tags:
  - '#audit'
  - '#clarification-continuation'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:e78b74e58202c93f6cd1246fe97668d2964e278917ef4a015c3a18ac085e74d5'
related:
  - "[[2026-08-02-clarification-continuation-plan]]"
  - "[[2026-08-02-clarification-continuation-adr]]"
---

# `clarification-continuation` audit: `implementation review`

## Scope

The implemented clarification-continuation contract was reviewed against the
accepted decision, the existing six-verb gateway, reducer semantics, text
bounds, request identity checks, and the repository's real-behavior testing
rules. The review covered the typed thread contract, graph gate, gateway schema
and route, and the SQLite-backed live loop test.

## Findings

### implementation-review | high | concurrent resolutions lack an atomic durable claim

This is a pre-existing control-integrity gap, not a regression from the
continuation outcome. The gateway reads and validates a pending checkpoint
before dispatch, so two concurrent valid resolutions can both observe the same
request and dispatch resume commands. The accepted ADR deliberately defers this
larger protocol change; it remains open.

### implementation-review | low | whitespace and wire-boundary cases were initially absent

The first test pass proved empty domain input and the domain character ceiling,
but did not independently prove whitespace-only rejection at both validation
layers or the inclusive ceiling at the HTTP schema. Deterministic domain and
wire tests now cover empty, spaces, control whitespace, the exact ceiling, and
one character beyond it. This finding is fixed in this pass.

## Recommendations

For the high-severity concurrency finding, author a follow-on ADR that chooses
the durable ownership and replay semantics for an atomic claim keyed by
`run_id` and `request_id`, including how a losing request observes the recorded
outcome and how claim completion reconciles with checkpoint advancement. Prove
that decision with real concurrent requests and lost-ack recovery.

Keep the fixed low-severity cases as contract ratchets whenever prompt-bearing
resolution shapes change.
