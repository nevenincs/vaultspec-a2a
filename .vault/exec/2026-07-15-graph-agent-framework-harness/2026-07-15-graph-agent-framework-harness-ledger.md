---
tags:
  - '#exec'
  - '#graph-agent-framework-harness'
date: '2026-07-15'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:5827a96cc3b70756ddc5db05a202b8eccae1e8f515894fcdc49d9c6e056aabb5'
related:
  - "[[2026-07-15-graph-agent-framework-harness-plan]]"
---

<!-- Machine-owned: filename and frontmatter, scaffolded by
     `vaultspec-core vault exec log`; never hand-edit. Add no
     frontmatter fields. Wiki-links belong in `related:` only, never in the body.

     ONE ledger per plan, replacing one document per Step. The Step identity
     the plan's ids provide moves from the filename into the row's first
     column, so a Step still maps to a real artifact. -->

# `graph-agent-framework-harness` ledger

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
- `S01` `T` `src/vaultspec_a2a/authoring/submitter.py`
- `S01` `T` `src/vaultspec_a2a/graph/nodes/phase_gate.py`
- `S01` `T` `src/vaultspec_a2a/team/presets/agents/vaultspec-researcher.toml`
- `S01` `T` `vaultspec-synthesist.toml`
- `S01` `T` `vaultspec-adr-author.toml`
- `S01` `T` `vaultspec-doc-reviewer.toml`
- `S02` `T` `.vault/exec/2026-07-15-graph-agent-framework-harness/2026-07-15-graph-agent-framework-harness-P01-summary.md`
- `S03` `T` `.vaultspec/rules/`
- `S03` `T` `.vaultspec/templates/adr.md`
- `S03` `T` `research.md`
- `S03` `T` `plan.md`
- `S03` `T` `audit.md`
- `S03` `T` `ref-audit.md`
- `S04` `T` `src/vaultspec_a2a/context/rules.py`
- `S05` `T` `src/vaultspec_a2a/team/presets/agents/vaultspec-researcher.toml`
- `S06` `T` `src/vaultspec_a2a/team/presets/agents/vaultspec-synthesist.toml`
- `S07` `T` `src/vaultspec_a2a/team/presets/agents/vaultspec-adr-author.toml`
- `S08` `T` `src/vaultspec_a2a/team/presets/agents/vaultspec-doc-reviewer.toml`
- `S09` `T` `src/vaultspec_a2a/graph/nodes/worker.py`
- `S10` `T` `src/vaultspec_a2a/graph/nodes/supervisor.py`
- `S11` `T` `src/vaultspec_a2a/service_tests/test_receipt_role_rules.py`
- `S12` `T` `.vault/exec/2026-07-15-graph-agent-framework-harness/2026-07-15-graph-agent-framework-harness-P05-summary.md`
- `S13` `T` `src/vaultspec_a2a/context/rules.py`
- `S14` `T` `src/vaultspec_a2a/graph/compiler.py`
- `S15` `T` `src/vaultspec_a2a/providers/_acp_mcp.py`
- `S15` `T` `src/vaultspec_a2a/providers/_acp_session.py`
- `S15` `T` `src/vaultspec_a2a/graph/compiler.py`
- `S15` `T` `feat(providers)`
- `S15` `T` `357d87a`
- `S15` `T` `[team.harness]`
- `S15` `T` `mcp_servers`
- `S15` `T` `session/new`
- `S15` `T` `src/vaultspec_a2a/providers/tests/test_acp_mcp.py`
- `S15` `T` `src/vaultspec_a2a/graph/tests/nodes/test_harness_mcp_wiring.py`
- `S15` `T` `src/vaultspec_a2a/graph/nodes/worker.py`
- `S15` `T` `_acp_session.py`
- `S15` `T` `config.mcp_servers`
- `S15` `T` `_acp_mcp.py`

