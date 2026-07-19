---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S47'
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
     The S47 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Define separate liveness gateway readiness worker state provider eligibility and run-admission fields and ## Scope

- `src/vaultspec_a2a/api/schemas/gateway.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Define separate liveness gateway readiness worker state provider eligibility and run-admission fields

## Scope

- `src/vaultspec_a2a/api/schemas/gateway.py`

## Description

- Add five bounded `StrEnum` facts to the gateway wire schema: `LivenessState`,
  `GatewayReadiness`, `WorkerLifecycleState`, `ProviderEligibility`, and
  `RunAdmission`. Each documents its own axis so no consumer collapses process
  liveness, gateway readiness, worker state, provider eligibility, and run
  admission into a single boolean.
- Add `LivenessResponse`, a deliberately minimal model carrying only the
  liveness fact for the unauthenticated liveness surface.
- Add `DesktopReadiness`, the authenticated projection carrying process identity
  (`gateway_pid`), product identity (`generation`, `profile`), the five facts,
  the bounded eligible-provider list, and bounded path-free reasons.
- Extend `ServiceStateResponse` with an optional nested `readiness` so the
  service-state verb can serve the same projection, and rebuild the model to
  resolve the forward reference.

## Outcome

Schema layer compiles, imports, and constructs cleanly; `ruff` and `ty` pass on
the file. The `WorkerLifecycleState` ladder (`cold` to `starting` to `ready`,
with `unavailable` for post-demand degradation) and the `RunAdmission` triad
(`ready`/`deferred`/`blocked`) together let a cold, startable worker read as
gateway-ready yet not execution-ready. No behaviour change lands in this Step;
the assembler and endpoints that populate the new fields follow.

## Notes

The shared desktop baseline suite shows 15 pre-existing failures confined to the
concurrently-owned untracked closure-inventory and lock-reconciliation work
(`artifacts.py`, `closure_inventory.py`, `lock_reconciliation.py` and their
tests); those files are outside this Step and were neither read nor staged. The
remaining baseline is green.
