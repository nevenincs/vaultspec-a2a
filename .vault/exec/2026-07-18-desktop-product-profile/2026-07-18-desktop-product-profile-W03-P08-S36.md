---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S36'
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
     The S36 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Validate dashboard-created attach and ownership files and create a distinct gateway-owned worker IPC credential with platform ACL checks and ## Scope

- `src/vaultspec_a2a/desktop/credentials.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Validate dashboard-created attach and ownership files and create a distinct gateway-owned worker IPC credential with platform ACL checks

## Scope

- `src/vaultspec_a2a/desktop/credentials.py`

## Description

- Add `src/vaultspec_a2a/desktop/_platform_acl.py` as the single cross-platform
  owner-restriction authority: POSIX mode-bit and Windows discretionary
  access-control-list restrict, verify, harden, and is-owner-restricted helpers.
- Add `src/vaultspec_a2a/desktop/credentials.py` modelling the three disjoint
  credential planes: validate the dashboard-created attach and ownership files
  fail-closed (regular non-link file, owner-restriction, bounded size, token
  format) and mint the gateway-owned worker interprocess-communication secret
  per boot under the same owner-restriction guarantee.
- Rewire `src/vaultspec_a2a/lifecycle/discovery.py` to consume the shared ACL
  authority, deleting its private native Windows ACL copies so both the
  discovery credential and the split desktop credentials share one authority.
- Certify the authority with real files in
  `src/vaultspec_a2a/desktop/tests/test_credentials.py`.

## Outcome

- Modified: `src/vaultspec_a2a/lifecycle/discovery.py`.
- Created: `src/vaultspec_a2a/desktop/_platform_acl.py`,
  `src/vaultspec_a2a/desktop/credentials.py`,
  `src/vaultspec_a2a/desktop/tests/test_credentials.py`.
- Typed fail-closed errors (`CredentialError`); no credential value reaches a
  message, log, or exception argument.
- The Windows access-control-list check closes the prior Windows descriptor
  enforcement gap: the strongest real check available stdlib-only is the
  private-DACL predicate (current user, SYSTEM, administrators; no inherited
  entries), the same guarantee the discovery credential already enforces.

## Notes

- Pre-existing vs added: the native Windows ACL machinery pre-existed inside
  the runtime discovery module; this Step promotes it to a shared authority and
  adds the credential plane split on top. No parallel ACL implementation now
  exists.
- Gates: ruff and ty clean on all touched files; the new credential suite and
  the discovery suite both pass. The POSIX permission-bit rejection case is the
  only skip on Windows, as it asserts a POSIX-only mode.
