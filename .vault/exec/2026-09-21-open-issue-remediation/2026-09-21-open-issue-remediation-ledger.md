---
tags:
  - '#exec'
  - '#open-issue-remediation'
date: '2026-09-21'
modified: '2026-09-22'
body_schema: 'body-v2'
body_hash: 'sha256:ec1b31078e9e7b19237f69b30bb816b116859ed55307ef26e270378112d4550f'
related:
  - "[[2026-09-21-open-issue-remediation-plan]]"
---

# `open-issue-remediation` ledger

## Changes

- `S02` `A` `.vault/audit/2026-09-21-open-issue-remediation-audit.md`
- `S02` `verify:` `61 focused Dashboard Vitest cases` -> `pass`
- `S02` `by:` `dashboard_contracts-terra-high`
- `S03` `M` `.vault/adr/2026-09-21-workspace-root-authority-adr.md`
- `S03` `A` `.vault/adr/2026-09-21-workspace-root-authority-compose-provider-boundary-adr.md`
- `S03` `M` `.vault/plan/2026-09-21-open-issue-remediation-plan.md`
- `S03` `M` `.vault/audit/2026-09-21-open-issue-remediation-audit.md`
- `S06` `M` `.vault/audit/2026-09-21-open-issue-remediation-audit.md`
- `S06` `verify:` `vaultspec-core vault check annotations malformed-fixture` -> `fail`
- `S06` `M` `prek.toml`
- `S06` `A` `dev/vault_annotations_gate.py`
- `S06` `M` `dev/tests/test_prek_config.py`
- `S06` `verify:` `Core migration dry-run` -> `pass`
- `S06` `verify:` `pytest dev/tests/test_prek_config.py -q` -> `pass`
- `S06` `verify:` `prek run vault-sanitize-annotations --all-files --no-progress` -> `pass`
- `S06` `verify:` `ruff and ty focused checks` -> `pass`
- `S06` `verify:` `prek validate-config prek.toml` -> `pass`
- `S06` `by:` `readonly-hooks-luna-max`
- `S10` `by:` `readonly-hooks-luna-max`
- `S05` `M` `.github/workflows/test.yml`
- `S05` `M` `Justfile`
- `S05` `verify:` `just check-workflow (actionlint and CI contract)` -> `pass`
- `S05` `by:` `readonly-hooks-luna-max`
- `S03` `by:` `readonly-hooks-luna-max`
- `S10` `M` `service/docker-compose.dev.yml`
- `S10` `M` `service/docker-compose.integration.yml`
- `S10` `M` `service/docker-compose.prod.yml`
- `S10` `M` `service/docker/provider_identity_launcher.c`
- `S10` `M` `service/docker/service_entrypoint.py`
- `S10` `M` `service/README.md`
- `S10` `M` `service/docker/README.md`
- `S10` `M` `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`
- `S10` `M` `src/vaultspec_a2a/service_tests/test_compose_provider_service_state_isolation.py`
- `S10` `M` `.vault/adr/2026-09-21-workspace-root-authority-compose-provider-boundary-adr.md`
- `S10` `M` `.vault/audit/2026-09-21-open-issue-remediation-audit.md`
- `S10` `verify:` `Ruff and Ty focused checks` -> `pass`
- `S10` `by:` `vaultspec-high-executor`
- `S12` `by:` `metadata-integration-coordinator`
- `S11` `by:` `metadata-integration-coordinator`
- `S11` `M` `.env.example`
- `S11` `A` `src/vaultspec_a2a/api/tests/test_workspace_root_authority.py`
- `S11` `M` `src/vaultspec_a2a/control/tests/test_active_project_identity.py`
- `S11` `M` `src/vaultspec_a2a/control/thread_service.py`
- `S11` `M` `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`
- `S11` `A` `scripts/prepare_release.py`
- `S11` `M` `src/vaultspec_a2a/providers/tests/test_project_confinement.py`
- `S11` `A` `service/docker/service_entrypoint.py`
- `S11` `M` `src/vaultspec_a2a/control/tests/test_env_example_coverage.py`
- `S11` `verify:` `P01.S11 official Ty/type-policy/type-safety gate` -> `pass`
- `S01` `M` `src/vaultspec_a2a/lifecycle/manager.py`
- `S01` `M` `src/vaultspec_a2a/lifecycle/tests/test_manager.py`
- `S01` `M` `src/vaultspec_a2a/service_tests/test_cancel_health_trace.py`
- `S01` `verify:` `focused lifecycle suite 41 tests` -> `pass`
- `S01` `by:` `metadata-integration-coordinator`
- `S03` `A` `src/vaultspec_a2a/api/workspace.py`
- `S03` `M` `src/vaultspec_a2a/api/routes/_gateway_action_endpoints.py`
- `S03` `M` `src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py`
- `S03` `M` `src/vaultspec_a2a/api/routes/gateway.py`
- `S03` `M` `src/vaultspec_a2a/api/tests/test_active_run_discovery_live.py`
- `S03` `verify:` `workspace admission suite 67 tests` -> `pass`
- `S03` `by:` `metadata-integration-coordinator`
- `S04` `M` `.github/workflows/release.yml`
- `S04` `A` `.github/workflows/release-please.yml`
- `S04` `A` `.release-please-manifest.json`
- `S04` `A` `release-please-config.json`
- `S04` `A` `CHANGELOG.md`
- `S04` `M` `Justfile`
- `S04` `A` `scripts/prepare_release.py`
- `S04` `A` `scripts/tests/test_prepare_release.py`
- `S04` `verify:` `release workflow contract and hooks` -> `pass`
- `S04` `by:` `metadata-integration-coordinator`
- `S10` `M` `service/docker/prod.Dockerfile`
- `S10` `M` `src/vaultspec_a2a/control/infra_config.py`
- `S10` `M` `src/vaultspec_a2a/providers/_subprocess.py`
- `S10` `A` `src/vaultspec_a2a/providers/tests/test_provider_service_state_isolation.py`
- `S10` `M` `src/vaultspec_a2a/workspace/environment.py`
- `S10` `A` `src/vaultspec_a2a/workspace/tests/test_environment.py`
- `S10` `verify:` `provider workspace isolation suite 30 tests` -> `pass`
- `S10` `by:` `metadata-integration-coordinator`
- `S12` `M` `src/vaultspec_a2a/control/direct_control_recovery.py`
- `S12` `M` `src/vaultspec_a2a/control/event_handlers.py`
- `S12` `M` `src/vaultspec_a2a/worker/executor.py`
- `S12` `M` `src/vaultspec_a2a/worker/ipc.py`
- `S12` `M` `src/vaultspec_a2a/streaming/ingest.py`
- `S12` `M` `src/vaultspec_a2a/testing/__init__.py`
- `S12` `M` `src/vaultspec_a2a/testing/runner_child.py`
- `S12` `M` `src/vaultspec_a2a/api/tests/test_cancel_settled_run_status.py`
- `S12` `M` `src/vaultspec_a2a/control/tests/test_direct_control_recovery_current.py`
- `S12` `M` `src/vaultspec_a2a/control/tests/test_event_handlers.py`
- `S12` `M` `src/vaultspec_a2a/worker/tests/test_executor.py`
- `S12` `M` `src/vaultspec_a2a/worker/tests/test_ipc.py`
- `S12` `M` `src/vaultspec_a2a/streaming/tests/test_aggregator.py`
- `S12` `A` `src/vaultspec_a2a/service_tests/test_blocked_stream_cancellation.py`
- `S12` `verify:` `cancellation and streaming suite 200 tests` -> `pass`

