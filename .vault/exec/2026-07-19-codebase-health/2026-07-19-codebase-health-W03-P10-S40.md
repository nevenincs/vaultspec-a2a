---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S40'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Apply bounded deadlines to provider turns requests and cleanup operations

## Scope

- `src/vaultspec_a2a/providers/acp_chat_model.py, src/vaultspec_a2a/providers/codex_chat_model.py`

## Description

- Audit which provider awaits already carry a deadline before adding any.
- Bound the cleanup awaits that did not, and await the background task that was
  cancelled but never awaited at all.
- Record what could not be asserted at unit level rather than asserting it badly.

## Outcome

Turn requests were already bounded. Every Codex request, thread creation, prompt, and
notification read carries the configured timeout, and the process reap is bounded at five
seconds per stage. Adding deadlines there would have been change without effect.

Cleanup was the real gap, in two shapes. The reader task was awaited after cancellation
with no deadline, so a task blocked in a call that does not observe cancellation would hang
close - and close is on the path that frees the process tree. Separately the stderr drain
task was cancelled and never awaited at all, so it could outlive the session it belonged
to. Both now cancel and await under one bounded deadline, and a task that misses it is
abandoned rather than allowed to hold the session open.

Gates: `ruff check src/` clean, `ty check src/` clean, provider suite reports three hundred
eighty passed with ten deselected.

## Notes

The stronger property - that close abandons a task which ignores cancellation - was written
as a test, and the test hung the suite. Proving it requires constructing a genuinely
uncancellable task, which then survives the assertion and blocks the event loop shutdown at
the end of the test: the test hangs while proving the code does not. It was removed rather
than weakened into something that looked equivalent, and the docstring on the surviving
assertion records why, so the gap is visible instead of appearing covered.

The unawaited drain task was introduced by an earlier Step in this same session. Finding it
here is the argument for auditing before extending: the Step asked for deadlines on turns,
turns already had them, and the defect was in cleanup - including one this session had just
added.
