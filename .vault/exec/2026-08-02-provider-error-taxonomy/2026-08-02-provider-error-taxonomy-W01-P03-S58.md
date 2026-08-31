---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:c1f6010d466ae1589490b23ddcb6f3e999ef1af2456964f36a577a41e6d391e3'
step_id: 'S58'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Project the repair reason onto the run-status response

## Scope

- `src/vaultspec_a2a/api/routes/gateway.py`
- `src/vaultspec_a2a/api/schemas/gateway.py`
- `src/vaultspec_a2a/api/schemas/snapshots.py`
- `src/vaultspec_a2a/thread/snapshots.py`
- `src/vaultspec_a2a/control/thread_state_service.py`
- `src/vaultspec_a2a/api/tests/test_internal.py`

## Description

- Declare the repair reason on the domain snapshot, the wire snapshot and the
  run-status response, bounded on the consumer's terms.
- Read it from the durable row into the snapshot and project it onto run-status.
- Prove a live run discloses why an operation missed it, while disclosing no
  failure.
- Drop a plan Step id from the failure-reason field's comment.

## Outcome

The paths that record this - an undelivered follow-up, an undelivered
clarification resume - deliberately decline to write a failure reason, because
the run is still parked on its question and may yet complete. That decision is
right and it was already proven. It was also, until now, self-defeating: the
column was written durably and appeared on no wire schema and no route, so the
account reached no client at all. A write nobody can read is indistinguishable
from not writing.

The field is deliberately NOT merged with the failure reason. They answer
different questions about different run states and the distinction is the whole
point of the split: a client that collapsed them would tell a user their run had
died when it is still waiting for an answer. Both fields, and the domain
dataclass, now carry that warning where a reader of the type will see it.

Four hops were needed, and the count is the finding. The condition's own comment
in the wire snapshot warns that the projection seam is a `model_validate` which
drops an unnamed field silently - and the DOMAIN dataclass is a fourth site that
comment does not mention. Adding the field to the pydantic models and the route
left `ThreadStateData` without it, which surfaced as a loud `TypeError` rather
than a silent drop only because the service constructs it by keyword. A reader
adding the next field should expect four sites, not three.

Verified by mutation rather than by assertion alone: replacing the projection
with a constant `None` fails exactly the new test and leaves the two condition
tests passing. Whole-tree `ruff check src` and `ty check` are clean, and
`pytest src/vaultspec_a2a/api/tests/test_internal.py src/vaultspec_a2a/control/tests/`
reports 345 passed, 7 deselected.

## Notes

Taken by the orchestrator after every dispatched executor was stopped by an
account-level API refusal requiring the operator to accept updated terms.

The bound is 500 characters against a consumer that rejects over 500 BYTES,
matching the failure reason's existing treatment rather than inventing a second
rule. The two should move together if that limit is ever revisited; a follow-on
worth carrying is that both would be better expressed as one shared constant
than as two literals that agree today.
