---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S49'
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
     The S49 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Return only a minimal alive or not-alive signal from unauthenticated HTTP liveness and return process and product identity plus state only from authenticated readiness responses and ## Scope

- `src/vaultspec_a2a/api/app.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Return only a minimal alive or not-alive signal from unauthenticated HTTP liveness and return process and product identity plus state only from authenticated readiness responses

## Scope

- `src/vaultspec_a2a/api/app.py`

## Description

- Split the top-level liveness endpoint under the armed desktop profile: an
  unauthenticated caller receives only the minimal liveness body (the single
  liveness fact and nothing else - no version, process id, profile, or state);
  an attach-authenticated caller additionally receives the readiness projection
  from the single readiness authority.
- Add `_http_attach_authorized`, a constant-time attach check mirroring the
  existing WebSocket attach gate, so the liveness boundary reuses the P08 attach
  credential without weakening it.
- Leave the Compose and development profiles on their existing aggregate liveness
  body so their probes stay green; readiness there remains on the separate
  aggregate endpoint.

## Outcome

`ruff` and `ty` pass on the module. The api suite passes: 321 passed. The armed
credential-boundaries certification, which drives a real armed child gateway and
reads unauthenticated liveness over real HTTP, passes: 1 passed - confirming the
minimal body still answers 200 and leaks no secret. Process and product identity
and the separated state facts now cross only the attach-authenticated boundary.

## Notes

The readiness projection is computed by the shared authority rather than
recomputed here, so the liveness surface and the service-state verb cannot
disclose divergent readiness. No Compose consumer of the aggregate readiness
endpoint is touched.

Follow-up closing a review finding: the aggregate liveness route was a second
ungated surface that still disclosed process identity and worker, circuit-breaker,
and backend state to unauthenticated callers. It now returns the same minimal
liveness body under the armed desktop profile, with the full aggregate body
retained for the Compose and development profiles their gateway healthchecks
consume. Every ungated liveness surface is now minimal under the armed profile.
