---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S53'
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
     The S53 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Require a desktop gateway to spawn and own its worker without discovering adopting or evicting a Compose worker and ## Scope

- `src/vaultspec_a2a/control/worker_management.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Require a desktop gateway to spawn and own its worker without discovering adopting or evicting a Compose worker

## Scope

- `src/vaultspec_a2a/control/worker_management.py`

## Description

- Gate the worker spawn's discover, adopt, and evict block on the non-armed
  profiles: the armed desktop gateway now skips the pre-spawn health probe, the
  same-gateway adopt short-circuit, and the stale-orphan eviction entirely, and
  spawns its own worker unconditionally.
- Keep the Compose and development band behaviour intact: they still probe the
  worker port for an already-running same-gateway worker to adopt or a foreign
  stale orphan to evict before spawning.
- Declare a public optional demand-readiness event on the lazy worker spawner,
  defaulting to unset, that the armed gateway wires and the authenticated demand
  path fires once single-flight readiness is reached.

## Outcome

- The armed desktop gateway owns its worker exclusively: its runtime directory
  and worker port are private to the application home, so it never discovers,
  adopts, or evicts a Compose or foreign worker. Ownership therefore ties to the
  app home. The spawner field declared here formalizes the attribute the gateway
  lifespan already wires and gives the dispatch demand path a typed handle to
  fire.
- Gates: `ty` and `ruff` clean on the changed module. Suites:
  `pytest src/vaultspec_a2a/api src/vaultspec_a2a/control src/vaultspec_a2a/worker`
  504 passed, 8 deselected; top-level `desktop_tests` (`-m "not service"`,
  dependency-closure ignored) 23 passed, 26 deselected.

## Notes

- The combined desktop baseline could not collect five module-local capsule and
  package archive test files: a separate, uncommitted closure-inventory work
  stream owns those files and left their imports mid-refactor with a collection
  `NameError`. That failure is outside this Step's scope (control only), was
  absent before that concurrent work landed, and is not touched or repaired here;
  the top-level `desktop_tests` suite, which this change can actually affect, is
  fully green.
