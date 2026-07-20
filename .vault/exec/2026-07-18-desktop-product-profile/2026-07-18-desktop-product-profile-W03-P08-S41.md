---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S41'
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
     The S41 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Require attach authentication before accepting desktop event WebSockets and ## Scope

- `src/vaultspec_a2a/api/app.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Require attach authentication before accepting desktop event WebSockets

## Scope

- `src/vaultspec_a2a/api/app.py`

## Description

- Require the attach credential on the desktop event WebSocket: reject and close
  an unauthenticated or wrong-credential client with the policy-violation code
  before the connection is accepted; constant-time comparison.
- Load the armed desktop credential planes at application creation: replace the
  generated attach token with the dashboard-created attach credential, load the
  receipt-bound ownership capability, and mint the worker interprocess secret.
- Close the versioned-record publication seam: after bind, an armed gateway
  publishes the versioned, secret-free desktop discovery record keyed to the held
  runtime singleton, naming only the ACL-protected attach-credential reference,
  and heartbeats it on the shared cadence. The unarmed Compose path is unchanged.
- Certify the WebSocket gate over a real ASGI handshake.

## Outcome

- Modified: `src/vaultspec_a2a/api/app.py`.
- Created: `src/vaultspec_a2a/api/tests/test_ws_attach_gate.py`.
- Pre-existing vs added: the Compose discovery publication and heartbeat are the
  owner's landed path, left intact; the armed desktop branch (credential loading,
  versioned-record publication, and its heartbeat) is added beside it.

## Notes

- The WebSocket attach gate is certified here with a real handshake. The armed
  credential loading and the versioned-record publication run only on an armed
  boot against real dashboard files and a held singleton; they are exercised
  end-to-end by the real-process credential-boundary certification, which
  byte-scans the published discovery record for any secret.
- Gates: ruff and ty clean; the full `src/vaultspec_a2a/api` suite passes
  (314 passed).
