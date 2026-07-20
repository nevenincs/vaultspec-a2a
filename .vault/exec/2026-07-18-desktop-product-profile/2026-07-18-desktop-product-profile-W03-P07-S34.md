---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S34'
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
     The S34 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Prove two real desktop gateway processes cannot own or overwrite one app home and ## Scope

- `src/vaultspec_a2a/desktop_tests/test_runtime_singleton.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Prove two real desktop gateway processes cannot own or overwrite one app home

## Scope

- `src/vaultspec_a2a/desktop_tests/test_runtime_singleton.py`

## Description

- Add a real-process certification that spawns child interpreters running the
  production desktop ownership surface: acquire the runtime singleton over an
  explicit application home (as the serve path does before bind), then publish
  the versioned discovery record.
- Prove a second gateway against the same application home fails loud at
  acquisition (non-zero exit carrying the conflict classification) and never
  reaches discovery publication, so the first gateway's record is byte-for-byte
  intact after the failed contender.
- Prove that after the first gateway is really killed its runtime singleton
  reads STALE, and a same-owner restart reclaims the home through stale
  classification and republishes its own discovery record.
- Certify ownership through the published discovery and singleton records — the
  real gateway process identity — never the launch handle, since desktop-serve
  re-execs a fresh interpreter whose launcher pid differs from the gateway's.

## Outcome

Two real desktop gateways cannot own or overwrite one application home, and an
owner-matching restart after a real kill recovers cleanly. Gates: `ruff` clean;
`pytest src/vaultspec_a2a/desktop_tests/test_runtime_singleton.py -q` 2 passed.

## Notes

The certification drives the singleton-then-publish serve surface directly
rather than booting a full Uvicorn gateway, which would require a real capsule
and database; this is the "minimal real desktop-serve path against real app
homes" the Step contemplates and exercises the exact ordering the gateway uses.
Full attach authentication and the gateway's own publication of this record land
in `W03.P08`.
