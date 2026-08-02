---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:30bdce10d80826c9c93f72b4467a4924e97a325d3a006a9f0125e3a0df8ae026'
step_id: 'S35'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Record a condition on the missing-graph rejection

## Scope

- `src/vaultspec_a2a/worker/executor.py`

## Description

- Add `_reject_with_condition` to the executor: the one pre-run refusal epilogue
  that emits the condition floor as the error frame's code and the refusal's own
  wording as the terminal's error detail.
- Route the missing-graph guard through it, and give the guard wording record a
  client-facing detail per dispatch mode beside the operator log line it already
  carried, so an ingest with no preset and a resume with no graph stay distinct.
- Route the pre-flight failed arm through the same epilogue: it shared the exact
  blank shape, driving a run to FAILED with nothing to say why it was not re-run.

## Outcome

Both refusals always knew their cause and neither told a client any of it: the
terminal carried no detail, and no error frame preceded it, so a consumer that
branches on the frame's code could not see the failure at all. Both channels now
carry it, which is the pairing this campaign treats as the minimum for a failed
run - the code is what a consumer branches on, the detail is what the gateway
persists so a reload recovers it without the live stream.

The client detail is deliberately separate from the operator log line rather than
reusing it: the log line carries the run identifier, and the client's reason is
already scoped to the run being read, so repeating it would spend a capped reason
on something the frame already carries.

Coverage drives all three arms through a real `handle_dispatch` over a real
bridge and HTTP relay. The pre-flight arm's checkpoint is made to record an
unhandled error the only honest way available - by running a real graph whose
node raises, so the framework writes the error channel itself; a hand-written
checkpoint row would prove the pre-flight reads a shape the framework may never
produce.

Verified with `ruff format`, `ruff check` over the worker, streaming and thread
error surfaces, and pytest over the worker and streaming suites: 295 passed.

## Notes

The slot-held guard is deliberately NOT routed through the new epilogue and stays
silent. That guard drops a dispatch because another run already owns the thread's
ingest slot, and that owning run settles on its own; a terminal emitted here would
corrupt a live run's outcome rather than close a blank one.
