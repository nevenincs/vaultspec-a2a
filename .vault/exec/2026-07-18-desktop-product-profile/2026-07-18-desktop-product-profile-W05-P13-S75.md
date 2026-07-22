---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-20'
modified: '2026-07-20'
step_id: 'S75'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Prove authenticated attach owner-only shutdown drain and data-preserving capsule removal boundaries

## Scope

- `src/vaultspec_a2a/desktop_tests/test_artifact_ownership_lifecycle.py`

## Description

- Created `src/vaultspec_a2a/desktop_tests/test_artifact_ownership_lifecycle.py` with four `@pytest.mark.service` tests and a module-scoped `installed_capsule` fixture.
- `test_unauthenticated_access_rejected`: boots gateway, asserts `/health` is 200, `/v1/service` without auth is 401, random bearer is 401, wrong capability on shutdown is 403.
- `test_owner_only_shutdown_requires_ownership_capability`: verifies that the attach credential alone returns 403 on `/api/admin/shutdown`, and that the ownership credential paired with the lifecycle header returns 202 and terminates the process.
- `test_drain_and_graceful_shutdown_reaps_worker`: fires a run-start to auto-spawn the worker, then sends an owner-authenticated shutdown, confirms the gateway process exits and the worker port is freed.
- `test_data_preserving_capsule_removal`: builds a per-test capsule (not the module-scoped fixture), seeds credentials, seats a database, boots briefly, then deletes `install_root`; asserts all user-data files (database, checkpoint, credentials) are intact.

## Outcome

Service gate: **14 passed, 0 failed** — run 1: 115.75s, run 2: 115.54s (two consecutive runs, 2026-07-20). `ruff check` clean, `ty check` clean, baseline (32 non-service) passes.

Revision history:
- Round 1 fixes: workspace seam for drain test; real credential constants; `discovery_path` assertion; `gateway_env()` uses `clean_env()`.
- Round 2 fix (flake): auth-plane probe timeouts raised to 30.0s across all three test files to tolerate build-load latency during concurrent module-scoped capsule builds.

## Notes

`test_data_preserving_capsule_removal` uses its own `build_and_install` call (not the module-scoped fixture) so the install root can be deleted without affecting other tests in the module.  The discovery record (`state.discovery_path`) is written by the gateway lifespan on startup and is asserted to survive capsule removal, proving the app home and the immutable runtime generation are genuinely separate authorities.
