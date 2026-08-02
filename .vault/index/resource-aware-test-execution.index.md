---
generated: true
tags:
  - '#index'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:12732758abbb7d81224140d68a45c92ce8ae1df99494e2edb10409c6c16b641e'
related:
  - '[[2026-08-02-resource-aware-test-execution-S01]]'
  - '[[2026-08-02-resource-aware-test-execution-S02]]'
  - '[[2026-08-02-resource-aware-test-execution-S03]]'
  - '[[2026-08-02-resource-aware-test-execution-S04]]'
  - '[[2026-08-02-resource-aware-test-execution-S05]]'
  - '[[2026-08-02-resource-aware-test-execution-S06]]'
  - '[[2026-08-02-resource-aware-test-execution-S07]]'
  - '[[2026-08-02-resource-aware-test-execution-S08]]'
  - '[[2026-08-02-resource-aware-test-execution-S09]]'
  - '[[2026-08-02-resource-aware-test-execution-S10]]'
  - '[[2026-08-02-resource-aware-test-execution-S11]]'
  - '[[2026-08-02-resource-aware-test-execution-S12]]'
  - '[[2026-08-02-resource-aware-test-execution-S13]]'
  - '[[2026-08-02-resource-aware-test-execution-S14]]'
  - '[[2026-08-02-resource-aware-test-execution-S15]]'
  - '[[2026-08-02-resource-aware-test-execution-S16]]'
  - '[[2026-08-02-resource-aware-test-execution-S17]]'
  - '[[2026-08-02-resource-aware-test-execution-S18]]'
  - '[[2026-08-02-resource-aware-test-execution-S19]]'
  - '[[2026-08-02-resource-aware-test-execution-S20]]'
  - '[[2026-08-02-resource-aware-test-execution-S21]]'
  - '[[2026-08-02-resource-aware-test-execution-adr]]'
  - '[[2026-08-02-resource-aware-test-execution-audit]]'
  - '[[2026-08-02-resource-aware-test-execution-plan]]'
---

# `resource-aware-test-execution` feature index

Auto-generated index of all documents tagged with `#resource-aware-test-execution`.

## Documents

### adr

- `2026-08-02-resource-aware-test-execution-adr` - `resource-aware-test-execution` adr: `declaration-derived test scheduling over registry-backed resource leases` | (**status:** `accepted`)

### audit

- `2026-08-02-resource-aware-test-execution-audit` - `resource-aware-test-execution` audit: `resource-aware test execution implementation review`

### exec

- `2026-08-02-resource-aware-test-execution-S01` - Add the pytest-xdist dev dependency under the locked profile
- `2026-08-02-resource-aware-test-execution-S02` - Implement the resource catalog and marker vocabulary
- `2026-08-02-resource-aware-test-execution-S03` - Implement machine-global exclusive and shared resource leases
- `2026-08-02-resource-aware-test-execution-S04` - Implement progress deadlines with pid-and-heartbeat liveness watch
- `2026-08-02-resource-aware-test-execution-S05` - Implement registry-backed gateway and worker endpoint resolution
- `2026-08-02-resource-aware-test-execution-S06` - Implement the scheduling plugin with group computation, dist-mode guard, backstop derivation, and acquisition fixtures
- `2026-08-02-resource-aware-test-execution-S07` - Wire the plugin into the root conftest and register the resource marker
- `2026-08-02-resource-aware-test-execution-S08` - Replace the hardcoded gateway default with registry resolution in the pw7 harness
- `2026-08-02-resource-aware-test-execution-S09` - Prove lease serialization and declaration-derived concurrency with real subprocess runs
- `2026-08-02-resource-aware-test-execution-S10` - Run whole-tree gates, classify findings, and close the rolling audit for this feature
- `2026-08-02-resource-aware-test-execution-S11` - Centralize the production port-literal defaults into the strict config home
- `2026-08-02-resource-aware-test-execution-S12` - Provide the one canonical allocator-backed test port acquisition helper
- `2026-08-02-resource-aware-test-execution-S13` - Verify the literal inventory with a Python sweep and classify every kept literal in the audit
- `2026-08-02-resource-aware-test-execution-S14` - Move reservation-backed allocation inside the shared spawning primitives with candidate fallback
- `2026-08-02-resource-aware-test-execution-S15` - Register every pytest session machine-globally and derive distributed worker counts from observed capacity
- `2026-08-02-resource-aware-test-execution-S16` - Prove cross-run exclusion for undeclared tests and degraded admission of a concurrent session
- `2026-08-02-resource-aware-test-execution-S17` - Load the plugin through its pytest11 entry point and guard against addopts stripping
- `2026-08-02-resource-aware-test-execution-S18` - Heartbeat held reservations so process-lifetime holds outlive the reservation TTL
- `2026-08-02-resource-aware-test-execution-S19` - Compose capacity limits by minimum, bound lease waits under the item clock, and make shared markers unique per acquisition
- `2026-08-02-resource-aware-test-execution-S20` - Tighten the proofs against fallback passes and isolated-home binds
- `2026-08-02-resource-aware-test-execution-S21` - Add the parallel toolchain lane for declaration-derived distribution

### plan

- `2026-08-02-resource-aware-test-execution-plan` - `resource-aware-test-execution` plan
