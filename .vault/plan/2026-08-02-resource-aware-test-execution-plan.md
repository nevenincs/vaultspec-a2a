---
tags:
  - '#plan'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_hash: 'sha256:8df5e4bece65c77948cd86756fa7a2aab735fb112fcbbe632dfa4e974af4a8c2'
tier: L1
related:
  - '[[2026-07-15-dev-process-registry-adr]]'
  - '[[2026-08-02-resource-aware-test-execution-adr]]'
  - '[[2026-08-02-resource-aware-test-execution-audit]]'
---
# `resource-aware-test-execution` plan

Deliver the two-layer test execution framework decided in
`2026-08-02-resource-aware-test-execution-adr`: machine-global resource leases
as the correctness layer, declaration-derived `loadgroup` distribution as the
throughput layer, registry-backed service resolution, and progress-based
deadlines in place of one arbitrary global timeout.

## Description

Executes `2026-08-02-resource-aware-test-execution-adr`. A new `testing`
subpackage carries the resource vocabulary, the lease primitive (same `O_EXCL`
plus pid-liveness discipline as the dev-process registry), progress deadlines
judged on owner pid and heartbeat together, and endpoint resolution from the
lifecycle registry. A pytest plugin wires declarations to `xdist_group`
computation, guards against blind distribution modes, derives per-item timeout
backstops, and exposes acquisition fixtures that refuse undeclared use. The
hardcoded gateway default in the pw7 acceptance harness is replaced by registry
resolution, closing the audited harness-registry gap.

## Steps

- [x] `S01` - Add the pytest-xdist dev dependency under the locked profile; `pyproject.toml`.
- [x] `S02` - Implement the resource catalog and marker vocabulary; `src/vaultspec_a2a/testing/resources.py`.
- [x] `S03` - Implement machine-global exclusive and shared resource leases; `src/vaultspec_a2a/testing/leases.py`.
- [x] `S04` - Implement progress deadlines with pid-and-heartbeat liveness watch; `src/vaultspec_a2a/testing/progress.py`.
- [x] `S05` - Implement registry-backed gateway and worker endpoint resolution; `src/vaultspec_a2a/testing/endpoints.py`.
- [x] `S06` - Implement the scheduling plugin with group computation, dist-mode guard, backstop derivation, and acquisition fixtures; `src/vaultspec_a2a/testing/plugin.py`.
- [x] `S07` - Wire the plugin into the root conftest and register the resource marker; `src/vaultspec_a2a/conftest.py`.
- [x] `S08` - Replace the hardcoded gateway default with registry resolution in the pw7 harness; `src/vaultspec_a2a/service_tests/test_pw7_acceptance.py`.
- [x] `S09` - Prove lease serialization and declaration-derived concurrency with real subprocess runs; `src/vaultspec_a2a/testing/tests/`.
- [x] `S10` - Run whole-tree gates, classify findings, and close the rolling audit for this feature; `pyproject.toml`.
- [x] `S11` - Centralize the production port-literal defaults into the strict config home; `src/vaultspec_a2a/control/config.py`.
- [x] `S12` - Provide the one canonical allocator-backed test port acquisition helper; `src/vaultspec_a2a/testing/ports.py`.
- [x] `S13` - Verify the literal inventory with a Python sweep and classify every kept literal in the audit; `src/vaultspec_a2a`.
- [x] `S14` - Move reservation-backed allocation inside the shared spawning primitives with candidate fallback; `src/vaultspec_a2a/tests/gateway_boot.py`.
- [x] `S15` - Register every pytest session machine-globally and derive distributed worker counts from observed capacity; `src/vaultspec_a2a/testing/sessions.py`.
- [x] `S16` - Prove cross-run exclusion for undeclared tests and degraded admission of a concurrent session; `src/vaultspec_a2a/testing/tests/`.
- [x] `S17` - Load the plugin through its pytest11 entry point and guard against addopts stripping; `pyproject.toml`.
- [x] `S18` - Heartbeat held reservations so process-lifetime holds outlive the reservation TTL; `src/vaultspec_a2a/tests/gateway_boot.py`.
- [x] `S19` - Compose capacity limits by minimum, bound lease waits under the item clock, and make shared markers unique per acquisition; `src/vaultspec_a2a/testing/`.
- [x] `S20` - Tighten the proofs against fallback passes and isolated-home binds; `src/vaultspec_a2a/testing/tests/`.
- [x] `S21` - Add the parallel toolchain lane for declaration-derived distribution; `dev/toolchain.py`.

## Parallelization

Steps are sequenced: the catalog and lease primitives precede the plugin, the
plugin precedes the harness migration, and the subprocess evidence run precedes
the closing gates. A single executor lands the whole plan.

## Verification

- A real subprocess run shows two tests declaring the same exclusive resource
  never overlap in time, while two tests with disjoint declarations do overlap
  under a two-worker `loadgroup` run.
- Lease exclusion holds without any scheduler: two concurrent contending
  processes serialize at acquisition time.
- A progress deadline trips on a killed owner pid and on a frozen heartbeat,
  and does not trip on a slow-but-progressing consumer.
- The pw7 harness resolves a gateway allocated off the band default via the
  registry, with no hardcoded `18100` fallback remaining.
- `-n` with a dist mode other than `loadgroup` aborts with a usage error.
- Whole-tree ruff, ty, and the full default pytest suite pass; findings are
  classified in the rolling audit.
