---
tags:
  - '#adr'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:9ec7d8a1ff8c47472f000806efddb2a51163e249387314a78fe85d116b24aced'
related:
  - "[[2026-07-15-dev-process-registry-adr]]"
  - "[[2026-07-17-tool-cores-audit]]"
---

# `resource-aware-test-execution` adr: `declaration-derived test scheduling over registry-backed resource leases` | (**status:** `accepted`)

## Problem Statement

The full serial suite takes roughly one hour on an otherwise idle 24-core host,
which is not a usable signal. Blind parallelization is not an option: the live
tiers contend on real ports, real service processes, provider usage windows, and
shared workspaces, and pytest by itself has no vocabulary for those resources.
Simultaneously, the fixed global `timeout = "300"` clock is wrong in both
directions - it kills a legitimately slow live model turn and lets a hung run
burn five minutes before failing. The repository already solved contention in
production: the dev-process registry allocates band ports race-free via
`O_EXCL` reservation markers with pid-liveness reclaim, and boots services with
live-listener readiness (`2026-07-15-dev-process-registry-adr`). The test
harness ignores it - `service_tests/test_pw7_acceptance.py` hardcodes a gateway
default of `http://127.0.0.1:18100` while real gateways were allocated to 18102
and 18130, so proofs skip claiming no stack exists while the registry knows
exactly where it is (finding recorded in `2026-07-17-tool-cores-audit`, section
"the harness cannot find or authenticate to a gateway the registry knows").

## Considerations

- Correctness of exclusion must not depend on any scheduler being right; a
  wrongly-placed test must still be physically unable to overlap a contended
  peer (the production analogue: `reserve_port` in `lifecycle/registry.py`).
- The declaration mechanism must extend the existing prerequisite vocabulary in
  the root `conftest.py` (`ExternalPrerequisite`, `--require-prerequisite`),
  not fork a parallel one; the anti-false-green session-fail lever must keep
  working under any new runner topology.
- Engines here keep serving HTTP after their heartbeat writer dies
  (`2026-07-17-tool-cores-audit`, stale-service-record finding), so liveness
  must be judged on owner pid AND heartbeat together, never one signal.
- Registry state is machine-global (`~/.vaultspec/procs`), so a lease mechanism
  placed beside it also guards against concurrent test sessions from other
  agents, not only intra-run workers.
- `pytest-xdist` is not currently a dependency; adding it is a deliberate
  choice to justify, not a default.

## Considered options

1. **Raw `pytest-xdist -n auto`** - rejected: placement is blind, session
  fixtures duplicate per worker, contended live tests collide; exactly the
  gamble the owner forbids.
2. **Hand-rolled multi-process orchestrator** (collect declarations, partition,
  run one pytest subprocess per resource-disjoint group) - rejected:
  re-implements worker lifecycle, crash-tolerant report forwarding, and
  terminal aggregation that xdist already does well; high defect surface for
  zero property gain once correctness lives in leases.
3. **Single-process ordering plugin only** (no second process) - rejected: can
  sequence but never parallelize, so the one-hour wall stays.
4. **Chosen: two independent layers.** A correctness layer of machine-global
  resource leases acquired through fixtures (same `O_EXCL` + reserver-pid
  discipline as the registry), plus a throughput layer where `pytest-xdist` is
  admitted ONLY in `loadgroup` mode with every group computed from the
  declarations. Scheduling becomes an optimization; exclusion is enforced at
  acquisition time regardless.

## Constraints

- `pytest-timeout` stays as a last-resort backstop against test-code deadlock,
  but its per-item value is derived from the declared resources, no longer one
  arbitrary global number; progress deadlines are the real arbiter for live
  turns.
- No mocks, no monkeypatching, no env-var mutation in-process: isolation flows
  through explicit `home:`/parameter injection, which the registry APIs already
  support.
- Windows port probing is unreliable (bind succeeds under a foreign
  `0.0.0.0` listener), so port acquisition must reuse the registry's
  connect-first-then-bind probe, never a fresh implementation.
- The parent feature is stable: the dev-process registry landed 2026-07-15 and
  has live multi-stack proof (`2026-07-15-dev-process-registry-adr`).

## Implementation

A `testing` subpackage inside the shipped test tree owns four seams. A resource
catalog defines the machine-readable vocabulary: each resource has a key, an
exclusivity mode, an optional link to an `ExternalPrerequisite` id, and an
optional timeout backstop; tests declare usage with a `resource` marker.
A lease module implements machine-global exclusive/shared leases beside the
procs registry using `O_EXCL` marker files stamped with the leaseholder pid,
dead-pid reclaim, and an mtime TTL as pid-reuse backstop; acquisition blocks
under a deadline and releases on fixture teardown. A progress module implements
deadlines that fail on resource death (dead owner pid, frozen heartbeat past
the role's staleness window) or on observed-state stall past an idle window,
never on elapsed wall clock alone. An endpoints module resolves live gateway
and worker URLs from the lifecycle registry records (classified LIVE, health
probed) instead of hardcoded defaults, with an explicit env override retained
for operator control. A pytest plugin wires the seams: it computes
`xdist_group` from each item's declared exclusive keys, funnels undeclared
live-tier items into one serial catch-all group, refuses `-n` under any dist
mode other than `loadgroup`, derives per-item timeout backstops from
declarations, and exposes acquisition fixtures that fail loudly when the
requesting test did not declare the resource it asks for.

## Rationale

The knockout criterion is the owner's: concurrency must be a consequence of
declared disjointness, and exclusion must hold even when scheduling is wrong.
Only option 4 delivers both. Leases make overlap physically impossible at
acquisition time - the same primitive that already prevents same-band boot
collisions in production - so admitting xdist stops being a gamble: its only
job is placement quality, and the `loadgroup` guard plus computed groups remove
its blind mode entirely. The alternative orchestrator (option 2) buys no
additional property and re-implements mature machinery. Deriving group ids and
timeout backstops from one declaration also keeps a single source of truth a
machine can audit, which is the same admission discipline the served-profile
rule applies to provider lanes.

## Consequences

- Live tests resolve services the way production does; the 18100-default class
  of false "no stack" skips is closed, per the audit's own repair prescription.
- Tests that fail to declare a resource lose access to it (fixtures refuse),
  so the declaration set converges to the truth over time; undeclared live-tier
  stragglers are serialized, never gambled.
- A skip still never reads as a pass: `--require-prerequisite` extends over
  resource-linked prerequisites, and skip attribution keeps functioning under
  xdist because report forwarding replays skips on the controller.
- Cost: one new dev dependency (`pytest-xdist`), lease marker files beside the
  registry, and the discipline that new live tests must declare resources.
- Migration of every existing free-port helper call to leased acquisition is
  incremental; unmigrated callers stay correct but serial.
