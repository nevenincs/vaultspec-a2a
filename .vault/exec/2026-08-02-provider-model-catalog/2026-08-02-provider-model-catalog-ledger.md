---
tags:
  - '#exec'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:559829f159c120015f1247512e2cac51001f713f6b452a28b542f3ca45f8a606'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---

<!-- Machine-owned: filename and frontmatter, scaffolded by
     `vaultspec-core vault exec log`; never hand-edit. Add no
     frontmatter fields. Wiki-links belong in `related:` only, never in the body.

     ONE ledger per plan, replacing one document per Step. The Step identity
     the plan's ids provide moves from the filename into the row's first
     column, so a Step still maps to a real artifact. -->

# `provider-model-catalog` ledger

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
- `S01` `T` `src/vaultspec_a2a/providers/provider_catalog.py`
- `S01` `T` `src/vaultspec_a2a/providers/tests/test_provider_catalog.py`
- `S02` `T` `src/vaultspec_a2a/providers/acp_catalog.py`
- `S02` `T` `src/vaultspec_a2a/providers/tests/test_acp_catalog.py`
- `S02` `T` `src/vaultspec_a2a/providers/tests/test_acp_catalog_live.py`
- `S02` `T` `src/vaultspec_a2a/providers/tests/conftest.py`
- `S03` `T` `src/vaultspec_a2a/providers/provider_catalog.py`
- `S03` `T` `src/vaultspec_a2a/providers/acp_catalog.py`
- `S03` `T` `src/vaultspec_a2a/providers/codex_catalog.py`
- `S03` `T` `src/vaultspec_a2a/providers/tests/test_provider_catalog.py`
- `S03` `T` `src/vaultspec_a2a/providers/tests/test_acp_catalog.py`
- `S03` `T` `src/vaultspec_a2a/providers/tests/test_codex_catalog.py`
- `S04` `T` `src/vaultspec_a2a/providers/kimi_catalog.py`
- `S04` `T` `src/vaultspec_a2a/providers/tests/test_kimi_catalog.py`
- `S05` `T` `src/vaultspec_a2a/providers/openai_catalog.py`
- `S05` `T` `src/vaultspec_a2a/providers/tests/test_openai_catalog.py`
- `S05` `T` `.vault/reference/2026-08-02-provider-model-catalog-reference.md`
- `S06` `T` `src/vaultspec_a2a/providers/factory.py`
- `S06` `T` `src/vaultspec_a2a/control/config.py`
- `S06` `T` `src/vaultspec_a2a/providers/model_profiles.py`
- `S06` `T` `src/vaultspec_a2a/workspace/environment.py`
- `S07` `T` `src/vaultspec_a2a/api/routes/gateway.py`
- `S07` `T` `src/vaultspec_a2a/api/schemas/provider_catalog.py`
- `S07` `T` `src/vaultspec_a2a/providers/provider_catalog_service.py`
- `S09` `T` `src/vaultspec_a2a/providers/model_profiles.py`
- `S09` `T` `src/vaultspec_a2a/graph/compiler.py`
- `S10` `T` `src/vaultspec_a2a/team/presets/`
- `S10` `T` `src/vaultspec_a2a/graph/enums.py`
- `S10` `T` `src/vaultspec_a2a/graph/compiler.py`
- `S10` `T` `src/vaultspec_a2a/providers/factory.py`
- `S10` `T` `src/vaultspec_a2a/providers/model_profiles.py`
- `S10` `T` `src/vaultspec_a2a/api/`
- `S12` `T` `Y:/code/vaultspec-dashboard-worktrees/main/engine/crates/vaultspec-api/src/routes/ops/a2a.rs`
- `S13` `T` `Y:/code/vaultspec-dashboard-worktrees/main/frontend/src/stores/server/agent/`
- `S13` `T` `frontend/src/app/agent/ComposerModelPicker.tsx`
- `S13` `T` `frontend/src/app/agent/Composer.tsx`
- `S13` `T` `frontend/dev/visual-review/specimens/agent.tsx`
- `S15` `T` `frontend/src/app/agent/Composer.tsx`
- `S15` `T` `frontend/src/app/agent/ComposerExpertSelection.tsx`
- `S15` `T` `frontend/src/app/agent/ComposerModelPicker.tsx`
- `S15` `T` `frontend/src/app/kit/DropdownButton.tsx`
- `S15` `T` `frontend/src/app/kit/Popover.tsx`
- `S15` `T` `frontend/src/stores/server/agent/a2aProviderCatalog.ts`
- `S15` `T` `frontend/src/stores/server/agent/a2aTeam.ts`
- `S16` `T` `Y:/code/vaultspec-dashboard-worktrees/main/frontend/src/app/agent/`
- `S17` `T` `frontend/src/stores/server/agent/a2aTeam.ts`
- `S17` `T` `frontend/src/app/agent/TeamRunHeader.tsx`

