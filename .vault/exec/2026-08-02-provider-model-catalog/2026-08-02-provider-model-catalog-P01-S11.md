---
tags:
  - '#exec'
  - '#provider-model-catalog'
date: '2026-09-05'
modified: '2026-09-05'
body_schema: 'body-v2'
body_hash: 'sha256:da8c303a60703a7694e7a6a73d64a8f7d8d5cc3a9d9448f6eb3fa4aa1b7dd6db'
step_id: 'S11'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---

# Prove catalog discovery, stale refusal, health separation, served validation, replay, frozen restart and legacy restart with real behavior; correct ER19 by asserting observed availability rather than a hardcoded unavailable state

## Scope

- `src/vaultspec_a2a/providers/tests/`
- `src/vaultspec_a2a/api/tests/`
- `src/vaultspec_a2a/service_tests/`

## Changes

- `M` `.vault/audit/2026-08-02-provider-model-catalog-implementation-review-audit.md`
- `M` `.vault/audit/2026-09-05-embedded-runtime-remediation-implementation-review-audit.md`
- `M` `.vault/audit/2026-09-05-embedded-runtime-robustness-audit.md`
- `A` `.vault/exec/2026-08-02-provider-model-catalog/2026-08-02-provider-model-catalog-P01-S11.md`
- `M` `.vault/index/provider-model-catalog.index.md`
- `M` `.vault/plan/2026-08-02-provider-model-catalog-plan.md`
- `M` `src/vaultspec_a2a/api/tests/test_provider_catalog_route.py`
- `verify:` `uv run --locked python -m pytest src/vaultspec_a2a/providers/tests/test_provider_catalog.py src/vaultspec_a2a/api/tests/test_provider_catalog_route.py src/vaultspec_a2a/providers/tests/test_team_selection.py src/vaultspec_a2a/api/tests/test_run_selection_schema.py src/vaultspec_a2a/api/tests/test_model_profiles_evidence.py src/vaultspec_a2a/api/tests/test_gateway_live.py::test_run_envelope_and_presets_list_agree_on_provider_readiness src/vaultspec_a2a/api/tests/test_gateway_live.py::test_run_start_replays_a_rotated_bundle_and_conflicts_on_a_changed_body src/vaultspec_a2a/api/tests/test_gateway_live.py::test_modern_selection_insert_race_and_direct_replay_disclose_same_freeze src/vaultspec_a2a/providers/tests/test_factory.py::test_factory_restarts_the_frozen_acp_backend_not_the_current_default src/vaultspec_a2a/graph/tests/test_compiler.py::test_resolve_worker_model_preferences_consumes_frozen_assignment -q --tb=short --no-showlocals -o log_cli=false` -> `pass` (49 passed)
- `verify:` `uv run --locked ruff format --check src/vaultspec_a2a/api/tests/test_provider_catalog_route.py` -> `pass`
- `verify:` `uv run --locked ruff check src/vaultspec_a2a/api/tests/test_provider_catalog_route.py` -> `pass`
- `verify:` `uv run --locked ty check src/vaultspec_a2a/api/tests/test_provider_catalog_route.py` -> `pass`
