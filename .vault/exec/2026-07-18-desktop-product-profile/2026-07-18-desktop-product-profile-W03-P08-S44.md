---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S44'
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
     The S44 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Use only the worker IPC credential for gateway-facing event heartbeat and health traffic and ## Scope

- `src/vaultspec_a2a/api/internal.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Use only the worker IPC credential for gateway-facing event heartbeat and health traffic

## Scope

- `src/vaultspec_a2a/api/internal.py`

## Description

- Route the internal WebSocket authentication through the one shared worker-IPC
  bearer authority instead of a duplicated inequality check, so every
  gateway-facing internal channel (events, heartbeat, health, and the WebSocket)
  enforces the same worker IPC credential rule.
- Certify over real HTTP that the internal readiness and heartbeat endpoints
  require the worker IPC credential and reject the attach credential, proving the
  two planes are non-interchangeable.

## Outcome

- Modified: `src/vaultspec_a2a/api/internal.py`.
- Created: `src/vaultspec_a2a/api/tests/test_internal_worker_ipc.py`.
- Pre-existing vs added: the HTTP internal endpoints were already gated with the
  worker IPC credential by the owner's landed router dependency; this Step aligns
  the WebSocket onto the same authority and adds the non-interchangeability
  certification.

## Notes

- Gates: ruff and ty clean; the new certification and the existing internal auth
  suite pass (39 passed in the internal-scoped selection).
