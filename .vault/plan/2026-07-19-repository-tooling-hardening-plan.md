---
tags:
  - '#plan'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-08-02'
body_hash: 'sha256:db3031162571fe37b70822915230eea5c61ca8b51086668aa7eb0b0bbb4ca010'
tier: L3
related:
  - '[[2026-07-19-repository-tooling-hardening-adr]]'
  - '[[2026-07-19-repository-tooling-hardening-research]]'
  - '[[2026-07-19-repository-tooling-hardening-reference]]'
---

# `repository-tooling-hardening` plan

Deliver one locked, modular, clone-reproducible development and governance
control surface.

## Description

This plan executes `2026-07-19-repository-tooling-hardening-adr`, grounded by
the companion research and Core/RAG implementation reference. Wave W01 makes
the lock authoritative and provisions the framework tools. Wave W02 converges
governance and replaces dynamic command dispatch. Wave W03 makes validation
read-only and hardens hosted automation. Wave W04 publishes the contract and
closes the mandatory implementation-review-queue loop.

## Steps

## Wave `W01` - lock and provision the framework toolchain

Establish the project lock as the only Core and RAG execution authority before any generated surface changes.

### Phase `W01.P01` - dependency authority

Define explicit dependency profiles and make the lock authoritative for every Vaultspec tool invocation.

- [x] `W01.P01.S01` - Define explicit base, server, RAG, tooling, and all profiles with bounded Core and RAG upgrades; `pyproject.toml, uv.lock`.

### Phase `W01.P02` - framework lifecycle commands

Expose deterministic setup, upgrade, synchronization, and diagnosis without ambient-latest fallbacks.

- [x] `W01.P02.S02` - Add locked setup, sync, upgrade, status, and service recipes for Core and RAG; `just/dev/deps.just, just/dev/vault.just, just/dev/rag.just`.
- [x] `W01.P02.S03` - Route workspace provisioning and agent RAG acquisition through deliberate locked versions with real subprocess tests; `src/vaultspec_a2a/cli/provision.py, src/vaultspec_a2a/providers/_acp_mcp.py, tests`.

## Wave `W02` - reconcile governance and redesign the command facade

Land clone-persistent governance and then replace dynamic dispatch with owner-thin native modules.

### Phase `W02.P03` - Core-owned Git-ignore and rules

Converge effective Git policy and canonical rules through Vaultspec Core ownership.

- [x] `W02.P03.S04` - Remove obsolete broad framework ignores and prove Core-managed policy convergence; `.gitignore`.
- [x] `W02.P03.S05` - Reconcile the compact custom rule corpus and regenerate provider projections through owning verbs; `.vaultspec/rules, generated provider projections`.

### Phase `W02.P04` - native Just modules

Replace the monolithic dispatcher with a discoverable portable module hierarchy.

- [x] `W02.P04.S06` - Replace dynamic dispatch with a minimum-version-checked native module index and modular developer surface; `Justfile, just/dev`.
- [x] `W02.P04.S07` - Route named services only through the process registry and stacks only through Compose; `just/dev/service.just, just/dev/stack.just`.

## Wave `W03` - unify validation and harden hosted automation

Make one read-only gate authoritative and consume it from hooks and GitHub.

### Phase `W03.P05` - local gates and debt

Separate validation from repair and reduce currently classified code-health debt.

- [x] `W03.P05.S08` - Convert hooks to locked read-only validation with explicit repair and synchronization commands; `.pre-commit-config.yaml, hook integration tests`.
- [x] `W03.P05.S09` - Remediate formatter, typing, dependency, and test-selection debt without suppressive shortcuts; `pyproject.toml, affected source and tests`.

### Phase `W03.P06` - hosted enforcement

Apply the local contract and least-privilege security boundary to hosted automation.

- [x] `W03.P06.S10` - Invoke canonical CI, pin actions, minimize permissions, and authorize self-hosted dispatch before secrets; `.github/workflows, repository health configuration`.

## Wave `W04` - document, verify, review, and queue

Publish the executable contract, exercise it end to end, and close the mandated audit loop.

### Phase `W04.P07` - documentation pipeline

Ship separated onboarding, how-to, reference, and explanation surfaces that match executable commands.

