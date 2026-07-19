---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S48'
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
     The S48 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Make a valid desktop database with a cold startable worker gateway-ready without claiming execution readiness and ## Scope

- `src/vaultspec_a2a/control/health.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Make a valid desktop database with a cold startable worker gateway-ready without claiming execution readiness

## Scope

- `src/vaultspec_a2a/control/health.py`

## Description

- Add `assemble_desktop_readiness`, the single readiness authority. It derives
  the five bounded facts from seated application state and shared health data:
  gateway readiness turns only on a valid database, so a live gateway over a
  valid database reads ready even while its worker is cold.
- Treat an unspawned worker as `cold` (informational), not degradation, and map
  spawned worker status onto the `starting`/`ready`/`unavailable` ladder.
- Compute run admission as the distinct execution-readiness fact: a reachable
  worker plus an eligible provider is `ready`; a cold or starting worker over a
  ready gateway is `deferred`; a failed hard dependency is `blocked`.
- Add `_eligible_provider_names`, which resolves provider eligibility through the
  no-instantiation classify seam - no model is constructed and no subprocess is
  spawned. Accept caller-supplied live database and worker probe verdicts so the
  probe-backed service-state path and the cheap sync liveness path share one
  computation.

## Outcome

`ruff` and `ty` pass on the module. An in-process probe confirms the intended
semantics: a valid database with an unspawned worker reports gateway readiness
`ready`, worker state `cold`, and run admission `deferred` - gateway-ready but
not execution-ready - while an absent database reports `not_ready` and `blocked`.
The control suite passes: 97 passed, 6 deselected.

## Notes

This Step only adds the authority; the liveness endpoint and the service-state
verb that consume it land in the following Steps. No call site references the new
function yet, so the api and desktop surfaces are unchanged. The shared desktop
baseline's pre-existing failures remain confined to the concurrently-owned
closure-inventory work and are untouched here.
