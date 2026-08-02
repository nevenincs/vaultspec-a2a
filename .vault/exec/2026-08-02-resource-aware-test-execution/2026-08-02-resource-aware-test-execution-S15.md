---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:05f48c264decdc7108e91cabcd0135520d3af133508b79d2fe92aa3cc59929ad'
step_id: 'S15'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---
# Register every pytest session machine-globally and derive distributed worker counts from observed capacity

## Scope

- `src/vaultspec_a2a/testing/sessions.py`

## Description

- Add the session module: every non-worker pytest session takes a shared
machine-global lease at configure time, making live sessions countable;
a distributed run derives its admitted worker count from the operator's
explicit core budget, else the load-discounted core count, split across
live peers.
- Wire admission into the plugin (rewrites numprocesses and tx, reports
the verdict in the run header, deregisters at unconfigure) and extend the
lease module with a public live-shared-holder count plus the same
fresh-clock skew tolerance the registry fix applied.

## Outcome

Committed as 2da331ca. A second concurrent suite now proceeds DEGRADED rather than multiplying load; a run that cannot register still runs, serially safe, with a logged warning - admission is throughput policy, never a correctness gate.

## Notes

Proceed-degraded was chosen over wait-for-the-peer: waiting turns every scoped run launched beside a long suite into an unbounded queue; the rationale is recorded in the amended decision record.
