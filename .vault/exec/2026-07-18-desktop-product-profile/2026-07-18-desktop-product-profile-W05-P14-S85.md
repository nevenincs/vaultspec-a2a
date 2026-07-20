---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-20'
modified: '2026-07-20'
step_id: 'S85'
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
     The S85 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Run desktop target and Compose certification as required release checks without expected-failure shortcuts and ## Scope

- `.github/workflows/test.yml` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Run desktop target and Compose certification as required release checks without expected-failure shortcuts

## Scope

- `.github/workflows/test.yml`

## Description

- Added `desktop-certification` job to `.github/workflows/test.yml` with a three-target matrix (`x86_64-unknown-linux-gnu` on `ubuntu-24.04`, `aarch64-unknown-linux-gnu` on `ubuntu-24.04-arm`, `x86_64-pc-windows-msvc` on `windows-2022`). Each leg runs `just dev test service src/vaultspec_a2a/desktop_tests/` after syncing the full locked environment. Job depends on the existing `test` job.
- Added `compose-regression` job running on `ubuntu-latest` (Docker available). Runs `just dev test service src/vaultspec_a2a/service_tests/test_compose_profile_regression.py` after the `test` job.
- All actions pinned at existing SHA digests (matching the workflow's established pattern).
- YAML validated via PyYAML.

## Outcome

`.github/workflows/test.yml` now declares both `desktop-certification` and `compose-regression` as required checks that run on every push and pull request, blocking merge when either fails. Cannot be locally verified (GitHub Actions); the YAML is syntactically valid.

## Notes

Actions cannot be run locally; correctness is established by YAML validation and structural review. The `compose-regression` job builds Docker images from the repo Dockerfiles and runs the integration stack on ubuntu-latest, which has Docker available by default. The `desktop-certification` job runs `just dev test service` on three target runners, which exercises both pure-unit desktop tests and service-gated tests (capsule build needs internet access on CI runners, which is available in GitHub-hosted environments).
