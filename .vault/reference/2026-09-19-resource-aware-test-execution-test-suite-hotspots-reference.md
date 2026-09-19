---
tags:
  - '#reference'
  - '#resource-aware-test-execution'
date: '2026-09-19'
modified: '2026-09-19'
body_schema: 'body-v2'
body_hash: 'sha256:70a2defada0963d1275a213c76b2b385a4f326e3697dcea3647fc67cc8a27971'
related:
  - "[[2026-08-02-resource-aware-test-execution-adr]]"
---

# `resource-aware-test-execution` reference: `test suite collection and runtime hotspots`

Measured the repository's three collection lanes and the default full unit lane,
then traced collection imports, fixtures, subprocesses, platform executable
resolution, and live ACP/provider discovery through their production paths.

## Summary

The collection entry points are `Justfile:582`, `Justfile:587`, and
`Justfile:592`; the executable lane definitions are in `dev/toolchain.py:709`.
Before implementation, unit collection selected 4,570 of 4,761 items in 3.92s
and took 7.966s wall time, service selected 189 in 3.78s and took 7.706s, and
all selected 4,759 in 3.90s and took 7.633s. The difference between pytest's
reported collection time and process wall time is startup and process-owner
overhead, not item discovery.

Import-time profiling found that the root prerequisite plugin imported
`service_tests/_provider_catalog_live.py`, whose module-level schema imports
pulled gateway schemas, the provider catalog, OpenAI, LangChain, and MCP into
every pytest process. The chain is rooted at `src/vaultspec_a2a/conftest.py:19`
and the former eager imports were at
`src/vaultspec_a2a/service_tests/_provider_catalog_live.py:18`. A locked clean
interpreter took 1.19-1.31s to import the helper versus 0.10-0.11s to do no
work. Deferring validation-only imports to `_validated_selection` at
`src/vaultspec_a2a/service_tests/_provider_catalog_live.py:148` reduced helper
imports to 0.12-0.14s. Post-change collection took 6.765s unit, 6.882s service,
and 6.877s all; pytest's item-discovery time remained 3.79-3.88s, which confirms
the improvement is startup load rather than altered selection.

Fixture scope is already conservative: only seventeen fixtures are broader
than function scope. The compose stack is session-scoped at
`src/vaultspec_a2a/service_tests/conftest.py:26`, acceptance gateways are
module-scoped at `src/vaultspec_a2a/acceptance/tests/conftest.py:34`, and schema
materialization is session-scoped in `src/vaultspec_a2a/conftest.py:708`. The
largest remaining fixture lifecycle candidate is `acp_session_context` at
`src/vaultspec_a2a/providers/tests/conftest.py:82`: it is referenced 132 times
across eight test modules and starts a real Python child per invocation.
Changing its scope would also change asyncio loop ownership and mutable terminal
state, so runtime duration evidence is required before attempting that refactor.

The tests contain 182 real subprocess launch sites across 80 modules. Shared
gateway lifecycle and whole-tree reaping live in
`src/vaultspec_a2a/tests/gateway_boot.py:187` and
`src/vaultspec_a2a/tests/gateway_boot.py:321`; provider containment lives in
`src/vaultspec_a2a/providers/_subprocess.py:150`. The full serial unit lane was
later overlapped by an independently launched 12-worker suite in the same
worktree. It reached roughly 96 percent, accumulated ordinary failures under
contention, then pytest-timeout killed the Windows process at 1,913.854s without
a normal result or duration table. The stack showed the main asyncio loop
waiting with a live aiosqlite worker. Static configure-time admission cannot
protect a serial run from a distributed peer that starts later, so this run is
an under-contention failure measurement rather than a clean serial baseline.

Platform executable resolution is mostly centralized. Capsule Node paths are
platform-derived in `src/vaultspec_a2a/providers/factory.py:151`; Codex and Kimi
classification use `shutil.which` in `src/vaultspec_a2a/providers/factory.py:427`
and `src/vaultspec_a2a/providers/factory.py:452`; Antigravity's PATH plus
installer-location exception is centralized in
`src/vaultspec_a2a/providers/antigravity_cli.py:35`. Several live tests repeat
raw availability checks, but their production command construction still goes
through these classifiers. This is cleanup opportunity, not evidence of a
platform bug.

Default unit execution can still launch prompt-free live provider discovery
when a real gateway catalog path is exercised: observed children included
`agy models`, `kimi provider list --json`, and the Claude ACP Node adapter.
Those are discovery calls rather than model prompts. Billable completed-turn
proofs are separately gated by `requires_prerequisites` in
`src/vaultspec_a2a/conftest.py:576`; the measured default run withheld two such
proofs because dashboard-engine and explicit provider selection were absent.
The safety boundary held: no paid ACP prompt was authorized by the default
lane.

## Parallel unit-lane measurements

The RAG pinning module was excluded at the operator's direction and the local RAG
service remained stopped. No ACP completed-turn prompt was authorized.

The first uncontended parallel unit measurement completed in 382.193s wall
(378.39s reported): 4,529 passed, one skipped, and six registry tests failed
because isolated test homes all used the same real ports `18900-18902`. After
the initial port fix, the next lane took 492.75s and produced 4,533 passes, one
skip, and two telemetry failures. Both recording-span tests passed as part of
their module but failed when worker scheduling separated them from an earlier
telemetry configuration test; selecting only the pair reproduced the dependency.

After those fixes, a 409.68s lane produced 4,533 passes, one skip, and three
failures. One revealed that the first bind-to-zero registry-band repair still
had a release-to-use race; one manager test still hardcoded a real bind port;
both port defects are now repaired and passed ten consecutive two-worker stress
iterations. The third failure was an independent permission-response lease race
that reproduced on the eighth standalone iteration and remains queued as a
product-concurrency issue.

The runtime distribution is dominated by a small process/database tail rather
than collection. Across the measured lanes, WAL maintenance cases took roughly
20-77s each, model-stack warmup took 37-39s, CLI failed-start cleanup took about
26s, and serialized desktop/service-state or process-tree cases took roughly
20-76s. The final one to two percent of the lane therefore consumed several
minutes after most workers had drained. These are the highest-value runtime
targets: reduce WAL fixture/data setup, split or cache cold model compilation,
and consolidate repeated desktop process boots only where teardown and mutable
state can be proven independent.

## Implemented changes and retained opportunities

- Provider-catalog validation imports are lazy, reducing every pytest process's
  prerequisite import cost by about one second.
- Real registry bind tests no longer share the committed scratch band's fixed
  ports under xdist; the real manager bind uses the canonical held allocator.
- Recording-span assertions establish their own SDK-provider prerequisite and
  no longer depend on worker order.
- The function-scoped ACP child fixture, prompt-free provider discovery in the
  unit gate, repeated WAL materialization, cold model-stack compilation, and the
  long serialized desktop tail remain measured optimization opportunities.
- The permission-response lease race and unclosed Windows asyncio transport
  warnings are correctness/cleanup findings, not timing optimizations, and are
  retained in the audit queue.
