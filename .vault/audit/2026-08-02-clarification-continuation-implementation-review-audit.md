---
tags:
  - '#audit'
  - '#clarification-continuation'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:d04b573b069a8f697b4f148c45fe54a91c850b0bca6ef472e179b2cc1f9dbc0a'
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

### implementation-review | high | RESOLVED - the leased dispatch journal closed the concurrency gap

Appended 2026-08-02, later the same day: the follow-on decision the
recommendation below asks for exists and shipped as
`2026-08-02-control-action-leases-adr` (accepted; its plan completed 22 of 22
steps). The respond path now reserves an atomic claim on the request-scoped
idempotency key before any dispatch
(`src/vaultspec_a2a/control/clarification_service.py:296`,
`src/vaultspec_a2a/control/action_lease.py:65`): a competing resolution with a
different payload observes the recorded outcome and refuses with 409
(`payload_matches=false`), an identical concurrent replay returns the durable
outcome without dispatching (`acquired=false`), only the committed lease holder
dispatches, and worker success is never taken as application proof - only the
request-scoped checkpoint receipt settles the journal row, with restart
recovery redriving expired committed leases. The live loop suite proves six
racing identical replays and lost-ack recovery
(`src/vaultspec_a2a/api/tests/test_clarification_loop_live.py`). The original
entry above stands as written for its date; this gap is closed.

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
