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
