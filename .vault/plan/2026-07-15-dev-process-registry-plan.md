---
tags:
  - '#plan'
  - '#dev-process-registry'
date: '2026-07-15'
modified: '2026-07-15'
tier: L2
related:
  - '[[2026-07-15-dev-process-registry-adr]]'
  - '[[2026-07-15-dev-process-registry-research]]'
---
# `dev-process-registry` plan

### Phase `P01` - Registry core and verbs

The procs.toml port-band definitions, the file-per-process registry with atomic owner-checked writes, and the lifecycle verbs.

- [ ] `P01.S01` - Define procs.toml (role port bands, role build/serve commands, staleness windows) and the registry module: file-per-process JSON records under ~/.vaultspec/procs with atomic temp-and-rename writes, owner-checked mutation, pid-liveness and band-constrained port allocation; `src/vaultspec_a2a/lifecycle/, procs.toml`.
- [ ] `P01.S02` - Implement the lifecycle verbs on the operator CLI: procs list/attach/kill/rebuild/rerun/resume/reap with Windows tree-kill and staleness verdicts; `src/vaultspec_a2a/cli/, src/vaultspec_a2a/lifecycle/`.

### Phase `P02` - Adoption and evidence

Auto-registration in the serve paths and test harnesses, the engine-serve wrapper, and live multi-instance contention evidence.

- [ ] `P02.S03` - Route the gateway/worker serve paths, the engine-serve wrapper script, and the live-test/service-harness fixtures through registry registration and band-allocated ports; `repoint the port-asserting MCP tests at the declared bands; `src/vaultspec_a2a/api/app.py, src/vaultspec_a2a/worker/, scripts/, src/vaultspec_a2a/service_tests/, src/vaultspec_a2a/protocols/mcp/tests/`.
- [ ] `P02.S04` - Prove it live: two concurrent registered engine+gateway stacks without collision, a stale orphan detected and reaped, rerun rebuilding and re-registering on the same port, and procs list enumerating truthfully throughout; `src/vaultspec_a2a/lifecycle/tests/, src/vaultspec_a2a/service_tests/`.

## Description

## Steps

## Parallelization

## Verification
