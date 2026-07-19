---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S92'
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
     The S92 and 2026-07-18-desktop-product-profile-plan placeholders are machine-filled by
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
     The Audit and harden declared harness MCP launch specifications to inherit the owning ACP or Codex provider group and ## Scope

- `src/vaultspec_a2a/providers/_acp_mcp.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Audit and harden declared harness MCP launch specifications to inherit the owning ACP or Codex provider group

## Scope

- `src/vaultspec_a2a/providers/_acp_mcp.py`

## Description

- Audit finding: `_acp_mcp.py` only RESOLVES the declared harness MCP launch
  specs (registry entries) for the ACP `session/new` surface and the Codex
  `config.toml`. It spawns nothing. The ACP/Codex provider CLI spawns each
  declared harness server as its own child, so it is a descendant of the
  run-owned provider root and inherits that root's OS containment
  (`W04.P11.S60`). Nothing escapes the owning group; no spawn hardening is needed.
- Document the process-topology contract in the module docstring.
- Add an invariant-lock regression assertion
  (`providers/tests/test_acp_mcp.py`): a resolved harness server is a
  provider-child launch spec (command + args, no live process), and no
  process-spawn primitive is reachable from the registry module.

## Outcome

Declared harness MCP servers inherit the owning ACP/Codex provider group; audit
confirms they are already contained, and the invariant is locked by a test.
Gates: `ruff check`/`format` clean, `ty check` clean on `_acp_mcp.py`. New test =
1 (36 passed across the two harness-MCP modules). Providers suite `pytest
providers` = 345 passed, 10 deselected.

## Notes

Audit-and-harden row with no spawn-path change: this registry is a pure spec
resolver and was already correct. The scoped change is the topology docstring and
the regression assertion. The end-to-end reap of a harness MCP descendant on a
real run terminal is covered by the integrated proof (`W04.P11.S62`). With this
Step, every `W04.P11` launch-spec/child audit row (`S89`-`S92`) is closed: only
the terminal children (`S89`) escaped and were hardened; the three spec-only
modules were confirmed already contained.
