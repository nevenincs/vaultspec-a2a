---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S54'
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
     The S54 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Trigger deferred reconciliation only after authenticated execution demand has completed worker single-flight readiness and ## Scope

- `src/vaultspec_a2a/control/dispatch.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Trigger deferred reconciliation only after authenticated execution demand has completed worker single-flight readiness

## Scope

- `src/vaultspec_a2a/control/dispatch.py`

## Description

- After the single-flight worker start completes on the dispatch demand path,
  fire the spawner's demand-readiness signal exactly once, and only when the
  worker is genuinely up.
- Leave the signal untouched for the Compose and development profiles, where it
  is unset and boot reconciliation stays eager.

## Outcome

- The authenticated execution demand path now releases the parked desktop boot
  reconciliation the moment the worker first reaches single-flight readiness:
  concurrent demand still starts exactly one worker (the existing spawn lock),
  and reconciliation of durable RECONCILING runs proceeds against the
  already-started worker rather than starting one at boot. The fire is idempotent
  and predicated on real readiness, so a failed start never wakes reconciliation
  onto a dead worker.
- Gates: `ty` and `ruff` clean on the changed module. Suites:
  `pytest src/vaultspec_a2a/api src/vaultspec_a2a/control src/vaultspec_a2a/worker`
  504 passed, 8 deselected; top-level `desktop_tests` (`-m "not service"`,
  dependency-closure ignored) 23 passed, 26 deselected.

## Notes

- The combined desktop baseline still cannot collect the same five module-local
  capsule and package archive test files broken by a separate uncommitted
  closure-inventory work stream; that failure is outside this Step's scope
  (control only) and is not touched here. The top-level `desktop_tests` suite is
  fully green.
