---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

<!-- DO NOT add 'Related:', 'tags:', 'date:', or other frontmatter fields
     outside the YAML frontmatter above -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `entry-point-layer` `phase10` `step1`

Fixed `cli/_agent.py` filesystem bypass (D-11). Removed hardcoded
`Path(...) / "core" / "presets" / "agents"` referencing the pre-Layer-1
directory. Routed preset discovery through the domain service.

- Modified: `src/vaultspec_a2a/cli/_agent.py`
- Modified: `src/vaultspec_a2a/team/team_config.py`

## Description

The `list` and `show` commands in `cli/_agent.py` used a hardcoded
`Path(__file__).resolve().parent.parent / "core" / "presets" / "agents"`
path that referenced the old pre-Layer-1 `core/` directory. After the
Layer 1 decomposition, agent presets live under `team/presets/agents/`.

The fix:

- Added `discover_agent_preset_ids()` to `team_config.py`, analogous to
  the existing `discover_team_preset_ids()`. It globs
  `team/presets/agents/*.toml` and returns a frozenset of stems.

- Rewrote `cli/_agent.py` `list` command to call
  `discover_agent_preset_ids()` instead of globbing the filesystem.

- Rewrote `cli/_agent.py` `show` command to call `load_agent_config()`
  which uses the two-level discovery order (workspace override, then
  bundled preset). The `show` command now renders structured fields from
  the validated Pydantic model instead of dumping raw TOML.

- Removed the `pathlib.Path` import entirely from `_agent.py` -- the
  module no longer touches the filesystem directly.

## Tests

- 595 passed, 43 deselected (1 pre-existing failure unrelated to this
  change: `test_provider_factory_claude_creates_acp` requires `npm install`).
- Ruff lint passes cleanly on both modified files.
- Smoke-tested `discover_agent_preset_ids()` and `load_agent_config()`
  via Python REPL: both return correct results from `team/presets/agents/`.
