---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:ab932934de3c444e37b0f8757b64729f2c35cb52217940d72544219a9c2edb7b'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---

<!-- Machine-owned: filename and frontmatter, scaffolded by
     `vaultspec-core vault exec log`; never hand-edit. Add no
     frontmatter fields. Wiki-links belong in `related:` only, never in the body.

     ONE ledger per plan, replacing one document per Step. The Step identity
     the plan's ids provide moves from the filename into the row's first
     column, so a Step still maps to a real artifact. -->

# `repository-tooling-hardening` ledger

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
- `S01` `T` `pyproject.toml`
- `S01` `T` `uv.lock`
- `S02` `T` `just/dev/deps.just`
- `S02` `T` `just/dev/vault.just`
- `S02` `T` `just/dev/rag.just`
- `S03` `T` `src/vaultspec_a2a/cli/provision.py`
- `S03` `T` `src/vaultspec_a2a/providers/_acp_mcp.py`
- `S03` `T` `tests`
- `S04` `T` `.gitignore`
- `S05` `T` `.vaultspec/rules`
- `S05` `T` `generated provider projections`
- `S06` `T` `Justfile`
- `S06` `T` `just/dev`
- `S07` `T` `just/dev/service.just`
- `S07` `T` `just/dev/stack.just`
- `S08` `T` `.pre-commit-config.yaml`
- `S08` `T` `hook integration tests`
- `S09` `T` `pyproject.toml`
- `S09` `T` `affected source and tests`
- `S10` `T` `.github/workflows`
- `S10` `T` `repository health configuration`
- `S11` `T` `README.md`
- `S11` `T` `docs`
- `S12` `T` `.vault/audit`
- `S12` `T` `.vault/exec`
- `S13` `T` `dev/toolchain.py`
- `S14` `T` `dev/toolchain.py`
- `S14` `T` `pyproject.toml`
- `S15` `T` `dev/toolchain.py`
- `S15` `T` `justfile`
- `S16` `T` `.github/workflows/test.yml`
- `S17` `T` `.github/workflows/test.yml`
- `S18` `T` `dev/toolchain.py`
- `S18` `T` `dev/tests/test_ci_contract.py`
- `S19` `T` `src/vaultspec_a2a/control/tests/test_spawn_containment_ownership.py`
- `S19` `T` `src/vaultspec_a2a/streaming/tests/test_sse_frames.py`
- `S19` `T` `src/vaultspec_a2a/utils/process.py`
- `S20` `T` `dev/health/report.py`
- `S21` `T` `src/vaultspec_a2a/api/tests/conftest.py`
- `S22` `T` `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `S23` `T` `src/vaultspec_a2a/api/tests/test_gateway_live.py`
- `S23` `T` `src/vaultspec_a2a/api/tests/test_clarification_loop_live.py`
- `S23` `T` `src/vaultspec_a2a/api/tests/test_clarification_endpoint.py`
- `S23` `T` `src/vaultspec_a2a/api/tests/test_acceptance_five_verb.py`
- `S23` `T` `src/vaultspec_a2a/api/tests/clarification_harness.py`
- `S23` `T` `src/vaultspec_a2a/control/tests/test_verdict_loop_live.py`
- `S23` `T` `src/vaultspec_a2a/worker/executor.py`
- `S23` `T` `src/vaultspec_a2a/worker/graph_lifecycle.py`
- `S23` `T` `src/vaultspec_a2a/worker/tests/test_executor.py`
- `S23` `T` `src/vaultspec_a2a/worker/tests/test_executor_token_lifecycle.py`
- `S24` `T` `src/vaultspec_a2a/control`
- `S24` `T` `src/vaultspec_a2a/control/repositories`
- `S24` `T` `src/vaultspec_a2a/authoring/discovery.py`
- `S24` `T` `src/vaultspec_a2a/api/routes/gateway.py`
- `S24` `T` `src/vaultspec_a2a/desktop_tests/test_worker_health_decode_contract.py`
- `S25` `T` `src/vaultspec_a2a/providers`
- `S25` `T` `src/vaultspec_a2a/desktop/profile.py`
- `S25` `T` `src/vaultspec_a2a/desktop/tests/test_profile.py`
- `S25` `T` `src/vaultspec_a2a/desktop_tests/test_profile_paths.py`
- `S25` `T` `src/vaultspec_a2a/cli/tests/test_desktop_serve.py`
- `S25` `T` `src/vaultspec_a2a/desktop_tests/test_owned_process_tree.py`

