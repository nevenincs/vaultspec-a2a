---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S23'
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
     The S23 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Expose the internal desktop migrate command while keeping lifecycle verbs off the public run-control API and ## Scope

- `src/vaultspec_a2a/cli/main.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Expose the internal desktop migrate command while keeping lifecycle verbs off the public run-control API

## Scope

- `src/vaultspec_a2a/cli/main.py`

## Description

- Add an internal `desktop-migrate` command to the operator CLI that takes a
  required descriptor path, runs the staged-generation migration entrypoint in a
  fresh event loop, prints the bounded machine-readable result as sorted JSON to
  stdout, and exits zero only when the migration succeeds.
- Name the command flat (`desktop-migrate`), matching the existing
  `desktop-serve` convention, and keep it off the HTTP run-control router so the
  lifecycle verb stays CLI-only.

## Outcome

The dashboard external updater can drive the staged migration through one
internal CLI verb whose JSON result and exit code reflect the outcome. Proven by
real child-process CLI runs: a fresh store migrates and the command prints a
success result and exits zero; a mismatched descriptor prints a failed result
naming the descriptor stage and exits non-zero; a missing descriptor is a usage
error; and route-signature inspection proves no run-control HTTP route carries the
migration verb. New tests 4/4 green; `desktop-serve` and provision CLI suites
16/16; touched files pass ruff and ty.

## Notes

None.
