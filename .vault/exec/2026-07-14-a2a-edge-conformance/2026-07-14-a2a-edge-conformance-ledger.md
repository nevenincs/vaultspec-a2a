---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:8f6e6d9b74e063f94b382e65d7f6d6f8f992cc56a09013c6aee743236177137b'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

<!-- Machine-owned: filename and frontmatter, scaffolded by
     `vaultspec-core vault exec log`; never hand-edit. Add no
     frontmatter fields. Wiki-links belong in `related:` only, never in the body.

     ONE ledger per plan, replacing one document per Step. The Step identity
     the plan's ids provide moves from the filename into the row's first
     column, so a Step still maps to a real artifact. -->

# `a2a-edge-conformance` ledger

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
- `S01` `T` `src/vaultspec_a2a/control/worker_management.py`
- `S01` `T` `src/vaultspec_a2a/worker/app.py`
- `S01` `T` `src/vaultspec_a2a/api/app.py`
- `S02` `T` `src/vaultspec_a2a/team/presets/`
- `S02` `T` `src/vaultspec_a2a/graph/`
- `S03` `T` `pyproject.toml`
- `S03` `T` `src/vaultspec_a2a/**/tests/`
- `S04` `T` `.gitignore`
- `S04` `T` `.pre-commit-config.yaml`
- `S04` `T` `pyproject.toml`
- `S04` `T` `uv.lock`
- `S05` `T` `src/vaultspec_a2a/control/worker_management.py`
- `S05` `T` `src/vaultspec_a2a/infra/`
- `S05` `T` `.vault-local-state-moved-20260703/`
- `S06` `T` `src/vaultspec_a2a/core/`
- `S06` `T` `src/vaultspec_a2a/cli/`
- `S06` `T` `src/vaultspec_a2a/tests/`
- `S06` `T` `src/vaultspec_a2a/bin/`
- `S07` `T` `src/ui/`
- `S07` `T` `src/vaultspec_a2a/api/app.py`
- `S07` `T` `src/vaultspec_a2a/api/settings`
- `S08` `T` `package.json`
- `S08` `T` `Justfile`
- `S08` `T` `.github/workflows/`
- `S08` `T` `.pre-commit-config.yaml`
- `S09` `T` `src/vaultspec_a2a/api/`
- `S10` `T` `confirm the parent protocols __init__ needs no change`
- `S10` `T` `do NOT touch graph/protocols.py`
- `S10` `T` `an unrelated typing.Protocol module whose name collides. Authorized rider on W02's first hygiene commit (W01 review ruling): remove the source-deleted providers/probes/ husk (pycache and empty tests cache only)`
- `S10` `T` `src/vaultspec_a2a/protocols/a2a/`
- `S10` `T` `src/vaultspec_a2a/protocols/adapter/`
- `S10` `T` `src/vaultspec_a2a/providers/probes/`
- `S11` `T` `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`
- `S12` `T` `src/vaultspec_a2a/providers/tests/`
- `S13` `T` `src/vaultspec_a2a/graph/tools/task_queue.py`
- `S13` `T` `src/vaultspec_a2a/database/`
- `S13` `T` `src/vaultspec_a2a/graph/nodes/worker.py`
- `S14` `T` `src/vaultspec_a2a/graph/tests/`
- `S14` `T` `src/vaultspec_a2a/service_tests/`
- `S15` `T` `src/vaultspec_a2a/authoring/`
- `S16` `T` `src/vaultspec_a2a/authoring/`
- `S16` `T` `src/vaultspec_a2a/thread/`
- `S17` `T` `src/vaultspec_a2a/authoring/tests/`
- `S18` `T` `src/vaultspec_a2a/authoring/`
- `S18` `T` `src/vaultspec_a2a/protocols/mcp/tools/`
- `S19` `T` `src/vaultspec_a2a/providers/`
- `S19` `T` `src/vaultspec_a2a/graph/nodes/worker.py`
- `S20` `T` `src/vaultspec_a2a/team/presets/teams/`
- `S20` `T` `src/vaultspec_a2a/service_tests/`
- `S21` `T` `src/vaultspec_a2a/service_tests/`
- `S22` `T` `src/vaultspec_a2a/api/`
- `S22` `T` `src/vaultspec_a2a/control/`
- `S22` `T` `src/vaultspec_a2a/worker/`
- `S23` `T` `src/vaultspec_a2a/worker/tests/`
- `S23` `T` `src/vaultspec_a2a/control/tests/`
- `S24` `T` `src/vaultspec_a2a/api/`
- `S25` `T` `src/vaultspec_a2a/streaming/`
- `S25` `T` `src/vaultspec_a2a/api/tests/`
- `S26` `T` `src/vaultspec_a2a/cli/`
- `S26` `T` `pyproject.toml`
- `S27` `T` `src/vaultspec_a2a/lifecycle/`
- `S27` `T` `src/vaultspec_a2a/api/`
- `S28` `T` `src/vaultspec_a2a/lifecycle/tests/`
- `S29` `T` `.vault/adr/`
- `S30` `T` `README.md`
- `S30` `T` `docs/`
- `S31` `T` `src/vaultspec_a2a/service_tests/`
- `S31` `T` `src/vaultspec_a2a/team/`
- `S32` `T` `.vault/exec/`
- `S33` `T` `src/vaultspec_a2a/providers/_acp_session.py`
- `S33` `T` `src/vaultspec_a2a/providers/_subprocess.py`
- `S33` `T` `src/vaultspec_a2a/providers/acp_chat_model.py`
- `S33` `T` `src/vaultspec_a2a/providers/factory.py`
- `S34` `T` `this step blocks W02`
- `S34` `T` `this step blocks W02 and must not proceed before the decision lands`
- `S34` `T` `src/vaultspec_a2a/graph/tools/task_queue.py`
- `S34` `T` `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`
- `S34` `T` `src/vaultspec_a2a/streaming/`
- `S34` `T` `src/vaultspec_a2a/control/thread_service.py`
- `S35` `T` `conftest.py`
- `S35` `T` `src/vaultspec_a2a/**/tests/`
- `S36` `T` `NO remote deletions (origin/claude/* stay)`
- `S36` `T` `and feature/ci-resolve-vaultspec-core-dep-23 stays untouched pending W02.P03`
- `S36` `T` `defer feature/ci-resolve-vaultspec-core-dep-23 until W02.P03 lands`
- `S36` `T` `git worktrees`
- `S36` `T` `git stashes`
- `S36` `T` `git branches`
- `S37` `T` `src/vaultspec_a2a/control/worker_management.py`
- `S37` `T` `src/vaultspec_a2a/lifecycle/`
- `S37` `T` `src/vaultspec_a2a/streaming/`
- `S37` `T` `src/vaultspec_a2a/graph/nodes/worker.py`
- `S38` `T` `src/vaultspec_a2a/lifecycle/`
- `S38` `T` `src/vaultspec_a2a/cli/`
- `S38` `T` `src/vaultspec_a2a/api/`
- `S39` `T` `src/vaultspec_a2a/service_tests/`
- `S39` `T` `.vault/exec/`
- `S40` `T` `src/vaultspec_a2a/database/reconciliation.py`
- `S40` `T` `src/vaultspec_a2a/database/tests/`
- `S41` `T` `src/vaultspec_a2a/control/worker_management.py`
- `S41` `T` `src/vaultspec_a2a/api/app.py`
- `S41` `T` `src/vaultspec_a2a/database/permission_repository.py`
- `S42` `T` `src/vaultspec_a2a/providers/_acp_project_mcp.py`
- `S42` `T` `src/vaultspec_a2a/providers/tests/`
- `S43` `T` `src/vaultspec_a2a/service_tests/`
- `S43` `T` `.vault/exec/`
- `S44` `T` `src/vaultspec_a2a/providers/_acp_project_mcp.py`
- `S44` `T` `src/vaultspec_a2a/providers/tests/test_acp_project_mcp.py`

