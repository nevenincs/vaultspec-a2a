---
tags:
  - '#exec'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:768d15fc977ea2e0516a83a40b00c03f75a631e5752535ff5ba62859ee655917'
step_id: 'S02'
related:
  - "[[2026-08-05-served-capability-contract-plan]]"
---

# F25 DONE in commit 088bd603 - the ingest-stall bound is now derived from the compiled graph rather than a flat global, so a run's own declared step timeout is honoured and presets without one keep the previous floor

## Scope

- `src/vaultspec_a2a/streaming/ingest.py`

## Description

- Add `_effective_stall_timeout(graph)` returning the greater of the global floor
  and the compiled graph's own step timeout plus a fixed margin.
- Call it from the ingest loop instead of reading the global stall timeout
  directly, so the bound becomes run-aware from data already on the compiled
  graph object rather than from a static default.
- Redescribe the global value as a FLOOR rather than a fixed bound in its
  docstring, matching what it now is.
- Reword the failure text from "no event from the graph for over Ns" to name the
  observed signal - "astream_events produced no new event for over Ns" - so the
  message reports what was measured rather than asserting a cause.
- Add a regression test covering a node working within its own step budget.

## Outcome

Closed. The defect was an unconditional outer bound tighter than the step budget
it was meant to backstop: a flat global floor against a chat model that sanctions
a much longer legitimate idle period, and against a preset declaring a far longer
step timeout that the compiler already sets on the graph. Neither was consulted.
The system was terminating work its own configuration declared safe.

Verified as a FIX rather than a preservation check, in both directions. The new
test was run against a reverted implementation and failed with the run reporting
failed instead of completed, accompanied by the watchdog's own log line firing at
zero seconds; the implementation was reapplied and the test passes. A test that
only ever passed would not have distinguished a fix from a no-op here.

Preservation was checked separately and is the part that matters most for this
change: the full streaming test module passes, INCLUDING the original
stall-watchdog tests, so a genuine wedge still fails loudly. Widening a watchdog
is exactly the change that can silently disable the protection it adjusts, and
that is the assertion which rules it out. The worker executor and research-chain
modules were also run and pass.

Presets that declare no step timeout keep the previous floor unchanged, so the
change is a widening only where a run has asked for one.

## Notes

Three files were touched; the Step scope names one. The others are the domain
configuration module carrying the floor and its docstring, and the streaming test
module carrying the new test.

Two honest gaps, recorded rather than smoothed over. Per-event timestamps for the
run that motivated this could NOT be obtained - the local database holds no rows
for that thread, which belonged to a different worker session - so the diagnosis
rests on the architectural mismatch between the three timeout values rather than
on a log replay of that run. Confidence is high; the evidence is inference. And
the decision corpus was searched for a prior deliberate ruling on the global
value and none was found on point, so no ruling was overridden - the absence was
checked rather than assumed.

Residual: the margin added to the step timeout is a module constant,
deliberately not a configuration knob because no other consumer needs it
configurable. If that changes it is a decision, not a defect.

This record was authored by the vault writer from the implementing agent's
report and the team lead's own verification of the commit inventory, not from
direct observation of the work.
