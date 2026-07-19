---
generated: true
tags:
  - '#index'
  - '#dev-process-registry'
date: '2026-07-16'
modified: '2026-07-19'
related:
  - '[[2026-07-15-dev-process-registry-P01-S01]]'
  - '[[2026-07-15-dev-process-registry-P01-S02]]'
  - '[[2026-07-15-dev-process-registry-P02-S03]]'
  - '[[2026-07-15-dev-process-registry-P02-S04]]'
  - '[[2026-07-15-dev-process-registry-adr]]'
  - '[[2026-07-15-dev-process-registry-plan]]'
  - '[[2026-07-15-dev-process-registry-research]]'
---

# `dev-process-registry` feature index

Auto-generated index of all documents tagged with `#dev-process-registry`.

## Documents

### adr

- `2026-07-15-dev-process-registry-adr` - `dev-process-registry` adr: `machine-global dev-process registry with strict port bands and lifecycle verbs` | (**status:** `accepted`)

### exec

- `2026-07-15-dev-process-registry-P01-S01` - Define procs.toml (role port bands, role build/serve commands, staleness windows) and the registry module: file-per-process JSON records under ~/.vaultspec/procs with atomic temp-and-rename writes, owner-checked mutation, pid-liveness and band-constrained port allocation
- `2026-07-15-dev-process-registry-P01-S02` - Implement the lifecycle verbs on the operator CLI: procs list/attach/kill/rebuild/rerun/resume/reap with Windows tree-kill and staleness verdicts
- `2026-07-15-dev-process-registry-P02-S03` - Route the gateway/worker serve paths, the engine-serve wrapper script, and the live-test/service-harness fixtures through registry registration and band-allocated ports
- `2026-07-15-dev-process-registry-P02-S04` - Prove it live: two concurrent registered engine+gateway stacks without collision, a stale orphan detected and reaped, rerun rebuilding and re-registering on the same port, and procs list enumerating truthfully throughout

### plan

- `2026-07-15-dev-process-registry-plan` - `dev-process-registry` plan

### research

- `2026-07-15-dev-process-registry-research` - `dev-process-registry` research: `process contention across concurrent sessions: existing discovery machinery and the missing registry layer`
