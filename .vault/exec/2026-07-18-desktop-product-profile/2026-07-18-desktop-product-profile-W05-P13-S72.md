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

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace desktop-product-profile with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S72 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Build a real-process harness that installs invokes relocates and inspects a published desktop capsule and ## Scope

- `src/vaultspec_a2a/desktop_tests/harness.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

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
