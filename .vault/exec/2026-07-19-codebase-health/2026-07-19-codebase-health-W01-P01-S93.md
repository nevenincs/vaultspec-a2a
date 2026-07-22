---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S93'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Implement gateway lifetime identity worker generation identity and explicit paired-gateway identity in authenticated readiness

## Scope

- `src/vaultspec_a2a/api/schemas/gateway.py, src/vaultspec_a2a/control/worker_management.py, src/vaultspec_a2a/api/internal.py, src/vaultspec_a2a/worker/app.py`

## Description

- Mint one lifetime identity per gateway process, distinct from its pid and port.
- Count spawn generations on the spawner, and issue them through a single
  accessor so the lazy path and the watchdog cannot both mint.
- Carry both identities to the worker through its spawn environment.
- Report them from worker health, and expose the gateway's own identity plus the
  worker's claimed pairing on the authenticated readiness body.
- Keep every addition additive: nothing compares the values yet.

## Outcome

The pairing is now describable. Previously it was inferred from a URL, and a URL cannot
distinguish a gateway from its own restart on the same port - so a worker left over from a
previous incarnation reported the correct target and looked correctly paired. That is the
condition behind dispatch reaching a foreign worker.

Three facts now travel: which gateway incarnation exists, which incarnation spawned this
worker, and which spawn attempt produced it. A worker started by something other than a
gateway spawn reports empty values, which is the honest answer rather than a default that
would read as a valid pairing.

Six tests cover the identity: the lifetime value is stable within a process, the two
environment names are distinct and namespaced, a fresh spawner has issued nothing, issued
generations strictly increase, counters are per-spawner rather than global, and concurrent
issuance never duplicates.

Gates: `ruff check src/` clean, `ty check src/` clean, and the control and worker suites
report two hundred seventeen passed with eight deselected.

## Notes

The concurrency test initially passed against an unsafe implementation, and that is worth
recording rather than quietly fixing. Incrementing an attribute is not atomic - it loads,
adds and stores - so two callers can read the same value and issue one generation twice.
Twenty concurrent requests happened not to collide, which is luck under the interpreter
lock rather than evidence. The counter now takes a mutex, and the existing asyncio lock
was not usable for it because the watchdog reaches this path from a worker thread rather
than the event loop.

This Step deliberately compares nothing. Every value is reported, none is enforced, so a
mismatched or absent pairing changes no behaviour yet. The failure-closed decisions belong
to the following Step, and landing them together would have made an additive change and a
behavioural change indistinguishable in one diff.