- [x] `W04.P07.S11` - Rewrite onboarding and add separated setup, command, operating-model, and vocabulary documentation through the documentation pipeline; `README.md, docs`.

### Phase `W04.P08` - acceptance and audit closure

Run real-behavior acceptance, review the implementation, and queue every finding.

- [x] `W04.P08.S12` - Run clone-to-CI acceptance, formal review, finding classification, audit queue updates, and execution summaries; `.vault/audit, .vault/exec`.

## Wave `W05` - strict-quality harness and visibility

Establish the Sol-defined declarative strict-sentinel contract, repair scope correctness, and expose each result in hosted CI before any promotion is attempted.

### Phase `W05.P09` - declarative target correctness

Make every quality target executable over the correct A2A scope from one registry.

- [x] `W05.P09.S13` - Add the cross-platform Ty target over the canonical Python roots.; `dev/toolchain.py`.
- [x] `W05.P09.S14` - Correct the cognitive-complexity command scope so it measures only production sources on every supported host.; `dev/toolchain.py, pyproject.toml`.
- [x] `W05.P09.S15` - Reconcile the complete canonical CI sequence in the declarative registry before reducing the root recipe to delegation.; `dev/toolchain.py, justfile`.

### Phase `W05.P10` - hosted visibility and anti-drift

Make every strict and advisory result independently visible in CI and prove the declarations cannot diverge.

- [x] `W05.P10.S16` - Schedule one named hosted step per deterministic sentinel on every push and pull request, guarded by !cancelled and advisory until promotion.; `.github/workflows/test.yml`.
- [x] `W05.P10.S17` - Schedule production JSCPD clone detection as a named advisory hosted-CI result.; `.github/workflows/test.yml`.
- [x] `W05.P10.S18` - Prove exact root, workflow, sentinel, platform, advisory, blocking, and duplication anti-drift invariants from the real registry.; `dev/toolchain.py, dev/tests/test_ci_contract.py`.

## Wave `W06` - strict type and portability remediation

Reduce Ty and Basedpyright debt in independent Terra-owned domains while preserving focused real-behavior regression evidence.

### Phase `W06.P11` - Ty portability and strict test infrastructure

Repair portable typing and shared test-helper contracts before fan-out consumers.

- [x] `W06.P11.S19` - Repair the Ty portability tranche for Windows-only ctypes and generic-length access.; `src/vaultspec_a2a/control/tests/test_spawn_containment_ownership.py, src/vaultspec_a2a/streaming/tests/test_sse_frames.py, src/vaultspec_a2a/utils/process.py`.
- [x] `W06.P11.S20` - Type the health-instrument boundary without suppressions and preserve its measured-result contract.; `dev/health/report.py`.
- [x] `W06.P11.S21` - Establish typed API test-fixture contracts before repairing dependent API tests.; `src/vaultspec_a2a/api/tests/conftest.py`.
- [x] `W06.P11.S22` - Repair the API endpoint test partition against the typed fixture contract.; `src/vaultspec_a2a/api/tests/test_endpoints.py`.
- [x] `W06.P11.S23` - Repair the API live-gateway and clarification test partitions without overlapping peer work.; `src/vaultspec_a2a/api/tests/test_gateway_live.py, src/vaultspec_a2a/api/tests/test_clarification_loop_live.py, src/vaultspec_a2a/api/tests/test_clarification_endpoint.py, src/vaultspec_a2a/api/tests/test_acceptance_five_verb.py, src/vaultspec_a2a/api/tests/clarification_harness.py, src/vaultspec_a2a/control/tests/test_verdict_loop_live.py, src/vaultspec_a2a/worker/executor.py, src/vaultspec_a2a/worker/graph_lifecycle.py, src/vaultspec_a2a/worker/tests/test_executor.py, src/vaultspec_a2a/worker/tests/test_executor_token_lifecycle.py`.

### Phase `W06.P12` - strict production-domain typing

Repair production typing by bounded domain with no suppressions or compatibility shims.

