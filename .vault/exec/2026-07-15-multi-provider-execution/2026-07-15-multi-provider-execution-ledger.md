---
tags:
  - '#exec'
  - '#multi-provider-execution'
date: '2026-07-15'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:cfcc98ae0fbdb232fceec74a15913f5406308a93df10c7d97a09bfa89d5c4bf4'
related:
  - "[[2026-07-15-multi-provider-execution-plan]]"
---

<!-- Machine-owned: filename and frontmatter, scaffolded by
     `vaultspec-core vault exec log`; never hand-edit. Add no
     frontmatter fields. Wiki-links belong in `related:` only, never in the body.

     ONE ledger per plan, replacing one document per Step. The Step identity
     the plan's ids provide moves from the filename into the row's first
     column, so a Step still maps to a real artifact. -->

# `multi-provider-execution` ledger

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
- `S01` `T` `src/vaultspec_a2a/graph/enums.py`
- `S02` `T` `src/vaultspec_a2a/control/config.py`
- `S03` `T` `src/vaultspec_a2a/providers/factory.py`
- `S04` `T` `add a regression test pinning that`
- `S04` `T` `src/vaultspec_a2a/workspace/environment.py`
- `S04` `T` `src/vaultspec_a2a/workspace/tests/`
- `S05` `T` `src/vaultspec_a2a/providers/model_profiles.py`
- `S05` `T` `src/vaultspec_a2a/providers/factory.py`
- `S06` `T` `this closes the ADR's flagged Z.ai-fidelity unknown`
- `S06` `T` `src/vaultspec_a2a/providers/tests/`
- `S06` `T` `src/vaultspec_a2a/service_tests/`
- `S07` `T` `src/vaultspec_a2a/providers/tests/test_factory.py`
- `S07` `T` `src/vaultspec_a2a/providers/tests/test_model_profiles.py`
- `S08` `T` `this closes the ADR's flagged Codex auth-model unknown before any settings field is designed`
- `S08` `T` `src/vaultspec_a2a/control/config.py`
- `S09` `T` `src/vaultspec_a2a/graph/enums.py`
- `S10` `T` `src/vaultspec_a2a/providers/codex_chat_model.py`
- `S11` `T` `src/vaultspec_a2a/providers/_subprocess.py`
- `S11` `T` `src/vaultspec_a2a/providers/codex_chat_model.py`
- `S12` `T` `src/vaultspec_a2a/providers/factory.py`
- `S12` `T` `src/vaultspec_a2a/providers/model_profiles.py`
- `S13` `T` `src/vaultspec_a2a/providers/factory.py`
- `S14` `T` `src/vaultspec_a2a/providers/tests/test_codex_chat_model.py`
- `S14` `T` `src/vaultspec_a2a/service_tests/`
- `S15` `T` `src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research.toml`
- `S16` `T` `src/vaultspec_a2a/service_tests/`
- `S17` `T` `src/vaultspec_a2a/api/tests/`
- `S18` `T` `cross-repo (dashboard/engine, no A2A code change assumed)`
- `S19` `T` `.vault/exec/2026-07-15-multi-provider-execution/`

