---
tags:
  - '#exec'
  - '#tool-cores'
date: '2026-07-17'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:617ac433656a0d8e568f3815dbc7c90cf927ae4f8d4b4996efda8e52a2cf50d9'
related:
  - "[[2026-07-17-tool-cores-plan]]"
---

<!-- Machine-owned: filename and frontmatter, scaffolded by
     `vaultspec-core vault exec log`; never hand-edit. Add no
     frontmatter fields. Wiki-links belong in `related:` only, never in the body.

     ONE ledger per plan, replacing one document per Step. The Step identity
     the plan's ids provide moves from the filename into the row's first
     column, so a Step still maps to a real artifact. -->

# `tool-cores` ledger

## Changes

<!-- MECHANICAL LOG, append-only, one line per path touched per Step:
       - `S##` `A` `path`   added
       - `S##` `M` `path`   modified
       - `S##` `D` `path`   deleted
       - `S##` `R` `old` -> `new`   renamed
     Paths are repo-relative, in backticks. No prose, no sentences: the Step
     row states the intent and the commit carries the diff. Example:

       - `S01` `M` `src/vaultspec_core/cli/exec_cmd.py`
       - `S01` `A` `src/vaultspec_core/cli/tests/test_exec_cmd.py`
       - `S02` `D` `src/legacy/shim.py`

     Optional per-Step check line:
       - `S01` `verify:` `<command>` -> `pass` | `fail`

     Rows are appended in Step order and never rewritten. Only rows in this
     section register a Step as covered; a `## Notes` section is added ONLY on
     exception (data loss, skipped work, a scaffold left in code, a persistent
     failure) and is otherwise omitted. -->
- `S01` `T` `src/vaultspec_a2a/graph/nodes/worker.py`
- `S02` `T` `src/vaultspec_a2a/team/presets/agents/vaultspec-researcher.toml`
- `S03` `T` `src/vaultspec_a2a/graph/nodes/worker.py`
- `S04` `T` `src/vaultspec_a2a/providers/_acp_authoring.py`
- `S05` `T` `src/vaultspec_a2a/service_tests/`
- `S06` `T` `package.json`
- `S07` `T` `src/vaultspec_a2a/providers/factory.py`
- `S08` `T` `src/vaultspec_a2a/providers/`
- `S09` `T` `src/vaultspec_a2a/service_tests/`
- `S10` `T` `src/vaultspec_a2a/providers/_acp_mcp.py`
- `S11` `T` `src/vaultspec_a2a/graph/nodes/worker.py`
- `S12` `T` `src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research.toml`
- `S13` `T` `src/vaultspec_a2a/providers/acp_chat_model.py`
- `S14` `T` `src/vaultspec_a2a/providers/acp_chat_model.py`
- `S15` `T` `src/vaultspec_a2a/team/presets/agents/vaultspec-researcher.toml`
- `S16` `T` `src/vaultspec_a2a/service_tests/`
- `S17` `T` `src/vaultspec_a2a/service_tests/`
- `S18` `T` `src/vaultspec_a2a/providers/codex_chat_model.py`
- `S19` `T` `src/vaultspec_a2a/providers/codex_chat_model.py`
- `S20` `T` `src/vaultspec_a2a/service_tests/`
- `S21` `T` `src/vaultspec_a2a/service_tests/`
- `S22` `T` `src/vaultspec_a2a/providers/_acp_mcp.py`
- `S23` `T` `.vault/`
- `S24` `T` `.vault/audit/`
- `S25` `T` `.vault/exec/`

