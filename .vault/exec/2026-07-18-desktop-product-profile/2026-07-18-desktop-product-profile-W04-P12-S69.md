---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S69'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace desktop-product-profile with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S69 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Prove prepare timeout cancellation and failed commit release capacity without a run token or run-owned child process and ## Scope

- `src/vaultspec_a2a/desktop_tests/test_run_admission.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Prove prepare timeout cancellation and failed commit release capacity without a run token or run-owned child process

## Scope

- `src/vaultspec_a2a/desktop_tests/test_run_admission.py`

## Description

- Add a real-behavior admission proof driving a production gateway armed with the
  desktop profile over a genuinely migrated app home, real loopback sockets, and
  real HTTP - no mock, monkeypatch, stub, skip, or expected failure; every child
  is reaped by killing the gateway process tree.
- Prove concurrent first demand: four parallel authenticated prepares under a
  capacity of two admit exactly two and refuse the rest, and the worker spawn line
  appears exactly once, so the hard reservation bound holds and exactly one worker
  starts.
- Prove a prepare creates no run and receives no token: each admitted prepare
  carries a reservation identity and the validated required-role set but no run id
  and no lease or token, and active-run discovery stays empty - no run, hence no
  run-owned child.
- Prove commit is reservation-bound: a live reservation commits to exactly one
  durable run with a non-secret lease, a double commit of the consumed reservation
  is refused, and a bogus reservation is refused - each refusal precedes run
  creation.
- Prove the reservation time-to-live: a filled bound refuses a third prepare, and
  after the reservations expire a fresh prepare is admitted again while a commit
  against the expired reservation is refused and creates no run.
- Make the reservation time-to-live configurable so the timeout is provable in
  bounded wall-clock time and tunable in production; wire the broker seat to it.

## Outcome

Two real armed-gateway tests pass (2 passed in ~38s): the concurrent-bound and
reservation-bound commit proof, and the timeout and expired-commit proof. Lint,
format, and type checks pass across the test, the config field, and the broker
seat. The full `api`, `control`, and `worker` suites remain green, and the new
tests join the desktop baseline. The run-admission invariants - one worker under
concurrent demand, a hard bound, a prepare that creates no run or token, a
reservation-bound commit, and a timed-out reservation that leaks neither a slot
nor a run - are proven end to end.

## Notes

Follow-up remediation (P11 review MEDIUM-2): the shared run-creation core now
releases the drain-gate admission on EVERY non-durable failure path through a
try/finally release-if-not-persisted, not only on a nickname conflict, so an
unexpected exception from run creation can never leave a phantom active run that
blocks drain quiescence. The real regression proof lives in the api drain suite
(`test_gateway_drain.py`) rather than this subprocess desktop test, because it
needs in-process drain-gate observability and a mock-free forced failure - a
genuinely schemaless database makes the run-start insert raise a real
`OperationalError`, after which the admission count is asserted zero and a bounded
drain is asserted quiescent. The subprocess armed-gateway harness here cannot force
that pre-persist failure because the armed gateway validates its schema at boot.

The proof required a configurable reservation time-to-live: the broker default is
production-sized, so a wall-clock timeout proof needs a short one. The knob was
added to domain configuration (its proper home, and a tunable production benefits
from) and the broker seat now reads it - two small enabling changes beyond the
test file, made to keep the timeout proof honest rather than skipped. Commit
eligibility passes in this environment because the host resolves real provider
commands; the mock preset run itself uses the mock provider and completes fast, so
run existence is asserted through run-status rather than a race-prone active-run
count.
