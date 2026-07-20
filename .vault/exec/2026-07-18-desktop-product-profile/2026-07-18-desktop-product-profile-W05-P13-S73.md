---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-20'
modified: '2026-07-20'
step_id: 'S73'
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
     The S73 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Prove clean offline install relocation cold readiness lazy worker and default ACP execution from one real capsule and ## Scope

- `src/vaultspec_a2a/desktop_tests/test_artifact_install.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Prove clean offline install relocation cold readiness lazy worker and default ACP execution from one real capsule

## Scope

- `src/vaultspec_a2a/desktop_tests/test_artifact_install.py`

## Description

- Created `src/vaultspec_a2a/desktop_tests/test_artifact_install.py` with five `@pytest.mark.service` tests and a module-scoped `installed_capsule` fixture.
- `test_offline_install_seats_valid_database`: drives `desktop-migrate` CLI, verifies alembic head revision is written to a database path that is not inside the capsule.
- `test_capsule_relocation_preserves_state_independence`: seats a database at path A, relocates capsule to path B, verifies both python interpreters can read the same alembic revision.
- `test_cold_readiness_from_installed_capsule`: boots gateway, asserts `liveness=alive`, `worker_state=cold`, `run_admission=deferred`.
- `test_lazy_worker_from_installed_capsule`: fires four concurrent run-starts via ThreadPoolExecutor, asserts all 201, asserts exactly one `_SPAWN_LINE` in the log.
- `test_default_acp_execution_mock_seam`: runs the full run-start path via `mock-success-single` preset (disclosed seam), verifies a durable run record exists.

## Outcome

Service gate: **14 passed, 0 failed** — run 1: 115.75s, run 2: 115.54s (two consecutive runs, 2026-07-20). `ruff check` clean, `ty check` clean, baseline (32 non-service) passes.

Revision history:
- Round 1 fixes: workspace-override seam for mock presets, `gateway_env()` uses `clean_env()`.
- Round 2 fix (flake): auth-plane probe timeouts raised from 5.0s/10.0s to 30.0s across all three test files so concurrent module-scoped capsule builds cannot cause spurious timeout failures on a loaded host.

## Notes

`mock-success-single` and `mock-coder-success` are non-product test presets seeded exclusively via the workspace-override seam (team_config.py discovery order, workspace takes precedence). Disclosed in module docstring and `seed_workspace_preset` docstring. External ACP provider (Claude CLI) remains the production execution path and is not installable offline; this gate proves the installed package's run-start wiring end-to-end using the mock-provider seam.
