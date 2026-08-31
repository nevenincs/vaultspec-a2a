---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:4ad68af1bc714b5cc93651284a61b9a706a2c997ecc37ba1a497ed30d66b9ac9'
step_id: 'S34'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Emit a terminal from the executor top-level dispatch handler

## Scope

- `src/vaultspec_a2a/worker/executor.py`

## Description

- Extract the cause-chain rendering out of the ingest summarizer into a public
  `describe_exception_chain` in `src/vaultspec_a2a/thread/errors.py`, so every
  site that must name a failure in one client-visible line shares one renderer
  rather than growing a second copy of the depth cap, the join and the bound.
- Rewire `_summarize_ingest_exception` in `src/vaultspec_a2a/streaming/ingest.py`
  onto that renderer; its remaining job is the attribution prefix.
- Add `_fail_unhandled_dispatch` to the executor and call it from the top-level
  dispatch handler, which previously logged that the thread might be stuck in
  RUNNING and returned - emitting no terminal, no frame, and no durable write.
- Emit an error frame carrying the condition floor as its code, then the FAILED
  terminal carrying the rendered reason as its error detail, then release the
  ingest slot for the two actions that own it.
- Guard the settle itself so the backstop cannot raise in turn, since it runs
  from the handler that keeps one bad run from taking the task group down.

## Outcome

The gateway acknowledges a dispatch the moment the worker schedules it, so a
fault outside every inner guard used to leave the gateway believing the dispatch
had succeeded while the run sat RUNNING with nothing at all to explain it. That
run now settles: a client sees a machine-readable condition code on the error
frame and a reason on the terminal, and the durable status write happens through
the same terminal-event path every other failure already uses.

Two decisions are recorded on the code. The condition is the vocabulary's floor
rather than anything richer, because no provider was engaged at this site and
naming one would send the reader after a remedy the run never needed. The slot
release is limited to the two actions that take it: a cancel or an unrecognised
action never held the slot, so a held slot there belongs to a concurrent run
whose own settle owns the terminal, and emitting here would race a legitimate
outcome with a fabricated failure.

Verified with `ruff format`, `ruff check`, `ty check` and pytest over the worker,
streaming and thread suites (535 passed after the export-set fixture was updated
for the new public name).

## Notes

The backstop's own trigger is not inducible from a real dispatch with any
well-formed input, and that is by construction: every inner path already guards
itself, which is why the arm is a backstop rather than a branch. Coverage
therefore drives its target directly, over a real bridge, a real HTTP relay and
the executor's real ingest-slot state, and asserts what the gateway would
receive rather than what the executor intended to send. Reaching it end to end
would need fault injection at the relay boundary, which no supported seam offers
today; this is left as a coverage gap rather than closed with a test double.

Three suite failures observed in the same run belong to concurrent writers in
this shared worktree and not to this Step: the committed OpenAPI artifact drifted
from the live document, and two provider-eligibility credential tests. One
whole-tree type diagnostic in the gateway text-bounds schema tests is likewise
another writer's.
