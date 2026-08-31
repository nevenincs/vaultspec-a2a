---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:5716570b3d2e1f727a41b9d9ac09a2939b682edb8330e08f0658a95fd01c02b5'
step_id: 'S36'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Record a condition on the ingest and resume catch-alls

## Scope

- `src/vaultspec_a2a/worker/executor.py`
- `src/vaultspec_a2a/worker/tests/test_executor.py`

## Description

- Accept an optional fallback reason on the run settle, used only when the
  aggregator stashed none and the caller offered one.
- Emit an error frame alongside the terminal on that arm, because a failure
  ingest never classified emitted no frame either, leaving a consumer that keys
  on the frame's code unable to see the run failed at all.
- Wire the ingest catch-all to the per-mode execution wording rather than its
  own hardcoded strings, matching how the other shared arms already read.
- Wire the resume catch-all to the same fields with its own wording.
- Initialise the fallback to None on both paths so an ordinary settle offers
  nothing and keeps whatever ingest classified.
- Cover both directions: a failure with no stashed reason names itself on both
  channels, and a settle with no fallback invents no failure.

## Outcome

The two execution catch-alls previously set `outcome = FAILED` and logged, then
handed the settle a thread for which no reason had been stashed. The settle read
that absence and emitted a terminal with a null detail and no error frame, so a
run whose exception escaped around ingest's own reporting reached a client as a
bare "failed" on both channels.

The fallback arm is deliberately narrow. It fires only when a reason is absent
AND one was offered, so a classified failure keeps ingest's own richer reason and
a normal completion is untouched. The condition is the executor floor rather than
a provider member, on the same reasoning the pre-run refusals already record: an
exception in the executor's own machinery engaged no provider, so naming one
would send the reader after a remedy the run never called for.

Verified by mutation rather than by assertion alone: disabling the arm fails
`test_an_unclassified_execution_failure_still_names_itself` and leaves
`test_a_settle_with_no_fallback_invents_no_failure` passing, which is the pair
that distinguishes a real fix from one that emits an error on every settle. Both
drive the real settle through the real recording bridge, so the assertions read
payloads off an actual HTTP batch POST rather than the executor's intent before
it crossed the IPC boundary.

`uv run --no-sync pytest -q -p no:randomly --timeout=180 --timeout-method=thread
src/vaultspec_a2a/worker/tests/ src/vaultspec_a2a/streaming/tests/` reports
297 passed, 2 deselected. Whole-file `ruff format`, `ruff check` and `ty check`
clean.

## Notes

Completed by the orchestrator after the assigned executor stopped at a session
limit mid-Step. It had landed the data half - three wording fields declared on
the shared guard record and populated for both dispatch modes - with no consumer
anywhere. That fragment was inert rather than harmful, and the whole suite passed
with it in place, which is precisely why it was worth finishing rather than
committing: a declared capability with no caller is the dead-capability shape
this project treats as a defect, and it would have read as done.

The remaining Steps of this Phase are unstarted: the durable condition column and
its migration, the five control-plane dispatch-failure sites, the replay frame,
the fanout eviction policy, and the persistence proof. Until the column exists,
no path in this Phase can record a TYPED condition durably - only the reason
text, which is the user-visible half.
