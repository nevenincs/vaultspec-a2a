---
tags:
  - '#exec'
  - '#container-release'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:6f7e5ecc7aeaab1133291d59b4f75d50154cf46d08e07952a20c1c32f46f132c'
related:
  - "[[2026-10-04-container-release-plan]]"
---

# `container-release` ledger

## Changes

- `S01` `A` `dev/container_release.py`
- `S01` `M` `Justfile`
- `S01` `M` `.github/workflows/test.yml`
- `S01` `M` `dev/tests/test_release_workflow_contract.py`
- `S01` `verify:` `ruff check and format changed Python` -> `pass`
- `S01` `verify:` `ty check changed Python` -> `pass`
- `S01` `verify:` `pytest dev/tests/test_release_workflow_contract.py (6 tests)` -> `pass`
- `S01` `verify:` `python -m dev.ci_contract` -> `pass`
- `S01` `verify:` `python -m dev.container_release --ref e97c7adca6dc02d78162815404eb9f62ac124f55` -> `pass`
- `S02` `A` `dev/container_publish.py`
- `S02` `A` `dev/tests/test_container_publish.py`
- `S02` `M` `dev/container_release.py`
- `S02` `M` `.github/workflows/release.yml`
- `S02` `M` `Justfile`
- `S02` `M` `dev/tests/test_release_workflow_contract.py`
- `S02` `M` `service/README.md`
- `S02` `A` `.vault/adr/2026-10-04-container-release-adr.md`
- `S02` `verify:` `ruff changed Python` -> `pass`
- `S02` `verify:` `ty changed Python` -> `pass`
- `S02` `verify:` `pytest container receipt and release workflow contracts (19 tests)` -> `pass`
- `S02` `verify:` `actionlint release.yml and test.yml` -> `pass`
- `S02` `verify:` `python -m dev.ci_contract` -> `pass`
- `S03` `M` `.env.example`
- `S03` `D` `.github/workflows/deploy-containers.yml`
- `S03` `M` `.github/workflows/merge-gate.yml`
- `S03` `M` `.github/workflows/release.yml`
- `S03` `M` `.github/workflows/test.yml`
- `S03` `M` `.vault/adr/2026-03-20-service-lifecycle-architecture-adr.md`
- `S03` `M` `.vault/adr/2026-09-21-workspace-root-authority-compose-provider-boundary-adr.md`
- `S03` `M` `.vault/adr/2026-10-04-container-release-adr.md`
- `S03` `M` `.vault/audit/2026-10-04-container-release-audit.md`
- `S03` `M` `.vault/index/container-release.index.md`
- `S03` `M` `.vault/plan/2026-10-04-container-release-plan.md`
- `S03` `M` `Justfile`
- `S03` `M` `README.md`
- `S03` `D` `dev/audit/mcp_probe_isolation.py`
- `S03` `D` `dev/container_deploy.py`
- `S03` `D` `dev/container_publish.py`
- `S03` `D` `dev/container_release.py`
- `S03` `M` `dev/credentials.py`
- `S03` `D` `dev/tests/test_container_publish.py`
- `S03` `M` `dev/tests/test_credentials_settings_file.py`
- `S03` `M` `dev/tests/test_release_workflow_contract.py`
- `S03` `M` `dev/toolchain.py`
- `S03` `M` `docs/architecture.rst`
- `S03` `M` `docs/operations.rst`
- `S03` `M` `pyproject.toml`
- `S03` `M` `service/README.md`
- `S03` `D` `service/docker-compose.dev.yml`
- `S03` `M` `service/docker-compose.integration.yml`
- `S03` `D` `service/docker-compose.prod.postgres.yml`
- `S03` `D` `service/docker-compose.prod.yml`
- `S03` `D` `service/docker-compose.release.yml`
- `S03` `M` `service/docker/README.md`
- `S03` `D` `service/docker/dev.Dockerfile`
- `S03` `D` `service/docker/prod.Dockerfile`
- `S03` `D` `service/docker/provider_identity_launcher.c`
- `S03` `D` `service/docker/service_entrypoint.py`
- `S03` `M` `src/vaultspec_a2a/control/infra_config.py`
- `S03` `M` `src/vaultspec_a2a/control/tests/_env_example.py`
- `S03` `D` `src/vaultspec_a2a/control/tests/test_deployment_names.py`
- `S03` `M` `src/vaultspec_a2a/control/tests/test_env_example_coverage.py`
- `S03` `M` `src/vaultspec_a2a/control/tests/test_env_example_drift.py`
- `S03` `M` `src/vaultspec_a2a/service_tests/conftest.py`
- `S03` `M` `src/vaultspec_a2a/service_tests/harness.py`
- `S03` `M` `src/vaultspec_a2a/service_tests/test_cancel_health_trace.py`
- `S03` `D` `src/vaultspec_a2a/service_tests/test_compose_profile_regression.py`
- `S03` `D` `src/vaultspec_a2a/service_tests/test_compose_provider_service_state_isolation.py`
- `S03` `A` `.vault/adr/2026-10-04-container-release-native-production-adr.md`
- `S03` `A` `src/vaultspec_a2a/service_tests/test_development_fixture_boundary.py`
- `S03` `A` `src/vaultspec_a2a/service_tests/test_worker_attach_provenance.py`
- `S03` `verify:` `native lifecycle cancellation and real Jaeger trace (3 tests)` -> `pass`
- `S03` `verify:` `fixture boundary and native worker provenance (13 tests)` -> `pass`
- `S03` `verify:` `native launcher registry identity and desktop refusal (24 tests)` -> `pass`
- `S03` `verify:` `environment coverage and drift (18 tests)` -> `pass`
- `S03` `verify:` `tooling release and credential contracts (20 tests)` -> `pass`
- `S03` `verify:` `documentation tests (6 tests) and strict Sphinx` -> `pass`
- `S03` `verify:` `Ruff and ty changed Python` -> `pass`
- `S03` `verify:` `just check-workflow` -> `pass`
- `S03` `verify:` `just test-native-integration` -> `pass`

## Notes

- `S02` GHCR push and receipt attestation require a real release workflow run; no external publication performed.
- `S03` Owner corrected scope: native production only; Docker fixtures limited to Jaeger and VidaiMock. Historical S01/S02 reversed without rewriting their records.
- `S03` Native OS isolation and additional root-component/create-directory race cases remain follow-ups; no parity claim with retired container proof.
