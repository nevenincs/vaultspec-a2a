---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
body_hash: 'sha256:47b3398da99b84b115105d10db0016f9afb88ff1c5bc57f588422f53b1472ccc'
step_id: 'S183'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Answer a permission request through a run-scoped versioned verb

## Scope

- `src/vaultspec_a2a/api/routes/gateway.py`
- `src/vaultspec_a2a/api/schemas/gateway.py`

## Description

- Add the run-scoped answer verb the versioned surface was missing.
- Resolve and scope-check the request before anything acts on it.
- Declare the surface expansion in the guard that exists to catch an undeclared one.
- Regenerate the published contract through its own command.

## Outcome

Implemented, gated, and committed. The versioned surface could POSE a permission question -
the request has been an enumerated frame on the progress stream since the catalog closed -
but only the transition surface could accept the answer. That asymmetry blocked four
retirement Steps: retiring the transition surface would have stranded every run paused
awaiting a decision, because there would have been no way left to give one.

No existing verb could carry it honestly. A run-start retry is a fingerprint-compared
replay, so an answer-bearing retry is a different fingerprint and is refused by design;
cancel is destructive; the remaining members are reads. Overloading one of them would have
corrupted a certified contract to keep a count at five, so the count moved to six by
explicit amendment instead.

The verb adds no state machine of its own. It is a versioned projection of the existing
answer path, so at-most-once behaviour comes from there rather than being re-implemented:
a repeated answer replays the stored outcome byte for byte, including the derived
idempotency key, and dispatches no second resume.

Scoping is the part worth reading twice. A request identifier names a request, not a run,
so without a check a caller holding one run's identifier could answer another run's
question. The handler resolves the request and refuses a mismatch as not-found BEFORE
calling the service, which is the difference between a guessed identifier having no effect
and having its effect noticed afterwards. Proven by mutation on a copy outside the
repository: with the cross-run comparison removed, the test fails.

Verification: the interface suite passes 391 tests with no failures. Because a concurrent
session's uncommitted edit to a shared package broke imports tree-wide mid-verification,
that run was taken against a clean copy of the committed tree with only this Step's files
overlaid - which isolates this change from someone else's in-flight work rather than
waiting on it or reporting around it.

## Notes

Three guards failed on first run, and all three were correct to. The versioned surface
carries a test asserting it does NOT grow, and two more asserting the published contract
matches the live document. The surface guard was updated deliberately rather than loosened -
the set stays exact, and the new entry records that the sixth member arrived by decision
amendment rather than by drift, which is precisely what that guard exists to distinguish.
The contract was regenerated through the command its own failure message names, never
hand-edited.

One assertion states what the system does rather than what was expected of it. The first
answer reports accepted but NOT applied, because the run under test is not parked awaiting
that decision - the answer is recorded and a resume dispatched, but no paused execution
exists to release. That was probed and recorded rather than forced into the shape the test
author assumed, and the probe produced a stronger proof than the original intent: the
duplicate answer returns a byte-identical body, which is what replaying a stored outcome
actually means, where the assumed assertion would have held trivially and proven nothing.

This Step unblocks the gating half of legacy retirement only. Removal remains conditioned
on joint certification, and on the seven other gaps between the two surfaces - among them
thread deletion, whose contract this campaign specified while it exists only on the
transition surface.