## Notes

- `S02` Closed A2A issues #30 #31 #33 #34 #40 and created Dashboard issue #137 for the sole live recovery residue.
- `S02` Dashboard Rust tests were not run because configured X:/ci-shared/cargo/bin/cargo.exe was absent; alternate installed toolchains remain unchecked and the low tooling finding is queued in the audit.
- `S03` HIGH confirmed: shared /app/data and UID let admitted /app/data expose service.token and SQLite to ACP reads; path admission alone does not confine provider-native or terminal absolute reads. Superseding ADR accepted; P01.S10 blocks issue #25 closure until OS-denial proof passes.
- `S06` HIGH review finding: current read-only Core annotation check emits WARNING and exit 0 for malformed input; Step stays open pending strict read-only wrapper or supported strict mode with purity proof.
- `S06` Resolved the HIGH finding: Core annotation warnings previously exited 0; the wrapper fails on Core diagnostic totals and real clean/bad fixture runs prove exit 0/1 with unchanged bytes.
- `S06` LOW baseline finding queued: locked taplo fmt --check prek.toml fails on the pre-existing Core-managed block; taplo lint passes and no generated block was reformatted.
- `S06` LOW metadata finding queued: plan check emits PLAN022 because integration Step P02.S09 follows P01.S10; this reflects intentional phase placement and is not an S06 blocker.
- `S10` HIGH/security finding recorded: privileged ACP callbacks can resolve paths before no-follow read or write/create traversal, creating a TOCTOU escape window. S10 scope now owns _acp_rpc_handlers.py and test_project_confinement.py plus descriptor-relative Linux/Compose proof, directory anchoring, bounded handle lifetime, and fail-closed behavior; no proof claimed yet and issue #25 remains open.
- `S05` Independent review PASS: CI provisions the pinned kimi-cli 1.49.0 and the provider gate requires kimi-cli; all six intended Codex/Kimi cases ran with zero skips. The separate served-provider completed-turn eligibility lane remains unchanged; no paid live provider turn was used.
- `S05` Commit isolation constraint recorded: the shared worktree's normal staged hook isolation could not see concurrent S03 symbols, so the exact S06/S05 snapshots were validated and committed in a clean sibling worktree without bypassing hooks or staging other workers' files. Main integration remains coordinator-owned.
- `S03` Independent Terra review PASS recorded: canonicalize-before-validation fix at gateway.py:277; managed foreign/ancestor/symlink cases cover both stages; test_workspace_root_authority passed 14/14 with clean diff; Sol full review passed 67 tests plus Ruff/Ty. S03 remains open until its source commit is coordinated; issue #25 remains open for S10.
- `S12` Independent S12 review queued HIGH blocked-cancel-process-boundary and HIGH blocked-cancel-settlement-race findings, plus MEDIUM blocked-cancel-post-read-recheck; all remain REVISION REQUIRED. Architecture research is pending; keep P01.S12 open and do not claim cancellation closure.
- `S11` Integrated triage queued MEDIUM/CI-blocking locked-env-example-service-identity: src/vaultspec_a2a/control/tests/test_env_example_coverage.py deterministically fails because VAULTSPEC_PROVIDER_AGENT_UID, VAULTSPEC_PROVIDER_AGENT_GID, and VAULTSPEC_PROVIDER_IDENTITY_LAUNCHER added by P01.S10 in control/infra_config.py and Compose are absent from root .env.example. P01.S11 must document service-identity semantics rather than exclude required variables. Other 39 canonical failures passed in isolation and are classified as concurrent runtime contention; take no source action unless recurrence is observed. Keep S11 open.
- `S11` S11 findings locked-quality-type-policy, locked-quality-type-safety, locked-quality-format, and locked-env-example-service-identity are resolved by the reviewed nine-path snapshot and independent PASS. Five known basedpyright strict diagnostics are queued separately as non-gating follow-up; do not misclassify them as official Ty failures. Other 39 canonical failures passed in isolation and remain classified as concurrent runtime contention; no source action unless recurrence is observed.
- `S10` Eight Linux identity-launcher cases remain platform-excluded on this Windows host; prior real-image evidence is retained in the audit.
