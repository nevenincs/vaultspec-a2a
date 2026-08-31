---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:8b3229597d791470afa6fd0362115b38a4070ed23207ec3c748202f68ce486d7'
step_id: 'S25'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Derive the recoverable flag from the condition instead of the catch branch

## Scope

- `src/vaultspec_a2a/streaming/ingest.py`

## Description

- Declare one retryability predicate over the condition vocabulary, beside the
  vocabulary it judges, carrying the admission and exclusion reasoning with it.
- Replace the retry classifier's private table with a call to that predicate.
- Read the emitted failure frame's recoverable flag from the same predicate
  instead of the hardcoded false the catch-all always sent.
- Teach the ACP protocol simulator to attach an error kind and a chosen JSON-RPC
  code, so a real refusal can carry a discriminator other than the credential
  default.
- Prove the flag on the frame a consumer receives, for a retryable and a
  non-retryable condition, and prove the two consumers agree.

## Outcome

The flag stopped describing the handler and started describing the failure.

The defect was structural. Every provider fault reaches the catch-all arm, and
that arm passed a literal false, so a transient overload and a revoked credential
were served to a client identically unrecoverable while a step timeout - a fact
about graph infrastructure, not about a provider - was served recoverable. The
value classified which `except` branch had run. No provider failure of any kind
could be reported recoverable, which is why this could not be fixed by editing
the constant: nothing in that branch knew the difference.

The judgement now lives once, beside the vocabulary it judges, and both consumers
read it. That placement was the substantive decision of this Step. The two
consumers sit in different packages - the orchestrator's node retry policy, which
ACTS on the answer, and the failure frame, which REPORTS it - and neither is a
natural home for a rule the other must obey. Putting it in either would have made
one package import the other's private table or, far more likely, keep a second
copy. Two copies agree on the day they are written and drift on the day one is
edited, and the drift is not cosmetic: it is a client told a failure is permanent
while the graph quietly retries it, or a client told to wait on a failure the
graph has already given up on. The vocabulary module is where the members are
defined, retryability is a property of the members, and both consumers already
depend on it. So the predicate went there, and the retry classifier's private
table was deleted rather than left beside it - the earlier Steps' reasoning moved
with it, so nothing was lost in the move.

No member was added to the enum, which stays a closed, additive-only wire
contract. A predicate over it is not part of that contract.

The three already-classified branches are untouched: a recursion limit stays
unrecoverable, a stalled stream and a step timeout stay recoverable. Those are
graph-infrastructure judgements, they are correct, and none of them is a provider
condition, so the condition vocabulary has nothing to say about them.

Proving it needed one addition to the ACP protocol simulator. It could only ever
refuse with a bare code, which resolves to the credential member - so with the
simulator as it stood, no test could drive a RETRYABLE condition through the real
path at all, and the positive half of this Step would have had to be asserted on
the predicate in isolation. The simulator now accepts an error kind and a code,
attaching the kind to the error frame's data exactly where the real adapter puts
it. Both additions are optional and a refusal without them behaves as before, so
no existing caller changed.

Three assertions, all on the frame a consumer actually receives, driven through
the real simulator subprocess so the condition is resolved by the lane from a
real wire frame: a rate refusal arrives recoverable, a credential refusal arrives
unrecoverable, and - the one that guards the reason for the shared predicate -
what the client is told matches what the retry policy would do, checked over the
same real failure in the wrapper shape a worker node produces.

Mutation check, four mutations, each reverted before the next:

- Recoverable restored to the hardcoded false, which is the pre-Step behaviour:
  the transient case and the agreement case failed, and the credential case
  correctly still passed.
- Recoverable hardcoded true: the credential case and the agreement case failed.
- The frame's judgement inverted while the retry policy's was left alone, which
  is consumer drift made concrete: all three failed.
- The shared predicate emptied of every member: the streaming transient case
  failed AND all three retrying cases in the graph package failed, which is the
  positive evidence that both consumers really do read one source rather than two
  that happen to agree.

Both files were restored from byte copies and verified identical by hash.

Verification: `ruff format` and `ruff check` clean across the vocabulary module,
the graph package and the streaming package. Whole-tree `ty check` reports four
diagnostics, all in test modules of an unrelated in-flight lane. The streaming,
graph and condition suites ran together: 524 passed, 2 deselected, 2 failed. Both
failures are in the worker authoring-wiring tests and belong to a concurrent
refactor of the ACP MCP and authoring projection - they assert on environment
interpolation and workspace projection, they never invoke the simulator's error
path, and the simulator change is inert for them.

## Notes

A concurrent writer overwrote this Step's edits to the retry classifier partway
through and briefly replaced the lane hint's tri-state read with one that
collapsed silence into a stated refusal - which would have let one lane's frame
shape veto every other lane's condition and left the condition axis unreachable.
The file returned to its committed state on its own, and the edits were
re-applied against that state and re-verified. Recorded because the same shared
file is being written by more than one worker.

The scope declared for this Step names only the ingest module. Three further
files were touched and each is stated here rather than left to a reader of the
diff: the vocabulary module, which now carries the shared predicate; the retry
classifier, which now consumes it in place of its own table; and the protocol
simulator, which could not otherwise produce a retryable refusal. The first was
directed, the second is what makes it one judgement rather than two, and the
third is what makes the proof real rather than a predicate-level assertion.
