---
tags:
  - '#exec'
  - '#dev-process-registry'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S04'
related:
  - "[[2026-07-15-dev-process-registry-plan]]"
---

# Prove it live: two concurrent registered engine+gateway stacks without collision, a stale orphan detected and reaped, rerun rebuilding and re-registering on the same port, and procs list enumerating truthfully throughout

## Scope

- `src/vaultspec_a2a/lifecycle/tests/`
- `src/vaultspec_a2a/service_tests/`

## Description

- Add a single end-to-end live proof exercising every claim of the ADR against
  real OS processes, real loopback binds, and real registry files - no mocks, no
  fakes. Two concurrent engine+gateway stacks (four representative serve processes)
  are booted through `serve_up` on band-allocated ports inside the committed
  scratch range, so the proof never contends the real dev bands or the live
  acceptance stack.
- Assert the four ADR guarantees in one flow: (1) no collision - four distinct
  ports, each inside its own role band; (2) `list_verdicts` enumerates all four
  truthfully as LIVE; (3) a felled orphan reads DEAD and `reap` collects exactly
  that record while sparing the three live stacks; (4) `rerun` fells and
  re-registers on the SAME port with a new pid and a live listener that `attach`
  confirms.

## Outcome

- The proof passes: 1 test, ~9s, real processes. The full lifecycle suite is 57
  green; `ruff check`, `ruff format --check`, and `ty check` are clean.
- Operator-CLI dogfood confirmed end to end against an isolated registry home:
  `procs allocate gateway-dev` prints the declared band's first port (18100),
  `procs list` reports "no registered processes" on an empty home, and `procs up`
  is wired with its allocate-boot-register help.
- Created: `src/vaultspec_a2a/lifecycle/tests/test_live_concurrency.py`.
- Modified: `src/vaultspec_a2a/lifecycle/tests/conftest.py`.

## Notes

- Every pid killed in the proof is one the test spawned; the live acceptance stack
  (18770 / 18110 / 18111) and every foreign port are untouched. The felled-orphan
  case uses a dead pid (the strongest staleness signal) rather than a heartbeat
  timeout, so the proof is fast and deterministic.
- The stacks are representative serve processes (a real socket-binding child), not
  the literal engine binary or full gateway app: this is a process-lifecycle proof
  of the REGISTRY, and no engine build or LLM is required. Booting the literal
  engine/gateway on band ports through the same `serve_up`/registration path is the
  driver's forward live-verify, out of scope for this no-dependency proof.