- [x] `W06.P12.S24` - Repair strict types in the control and repository production domains.; `src/vaultspec_a2a/control, src/vaultspec_a2a/control/repositories, src/vaultspec_a2a/authoring/discovery.py, src/vaultspec_a2a/api/routes/gateway.py, src/vaultspec_a2a/desktop_tests/test_worker_health_decode_contract.py`.
- [x] `W06.P12.S25` - Repair strict types in the provider and ACP production domains.; `src/vaultspec_a2a/providers, src/vaultspec_a2a/desktop/profile.py, src/vaultspec_a2a/desktop/tests/test_profile.py, src/vaultspec_a2a/desktop_tests/test_profile_paths.py, src/vaultspec_a2a/cli/tests/test_desktop_serve.py, src/vaultspec_a2a/desktop_tests/test_owned_process_tree.py`.
- [ ] `W06.P12.S26` - Repair strict types in provider/service tests and the bounded callback-observability contracts they require after production contracts stabilize.; `src/vaultspec_a2a/providers/tests, src/vaultspec_a2a/service_tests, src/vaultspec_a2a/conftest.py, src/vaultspec_a2a/tests/test_prerequisite_rule.py, src/vaultspec_a2a/graph/nodes/worker.py, src/vaultspec_a2a/graph/nodes/diverge.py, src/vaultspec_a2a/graph/compiler.py, src/vaultspec_a2a/graph/tests/nodes/test_diverge.py`.
- [ ] `W06.P12.S27` - Repair strict types in lifecycle test helpers and their production contracts.; `src/vaultspec_a2a/lifecycle, src/vaultspec_a2a/lifecycle/tests`.
- [ ] `W06.P12.S28` - Repair strict types in graph, authoring, worker, and streaming domains.; `src/vaultspec_a2a/graph, src/vaultspec_a2a/authoring, src/vaultspec_a2a/worker, src/vaultspec_a2a/streaming`.
- [ ] `W06.P12.S47` - Resolve every residual Ty and Basedpyright diagnostic across the canonical Python roots before any strict-type graduation.; `src, dev, docs, scripts, packaging`.

## Wave `W07` - structural complexity remediation

Reduce production complexity, shape, nesting, and module-size debt at the accepted thresholds through behavior-preserving decomposition.

### Phase `W07.P13` - high-risk structural domains

Decompose provider, streaming, API, and control hotspots while preserving their real behavior.

- [ ] `W07.P13.S29` - Decompose ProviderFactory construction paths below the configured complexity and shape thresholds.; `src/vaultspec_a2a/providers/factory.py`.
- [ ] `W07.P13.S30` - Decompose ACP composition, protocol, RPC, and chat-model hotspots without changing provider behavior.; `src/vaultspec_a2a/providers/_acp_mcp.py, src/vaultspec_a2a/providers/_acp_protocol.py, src/vaultspec_a2a/providers/_acp_rpc_handlers.py, src/vaultspec_a2a/providers/acp_chat_model.py`.
- [ ] `W07.P13.S31` - Decompose streaming transformation and interrupt emission hotspots with stream regression evidence.; `src/vaultspec_a2a/streaming/transformer.py, src/vaultspec_a2a/streaming/ingest.py`.
- [ ] `W07.P13.S32` - Decompose API gateway and event-adapter hotspots while preserving authenticated edge behavior.; `src/vaultspec_a2a/api/routes/gateway.py, src/vaultspec_a2a/api/event_adapter.py`.
- [ ] `W07.P13.S33` - Decompose control permission, dispatch, projection, snapshot, and worker-management hotspots.; `src/vaultspec_a2a/control`.

### Phase `W07.P14` - remaining structural domains

Finish graph, lifecycle, desktop, and utility structural debt at the configured thresholds.

- [ ] `W07.P14.S34` - Decompose graph compiler and node hotspots while retaining compiled-topology evidence.; `src/vaultspec_a2a/graph/compiler.py, src/vaultspec_a2a/graph/nodes`.
- [ ] `W07.P14.S35` - Decompose lifecycle discovery and singleton hotspots without weakening ownership checks.; `src/vaultspec_a2a/lifecycle`.
- [ ] `W07.P14.S36` - Decompose desktop filesystem and process-utility hotspots with real-process regression evidence.; `src/vaultspec_a2a/desktop, src/vaultspec_a2a/utils/process.py`.
- [ ] `W07.P14.S48` - Resolve every residual production complexity, shape, nesting, and size finding before any structural-sentinel graduation.; `src/vaultspec_a2a`.

