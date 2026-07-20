---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S90'
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
     The S90 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Audit and harden per-run authoring MCP launch specifications to remain descendants of the owning provider group and ## Scope

- `src/vaultspec_a2a/providers/_acp_authoring.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Audit and harden per-run authoring MCP launch specifications to remain descendants of the owning provider group

## Scope

- `src/vaultspec_a2a/providers/_acp_authoring.py`

## Description

- Audit finding: `_acp_authoring.py` only BUILDS the per-run authoring bridge
  launch spec - an HTTP entry (no process) or a `python -m authoring_stdio` stdio
  entry. It spawns nothing. When the stdio transport is used, the ACP/Codex
  provider CLI spawns that bridge as its own child, so the bridge is a descendant
  of the run-owned provider root and already inherits that root's OS containment
  (`W04.P11.S60`). Nothing escapes the owning group; no hardening of the spawn
  path is needed.
- Document the process-topology contract in the module docstring so the
  containment reasoning stands with the code that builds the spec.
- Add an invariant-lock regression assertion
  (`providers/tests/test_authoring_stdio.py`): the bridge is a provider-child
  launch spec (a `command` + `-m` args, no live process), and no process-spawn
  primitive is reachable from the module namespace - the property that keeps the
  bridge contained.

## Outcome

The per-run authoring MCP bridge remains a descendant of the owning provider
group; audit confirms it is already contained, and the invariant is now locked
by a test. Gates: `ruff check`/`format` clean, `ty check` clean on
`_acp_authoring.py`. New test = 1 (10 passed in the module). Providers suite
`pytest providers` = 343 passed, 10 deselected.

## Notes

Audit-and-harden row with no spawn-path change: this module is a pure spec
builder and was already correct. The scoped change is the topology docstring and
the regression assertion, per the row's "already correct -> audit + regression
assertion" contract. The end-to-end reap of the authoring-bridge descendant on a
real run terminal is covered by the integrated proof (`W04.P11.S62`).
