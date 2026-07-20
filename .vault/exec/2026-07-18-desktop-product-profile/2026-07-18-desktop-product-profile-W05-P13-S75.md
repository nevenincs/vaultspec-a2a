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

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace desktop-product-profile with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S75 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Prove authenticated attach owner-only shutdown drain and data-preserving capsule removal boundaries and ## Scope

- `src/vaultspec_a2a/desktop_tests/test_artifact_ownership_lifecycle.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

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

REVISION REQUIRED. Code reviewer ran the service suite; failures included tests in this module. `ruff check` and `ty check` are clean; baseline passes.

Failures diagnosed:
1. `test_drain_and_graceful_shutdown_reaps_worker`: uses `mock-success-single` via run-start but preset is excluded from wheel; workspace seam not wired.
2. `test_data_preserving_capsule_removal`: used wrong credential filenames (`attach-control.cred`, `ownership-capability.cred`) instead of the real constants `attach.cred` / `ownership.cap`; did not assert `discovery_path` survives capsule removal.
3. `gateway_env()` used `dict(os.environ)` instead of `clean_env()`.

## Notes

Step unchecked and revision in progress. Per revision plan: fix credential constants from `credentials.py`; add workspace seam for mock preset; add `discovery_path` assertion to the removal test.