## Wave `W08` - evidence-bound graduation and audit

Promote only verified zero-debt sentinels atomically and complete the required review and audit trail.

### Phase `W08.P15` - sentinel graduation

Independently prove and atomically promote each deterministic strict sentinel only after two clean locked runs at unchanged scope and threshold on one clean candidate commit, no new exclusion, suppression, baseline, or duplication, a passing just ci, applicable runtime evidence, and a passing anti-drift guard.

- [ ] `W08.P15.S49` - Review and classify production JSCPD findings before promotion to prove no deterministic sentinel reaches zero through duplicated code.; `.vault/audit, .vault/exec`.
- [ ] `W08.P15.S37` - Prove cross-platform Ty is zero and atomically promote type-platforms into the blocking aggregate.; `dev/toolchain.py, .github/workflows/test.yml`.
- [ ] `W08.P15.S38` - Prove Basedpyright strict is zero and atomically promote type-strict into the blocking aggregate.; `dev/toolchain.py, .github/workflows/test.yml`.
- [ ] `W08.P15.S39` - Prove cognitive complexity is zero on the corrected production scope and atomically promote complexity.; `dev/toolchain.py, .github/workflows/test.yml`.
- [ ] `W08.P15.S40` - Prove cyclomatic complexity is zero and atomically promote cyclomatic.; `dev/toolchain.py, .github/workflows/test.yml`.
- [ ] `W08.P15.S41` - Prove module and function shape is zero and atomically promote shape.; `dev/toolchain.py, .github/workflows/test.yml`.
- [ ] `W08.P15.S42` - Prove function limits are zero and atomically promote limits.; `dev/toolchain.py, .github/workflows/test.yml`.
- [ ] `W08.P15.S43` - Prove nesting is zero and atomically promote nesting.; `dev/toolchain.py, .github/workflows/test.yml`.
- [ ] `W08.P15.S44` - Prove size and design limits are zero and atomically promote size.; `dev/toolchain.py, .github/workflows/test.yml`.

### Phase `W08.P16` - closure and audit

Retain terminal advisory clone evidence and complete the mandatory implementation review and finding queue.

- [ ] `W08.P16.S45` - Recheck and classify production JSCPD findings after graduation without changing the advisory policy.; `.vault/audit, .vault/exec`.
- [ ] `W08.P16.S46` - Run formal code review, record every finding, and close the campaign only on full evidence.; `.vault/audit, .vault/exec`.

## Parallelization

W01 through W04 are complete historical work. W05 is sequential: P09 must
finish before P10 because hosted CI may only name targets that the declarative
registry owns. W06 begins after W05.P10. Within W06, P11 is serial through the
shared API fixture and portability contracts; after those foundations land, its
non-overlapping API partitions may proceed in parallel. P12 domain work may run
in parallel only where source and test ownership do not overlap, and it follows
the corresponding P11 contracts.

W07 begins after W06 establishes the relevant typed contracts. P13 steps are
independent only where their named provider, streaming, API, and control scopes
do not overlap; P14 may run alongside the non-overlapping P13 work. W08 is
strictly ordered after every remediation step. Its promotion Steps each require
the same clean candidate commit and cannot be checked from a partial or
concurrently changing tree. S45 and S46 are terminal.

## Verification

- Root `just ci` delegates to the sole declarative CI owner, and the hosted
  canonical job invokes that root command without restating tool commands.
- Every deterministic sentinel has one independent hosted result, with advisory
  visibility until its own evidence-bound graduation; JSCPD remains advisory.
- `type-platforms` runs Ty for Linux, Darwin, and Windows over the canonical
  Python roots; each platform result is retained separately.
- Every Terra step passes its named focused real-behavior tests, scoped typing
  check, format/lint check, and `git diff --check` before an execution record
  is written.
- A target joins `lint all` only with repeated clean evidence at the existing
  threshold, a passing canonical CI run, and an applicable integration verdict
  or precise out-of-scope explanation at the same commit.
- The campaign ends only after formal review classifies every finding, the audit
  queue owns all deferred work, and all plan steps are checked through the
  owning CLI.
