---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S43'
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
     The S43 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Enforce the worker IPC credential on dispatch events heartbeats health and administration and ## Scope

- `src/vaultspec_a2a/worker/app.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Enforce the worker IPC credential on dispatch events heartbeats health and administration

## Scope

- `src/vaultspec_a2a/worker/app.py`

## Description

- Require the worker interprocess-communication credential on the worker's
  `/health` endpoint, matching the existing dispatch and administrative-shutdown
  gates, so the whole worker surface is private to the gateway-worker pair.
- Authenticate the gateway's own health probes with the shared worker IPC bearer
  so a worker that now enforces the credential on `/health` still answers its
  paired gateway: add a single `_internal_auth_headers` authority and present it
  on the watchdog/boot health probe and the provenance fetch, and reconcile the
  eviction path onto the same authority.
- Certify the `/health` gate over real HTTP: reject a missing or wrong bearer,
  accept the paired bearer, and leave a DEVELOPMENT worker with no token open.

## Outcome

- Modified: `src/vaultspec_a2a/worker/app.py`,
  `src/vaultspec_a2a/control/worker_management.py`.
- Modified (tests): `src/vaultspec_a2a/worker/tests/test_app.py`.
- Pre-existing vs added: dispatch and administrative shutdown were already gated
  with the worker IPC bearer by the owner's landed IPC auth; this Step extends the
  gate to `/health` and adds the counterpart probe authentication so the gate does
  not regress the watchdog or spawn provenance path.

## Notes

- The probe-authentication change touches the worker-management module because a
  gated worker `/health` is only correct if the gateway's own liveness probes
  present the shared bearer; without it the watchdog would read a paired worker as
  down and crash-loop it. The change is additive and reconciled onto one
  header authority.
- Gates: ruff and ty clean; the worker suite (86 passed) and the control suite
  (97 passed, including the worker-provenance token tests) both pass.
