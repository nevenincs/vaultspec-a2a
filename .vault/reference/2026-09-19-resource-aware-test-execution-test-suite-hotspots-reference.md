---
tags:
  - '#reference'
  - '#resource-aware-test-execution'
date: '2026-09-19'
modified: '2026-09-19'
body_schema: 'body-v2'
body_hash: 'sha256:22375ea496d49eb2bf0f4301a22c03226db3bf3a756eb4842725ac22fdca1aca'
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

## WAL optimization measurement — 2026-09-20

An isolated serial run established a clean WAL-maintenance baseline: fourteen
tests took 105.12s. The suite wrote thousands of 2 KiB rows as individual
autocommits even though its assertions concern WAL pages, checkpoint blocking,
file size, and freelist pages. Replacing transaction count with 16 KiB rows,
disabling crash-durability fsync only in test data generators, and using a 50ms
test busy timeout reduced two repeated serial runs to 8.87s and 9.37s. The same
real SQLite files, open readers, transaction boundaries, checkpoints, vacuums,
production ORM models, and administrative subprocess remain exercised.

The work also closed a production posture gap found by the timing investigation:
Alembic and the raw `migrate --fix` connection now honor the configured SQLite
busy timeout. Forty combined migration, administration, and WAL tests pass under
four workers.

The next non-RAG full unit lane completed in 386.11s: 4,534 passed, one skipped,
and three failed. This is 23.57s (5.8%) faster than the immediately preceding
409.68s lane despite the serialized process tail still determining completion.
No WAL-maintenance case remained in the fifty slowest items. The new top cost is
the five-slot cold model compile at 38.30s, followed by CLI failed-start cleanup
at 26.25s and serialized desktop process cases around 12-25s.

Two failures revealed remaining manager tests binding shared literal ports; the
module now uses held machine-global reservations for single-port binds and a
serialized dynamic range only for contiguous multi-port proofs, and passes 39
tests under four workers. The third failure is a desktop run-admission readiness
race retained in the audit queue. An unrelated concurrent worktree edit to the
Codex catalog was not changed or attributed to this pass.

## Model and CLI hotspot optimization — 2026-09-20

The model-stack module contained two consumers of the same cold compile report,
but each paid for a fresh interpreter and graph compilation. A module-scoped
fixture now supplies one read-only report to both assertions. The five-process,
five-trial loaded proof remains uncached. The isolated module measured 52.71s
before the change and 46.52-48.48s afterward; its remaining 35-37s is the
intentional loaded campaign rather than duplicate setup.

The 26.25s CLI failed-start hotspot was an injected `ready_timeout=25.0`, not
slow tree reaping. The test still occupies a real loopback port, launches the
detached service, waits for failure, fells the process tree, and proves that no
live resident was published, but now uses a three-second deadline. Two focused
runs completed in 3.18s and 5.31s, retaining a small variable tree-cleanup tail
without idling for the production startup budget.

The next comparable full non-RAG lane completed in 376.43s: 4,536 passed, one
skipped, and the previously reproduced permission-response lease race failed.
That is 9.68s faster than the preceding 386.11s lane and 33.25s faster than the
earlier 409.68s lane. CLI failed-start and WAL maintenance were both absent from
the fifty slowest cases. The 37.69s model entry is the deliberately unchanged
five-process loaded campaign; the single shared cold-compile fixture appeared
once as a 10.72s setup under lane contention.

## Provider idle-window optimization — 2026-09-20

The next duration table exposed six real-subprocess timeout controls whose
6-15-second observation windows dominated their assertions. The Codex pair and
ACP quartet took 47.33s in an isolated baseline. Scaling the short injected
deadline to 0.75s and the observation window to 3s retains a fourfold separation
between expiry and the control window, while the long controls remain 600 or
3,600 seconds. The stderr proof now emits every 0.1s to keep resetting the same
production deadline. Two complete focused runs passed in 23.69s and 24.76s, a
roughly 48% reduction with the real agent processes and production wait paths
unchanged.
