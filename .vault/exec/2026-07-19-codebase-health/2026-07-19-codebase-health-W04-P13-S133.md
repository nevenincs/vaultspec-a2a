---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S133'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Route lifecycle discovery integer coercion through the shared strict helper

## Scope

- `src/vaultspec_a2a/lifecycle/discovery.py`

## Description

- Remove the module-local coercion function and route the port, process id, and
  heartbeat reads through the shared helper.
- Add tests for the shared helper, since it is new production code.

## Outcome

The discovery record's three numeric fields now coerce through the shared helper, and the
module-local duplicate is gone. Eighteen tests cover the helper.

The behaviour worth pinning is the rejection rather than the acceptance. A JSON boolean is
an integer subclass in Python, so a record carrying true in the port field would coerce to
port one under a naive conversion; a numeric string would be accepted by the built-in
conversion; a fractional float would be silently truncated into a plausible port the writer
never sent. All three are refused, and each now has a test.

Gates: `ruff check src/` clean, `ty check src/` clean.

## Notes

Two real-process tests failed during verification and neither is attributable to this
change. The failures were different tests on consecutive runs of the same command - a
logging entrypoint first, a singleton acquisition second - with three hundred seven passing
both times. A deterministic break fails the same test twice. Both pass in isolation, both
spawn real subprocesses and bind real ports, and this host is concurrently running a heavy
indexing service, a container runtime, and another session.

The equivalence check described in the sibling record is the stronger evidence: this
refactor cannot change behaviour, because the replacement returns identical results to the
removed implementations across every input tried, including the edge values.
