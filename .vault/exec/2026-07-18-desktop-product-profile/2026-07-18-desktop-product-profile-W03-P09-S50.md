---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S50'
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
     The S50 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Serve the same authenticated readiness facts through service-state and discovery probes and ## Scope

- `src/vaultspec_a2a/api/routes/gateway.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Serve the same authenticated readiness facts through service-state and discovery probes

## Scope

- `src/vaultspec_a2a/api/routes/gateway.py`

## Description

- Build the readiness projection in the service-state verb from the shared
  readiness authority, feeding it the live database and worker probe verdicts the
  verb already computes, and attach it to the service-state response.
- Reuse the single authority rather than recomputing the facts, so the same
  projection a discovery contender probes to validate readiness before attach is
  the one service-state serves - one computation, no drift with the liveness
  surface.

## Outcome

`ruff` and `ty` pass on the module. The api suite passes: 321 passed. The
service-state verb now carries the separated readiness facts (gateway readiness,
worker state, provider eligibility, run admission) alongside its existing
probe-backed status, and the doctor route signature is unchanged because only a
response field was added, not a route.

## Notes

Readiness on this authenticated verb is fed the real probe verdicts, so its
worker and database facts are probe-truthful here while the cheap liveness
surface derives them from seated state; both paths funnel through the one
assembler.
