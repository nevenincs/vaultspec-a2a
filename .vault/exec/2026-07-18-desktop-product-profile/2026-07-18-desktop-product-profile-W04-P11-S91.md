---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S91'
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
     The S91 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Audit and harden projected project MCP configuration so only run-owned launch specifications enter the isolated provider tree and ## Scope

- `src/vaultspec_a2a/providers/_acp_project_mcp.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Audit and harden projected project MCP configuration so only run-owned launch specifications enter the isolated provider tree

## Scope

- `src/vaultspec_a2a/providers/_acp_project_mcp.py`

## Description

- Audit finding: `_acp_project_mcp.py` only WRITES the run workspace `.mcp.json`;
  it spawns nothing. Every server it projects is launched by the ACP provider CLI
  as its own child, so it is a descendant of the run-owned provider root and
  inherits that root's OS containment (`W04.P11.S60`). The marked-entry merge
  plus the ancestor deny set already ensure ONLY run-owned launch specs (declared
  harness servers plus the run's own authoring bridge) enter that isolated
  provider tree; a foreign or ancestor-declared server never rides in. No spawn
  hardening is needed.
- Document the process-topology and run-ownership contract in the module
  docstring.
- Add an invariant-lock regression assertion
  (`providers/tests/test_acp_project_mcp.py`): `projected_declared_names` returns
  exactly the run-owned declared set; a foreign ancestor server is enumerated for
  the caller's deny set but never part of what enters the provider tree; and no
  process-spawn primitive is reachable from the module.

## Outcome

Only run-owned launch specifications enter the isolated provider tree, and every
projected server is a descendant of the contained provider root. Gates: `ruff
check`/`format` clean, `ty check` clean on `_acp_project_mcp.py`. New test = 1 (18
passed in the module). Providers suite green.

## Notes

Audit-and-harden row with no spawn-path change: the projection channel was
already correct (run-owned admission + ancestor deny). The scoped change is the
topology docstring and the regression assertion. End-to-end reap of a projected
MCP descendant on real run terminal is covered by the integrated proof
(`W04.P11.S62`).
