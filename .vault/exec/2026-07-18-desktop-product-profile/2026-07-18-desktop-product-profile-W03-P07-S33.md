---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S33'
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
     The S33 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Acquire the desktop singleton before invoking Uvicorn socket bind and pass its ownership into gateway startup and ## Scope

- `src/vaultspec_a2a/cli/main.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Acquire the desktop singleton before invoking Uvicorn socket bind and pass its ownership into gateway startup

## Scope

- `src/vaultspec_a2a/cli/main.py`

## Description

- Acquire the desktop runtime singleton in the gateway serve entrypoint before
  the application boots, so the socket bind and discovery publication follow
  sole ownership of the application home; release it when the gateway stops.
- Fail loud on a live foreign or unverifiable resident: the conflict raises a
  non-zero `ClickException` carrying the immutable-conflict classification, so a
  second gateway never competes for one application home.
- Register the held singleton as the process's active owner through a small
  process-global holder so the gateway lifetime can read it; the acquisition runs
  only when the desktop profile is armed and is a no-op for Compose and plain
  foreground serve.
- Leave an explicit, documented seam for the versioned secret-free discovery
  publication (owner keyed to the held singleton, after bind and control-auth
  setup); acquisition and ownership registration are wired now, publication lands
  with the gateway credential work.
- Add a real test: a child interpreter holds the singleton over an application
  home while the serve-path acquisition is exercised in-process and must fail
  loud, plus a free-home acquire that registers and clears the active owner.

## Outcome

The desktop gateway takes sole ownership before it binds and refuses a foreign
resident loudly. Gates: `ruff` and `ty` clean on the changed modules;
`pytest src/vaultspec_a2a/cli -q` 38 passed; `pytest src/vaultspec_a2a/lifecycle -q`
117 passed. The two-real-gateway certification lands in `S34`.

## Notes

The Windows re-exec caveat is handled by design: `desktop-serve` re-execs a fresh
interpreter whose launcher stub carries a different pid than the real gateway
worker, so ownership is certified through the singleton record and its start
fingerprint, never the launch handle. This Step spans two files — the serve
entrypoint and a small process-global holder in the singleton module (its natural
home, importable by the future gateway lifetime without a reverse dependency on
the CLI). A concurrent authentication campaign holds uncommitted edits to the
same serve module's request-auth helper; only this Step's serve-path hunks were
staged through `git apply --cached`, leaving the campaign's working-tree changes
in place. The discovery-publication call is a deliberate seam, not a stub, and
lands in `W03.P08`.
