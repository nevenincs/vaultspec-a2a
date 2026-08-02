---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:f9a2d5071f82c9103098e40fa73389e98e4f1c1bc832bbd7459620a9429c9d45'
step_id: 'S27'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Prefer a lane-supplied retry hint over inferred retryability

## Scope

- `src/vaultspec_a2a/graph/compiler.py`

## Description

- Add a reader for the retry flag a lane states on its own failure, returning
  nothing when no flag was carried.
- Consult that hint ahead of the condition inference in the per-exception retry
  verdict, so a stated verdict decides in both directions.
- Record the axis ordering and the reason for it on the verdict helper.

## Outcome

One served lane answers the retry question outright instead of leaving it to be
inferred. Its error notification declares a required boolean beside the turn
error - confirmed against the protocol schema generated from the installed binary
during this Step, where the field is listed among the notification's required
properties - and the adapter has been parsing it into an attribute since the
raise sites were typed. Until now nothing read it.

The hint is preferred because it is strictly better information than anything
this predicate can derive: it is the provider's own verdict on its own failure,
it arrives on a frame already being parsed, and it costs nothing. Deriving a
conclusion and then ignoring the one the vendor sent would be the wrong trade in
every direction.

It decides in both directions, which is the deliberate part. A stated intent to
retry reinstates an attempt the lane itself intended - this adapter abandons the
turn on that notification rather than waiting for the lane's own retry, so
honouring the flag restores the behaviour the lane was describing rather than
inventing an extra one. A stated refusal is equally authoritative: the lane
saying it is done trying is exactly the signal that should stop a round of
backoff that could only fail identically.

Silence is not a refusal. The flag rides on one frame shape only, so a failure
raised anywhere else - the failed-turn path on the same lane, and every failure
on the other served lane - leaves it unset, and the condition inference decides
as it did before. Reading an absent flag as a stated false would have let one
lane's frame shape veto every other lane's condition, which is the opposite of
what this Step is for. The distinction was already modelled at the raise site,
where an unset flag is preserved as nothing rather than collapsed to false, and
this reader keeps it.

The hint sits inside the never-retry guard, not outside it. That guard is
structural - a recursion ceiling is a property of this orchestrator, not a
statement about a provider - so no lane may talk its way past it.

The residual risk is stated rather than designed around: a lane that stated it
would retry on a condition this classifier would otherwise refuse will get its
attempts. It is bounded by the policy's own attempt ceiling, and it follows the
governing decision's ruling that a directly supplied hint is preferred over
inference. The shape of the lane's own error taxonomy makes the combination
unlikely, and if it occurs the lane knows something this predicate does not.

Verification: driven through the real turn-failure builder on the real lane, with
the real notification shapes. A stated intent on a credential failure retried; a
stated refusal on an overload did not; silence on an overload, on an exhausted
usage window, and on a forwarded rate status each resolved by condition alone;
and the stdlib types were unchanged. `ruff format` left the file unchanged,
whole-tree `ty check` passed clean, and the graph suite passed 306 tests, 2
deselected. `ruff check src` reports one import-ordering finding in a testing
support module owned by another lane and none in this package.

## Notes

Behavioural proof under the real backoff policy belongs to the following proof
Step. What is recorded above is a predicate-level check driven through the real
lane builder rather than through a compiled graph.
