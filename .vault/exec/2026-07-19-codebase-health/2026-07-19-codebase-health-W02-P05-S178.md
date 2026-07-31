---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
step_id: 'S178'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Release the drain gate on every terminal run outcome and complete the bounded quiescence wait at shutdown

## Scope

- `src/vaultspec_a2a/control/event_handlers.py`
- `src/vaultspec_a2a/control/drain.py`
- `src/vaultspec_a2a/api/app.py`

## Description

- Release the admission gate whenever a run reaches a terminal outcome.
- Cover the dispatch-failure paths where a run is durably terminal but no worker ever runs.
- Complete the bounded quiescence wait at shutdown that the code promised but never performed.
- Remove the reopen entry point and correct the comments that described a release that did not exist.

## Outcome

Implemented, gated, and adjudicated PASS. The gate was never released on a terminal
outcome: three separate comments promised a release by a settlement path, and no such call
existed anywhere in the tree. Every run that started and completed normally therefore
stayed in the active set for the life of the process, so a drain could never quiesce - the
release being absent from the ordinary happy path, not from an edge case.

Release now sits on the terminal-event handler as a finally over its existing branches,
firing for any validated terminal payload including the one where the status write fails.
That placement was the substantive decision. The gate tracks EXECUTION liveness rather
than bookkeeping: once the terminal event arrives the work is over, so releasing after a
failed write cannot let a drain quiesce over live work, whereas withholding it would
recreate the leak on exactly the flaky-store runs a drain most needs to count correctly.
The settlement path was rejected as a home because it no-ops outside the armed desktop
profile and skips lease-less runs - both would leak.

Four further sites carry the same repair. Two are dispatch failures where the run is
durably terminal but no worker ever ran, so no terminal event will ever arrive. One of
them was found by the implementer rather than specified: the websocket follow-up path
marks a thread failed and pushes its terminal frame straight to clients without passing
the relay, so the primary site would never have seen it. Shutdown now closes admission,
waits a bounded interval for quiescence, and logs the live count rather than hanging when
a worker died emitting nothing - which remains the designed escape rather than a leak.

The structure stayed a set rather than becoming a reference count. Admission happens at
most once per durable run while release is now five-site and deliberately racy, so
idempotent discard absorbs a double fire with no coordination; a count would underflow on
the designed terminal-plus-cancel case.

Verification: the interface, control, and worker suites pass 677 tests with no failures.
Each release site was proven individually by short-circuiting it and confirming the exact
expected test fails, with the durable row confirmed terminal in the failure output so the
leak is demonstrated rather than inferred.

## Notes

One flaky result was investigated rather than accepted. Three live stream tests failed
once during a full gate run, and two deselect experiments APPEARED to implicate the new
tests. The lane declined its own most convenient explanation: the identical command then
passed twice unchanged, and the failing run was a third slower on a loaded machine. Those
tests carry fixed frame deadlines and are load-sensitive; the shorter runs passed by luck
rather than by removing a cause. Queued as a separate finding.

Two findings are queued rather than fixed here. The cancel verb's terminal release appears
unreachable - the cancel service's success path never returns a terminal status and the
already-terminal case raises before the release line - so it is dead code rather than a
live second site; it was left untouched and its test rewritten to assert the reachable
truth instead of a path that cannot execute. And the two follow-up release sites disagree
in rationale, one seating the gate and one deliberately refusing to.
