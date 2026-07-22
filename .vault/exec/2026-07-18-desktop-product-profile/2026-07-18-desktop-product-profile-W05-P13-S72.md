---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-20'
modified: '2026-07-20'
step_id: 'S72'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Build a real-process harness that installs invokes relocates and inspects a published desktop capsule

## Scope

- `src/vaultspec_a2a/desktop_tests/harness.py`

## Description

- Created `src/vaultspec_a2a/desktop_tests/harness.py` with `InstalledCapsule` dataclass, `build_and_install`, `relocate`, `seed_credentials`, `write_migration_descriptor`, `seat_valid_database`, `await_gateway_health`, `gateway_env`, `free_port`, `port_listening`, `clean_env`, and `offline_env` helpers.
- Used wheel-install approach (`uv build --wheel` + `uv export pylock.toml`) as the installed-capsule boundary; transport capsule (S13/CI) is out of scope for this step.
- Modelled relocation via `UV_OFFLINE=1` reinstall to prove the closed package inventory is self-contained after first install.
- Adopted `GATEWAY_SCRIPT` inline-uvicorn pattern matching existing W01-W04 test gates.
- Exposed `_MODULE`, `_PRESET`, `_REQUIRED_ROLE`, `_SPAWN_LINE` constants for consuming test modules.

## Outcome

`ruff check` clean. `ty check` clean. Baseline desktop suite (32 non-service tests) passes unmodified.

## Notes

Full transport capsule format (CPython + Node.js archives) requires S13 builder and CI runners; S76-S80 are the CI target-leg rows. This harness uses the wheel-install form, which is the correct installed-capsule boundary for the S73-S75 lifecycle gates and is documented explicitly in the module docstring.
