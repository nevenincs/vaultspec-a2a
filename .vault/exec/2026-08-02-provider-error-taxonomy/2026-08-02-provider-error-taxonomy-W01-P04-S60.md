---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:fbd3aef64e989a3c8c5fa81e532293260c1d1f7069770d80babd39c37d9e5518'
step_id: 'S60'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Refuse a retry once the lane has already relayed output

## Scope

- `src/vaultspec_a2a/graph/nodes/worker.py`
- `src/vaultspec_a2a/graph/compiler.py`
- `src/vaultspec_a2a/thread/errors.py`
- `src/vaultspec_a2a/graph/tests/test_compiler.py`

## Description

- Watch one attempt's token stream through a handler merged into the config that
  attempt already passes to the model.
- Carry the resulting flag on the wrapper the worker node already raises.
- Refuse the retry when the attempt relayed output, above the lane hint.
- Prove the pair: relayed output is never retried, the same refusal without
  output still is.

## Outcome

Retrying a turn re-invokes the model, so every token the lane had already
produced is relayed a second time and the user watches the same text arrive
twice with nothing to explain it. Before this campaign the defect was
unreachable, because provider faults never retried at all; making them retry is
what exposed it.

The guard is placed on whether the attempt STREAMED rather than on which
condition refused it, and that is the correction that matters. The obvious fix -
excluding the mid-stream transport variants - was measured and rejected: a plain
overload refusal, arriving after the lane had streamed, duplicated three times.
Duplication is a property of what the attempt already sent, not of what refused
it, so a condition-shaped fix would have closed one named variant and left every
other lane and condition duplicating unchanged, while reading as done.

It outranks a lane's STATED retry hint deliberately. The hint is the provider's
verdict on its own failure; the duplication is harm this system would cause, and
a vendor cannot consent to that on the user's behalf.

The flag rides the exception because the answer must come from the attempt that
failed. Any later inspection of state would be reading a world a retry had
already changed, and the handler observes the same callback stream that becomes
the client's chunks - not an approximation of it - so the guard cannot disagree
with what the client actually saw.

THE COST, stated rather than buried: a retry is now refused precisely when the
provider had already produced output, which is the case where a retry would have
been worth most - a stream dropped late in a long turn will fail instead of
succeeding with doubled text. The common retryable refusals (a 429, a 503)
arrive with nothing streamed, so the campaign's central value survives; what is
given up is the uncommon late failure.

Verified by two mutations in opposite directions, because one alone cannot tell
this guard from switching retry off: disabling it fails the two positive cases,
and making it refuse unconditionally fails the companion that proves the same
condition still retries when nothing was relayed. The condition under test is
resolved by the production mapper from the wire shape the adapter emits, not
chosen by the test.

## Notes

Taken by the orchestrator. The design, the measurement that ruled out the
condition-shaped fix, and the placement argument are the assigned executor's;
every dispatched executor was stopped mid-campaign by an account-level API
refusal requiring the operator to accept updated terms, so the implementation
was completed here rather than left pending.

A third path remains open and is NOT taken: keep the retry and DISCLOSE the
discarded output to the client. It is a better outcome for the late-failure case
but needs a new frame in the progress catalog plus a consuming change in the
dashboard, making it cross-repo against an additive-only wire contract. The
honest sequence is this guard first and disclosure later; the reverse order
would leave users watching duplicated text in the interim.
