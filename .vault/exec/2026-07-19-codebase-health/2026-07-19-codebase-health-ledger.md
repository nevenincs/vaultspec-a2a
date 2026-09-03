---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-19'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:523302ffb9e5dfdcc179c42c55c9fb03675a65773f43271785b723c3121e9518'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

<!-- Machine-owned: filename and frontmatter, scaffolded by
     `vaultspec-core vault exec log`; never hand-edit. Add no
     frontmatter fields. Wiki-links belong in `related:` only, never in the body.

     ONE ledger per plan, replacing one document per Step. The Step identity
     the plan's ids provide moves from the filename into the row's first
     column, so a Step still maps to a real artifact. -->

# `codebase-health` ledger

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
- `S01` `T` `.vault/adr`
- `S01` `T` `.vault/index`
- `S02` `T` `.vault/exec`
- `S02` `T` `.vault/audit`
- `S02` `T` `src/vaultspec_a2a/desktop_tests`
- `S03` `T` `.vault/exec`
- `S03` `T` `.vault/audit`
- `S03` `T` `just/dev/service.just`
- `S06` `T` `.vault/exec`
- `S06` `T` `.vault/audit`
- `S06` `T` `src/vaultspec_a2a/desktop_tests/test_owned_process_tree.py`
- `S08` `T` `src/vaultspec_a2a/database`
- `S08` `T` `src/vaultspec_a2a/control/repositories`
- `S09` `T` `src/vaultspec_a2a/control/repositories`
- `S10` `T` `src/vaultspec_a2a/control/thread_service.py`
- `S10` `T` `src/vaultspec_a2a/control/cleanup`
- `S11` `T` `src/vaultspec_a2a/control/thread_service.py`
- `S11` `T` `src/vaultspec_a2a/control/thread_state_service.py`
- `S12` `T` `src/vaultspec_a2a/control/cleanup`
- `S12` `T` `src/vaultspec_a2a/checkpointer`
- `S13` `T` `src/vaultspec_a2a/api/routes/threads.py`
- `S13` `T` `src/vaultspec_a2a/control/thread_service.py`
- `S14` `T` `tests/control`
- `S14` `T` `tests/api`
- `S15` `T` `.vault/audit`
- `S15` `T` `.vault/exec`
- `S16` `T` `.vault/audit/2026-07-19-codebase-health-audit.md`
- `S16` `T` `.vault/exec`
- `S17` `T` `src/vaultspec_a2a/api/schemas/gateway.py, src/vaultspec_a2a/control/run_start_policy.py`
- `S18` `T` `src/vaultspec_a2a/api/routes/gateway.py, src/vaultspec_a2a/control/repositories`
- `S19` `T` `src/vaultspec_a2a/providers/model_profiles.py, src/vaultspec_a2a/api/routes/gateway.py, src/vaultspec_a2a/authoring/discovery.py`
- `S20` `T` `src/vaultspec_a2a/control/thread_state_service.py`
- `S23` `T` `src/vaultspec_a2a/streaming/aggregator.py`
- `S23` `T` `src/vaultspec_a2a/streaming/transformer.py`
- `S24` `T` `src/vaultspec_a2a/api/routes/gateway.py, src/vaultspec_a2a/api/dependencies.py`
- `S26` `T` `src/vaultspec_a2a/authoring/discovery.py`
- `S27` `T` `tests/streaming`
- `S27` `T` `tests/api`
- `S33` `T` `.vault/audit`
- `S33` `T` `.vault/exec`
- `S34` `T` `.vault/audit/2026-07-19-codebase-health-audit.md`
- `S35` `T` `src/vaultspec_a2a/providers/_acp_mcp.py, src/vaultspec_a2a/mcp`
- `S36` `T` `src/vaultspec_a2a/providers/_acp_mcp.py, src/vaultspec_a2a/providers/_acp_project_mcp.py`
- `S37` `T` `tests/providers, tests/mcp`
- `S38` `T` `src/vaultspec_a2a/providers/codex_chat_model.py, src/vaultspec_a2a/providers/_subprocess.py`
- `S39` `T` `src/vaultspec_a2a/providers/_acp_protocol.py, src/vaultspec_a2a/providers/acp_chat_model.py`
- `S40` `T` `src/vaultspec_a2a/providers/acp_chat_model.py, src/vaultspec_a2a/providers/codex_chat_model.py`
- `S46` `T` `.vault/exec, .vault/audit, tests, pyproject.toml`
- `S48` `T` `tests/mcp, tests/api`
- `S49` `T` `src/vaultspec_a2a/thread/repair_policy.py, src/vaultspec_a2a/control/repair_transitions.py, tests`
- `S50` `T` `src/vaultspec_a2a/control/thread_service.py, src/vaultspec_a2a/control/repositories`
- `S51` `T` `tests/control, tests/api`
- `S55` `T` `src/vaultspec_a2a/api/routes`
- `S56` `T` `.vault/audit/2026-07-19-codebase-health-audit.md, src/vaultspec_a2a/graph, src/vaultspec_a2a/providers`
- `S57` `T` `src/vaultspec_a2a/workspace/git_manager.py, src/vaultspec_a2a/thread/errors.py, src/vaultspec_a2a/thread/__init__.py, ../../vaultspec-dashboard-worktrees/main, .vault/audit`
- `S58` `T` `src/vaultspec_a2a/graph/enums.py, tests`
- `S59` `T` `src/vaultspec_a2a/providers/acp_exceptions.py, tests`
- `S60` `T` `src/vaultspec_a2a/team/team_config.py, tests`
- `S61` `T` `src/vaultspec_a2a/providers/model_profiles.py, tests`
- `S62` `T` `src/vaultspec_a2a/providers/_acp_project_mcp.py, tests`
- `S64` `T` `src/vaultspec_a2a/utils/trace.py, tests`
- `S65` `T` `src/vaultspec_a2a/streaming/aggregator.py, tests/streaming`
- `S66` `T` `src/vaultspec_a2a/providers/factory.py, tests/providers`
- `S69` `T` `src/vaultspec_a2a/streaming/transformer.py, tests/streaming`
- `S71` `T` `src/vaultspec_a2a/control/thread_state_service.py, tests/control`
- `S73` `T` `service/README.md, service/docker/README.md, service/.env.example`
- `S75` `T` `.vault/audit`
- `S75` `T` `.vault/exec`
- `S76` `T` `.vault/audit/2026-07-19-codebase-health-audit.md`
- `S76` `T` `.vault/exec`
- `S77` `T` `src/vaultspec_a2a/acceptance`
- `S77` `T` `tests/acceptance`
- `S78` `T` `tests/acceptance/test_dashboard_contract.py`
- `S79` `T` `tests/acceptance/test_dashboard_stream.py`
- `S80` `T` `tests/acceptance/test_dashboard_deletion.py`
- `S82` `T` `src/vaultspec_a2a/service_tests/test_compose_profile_regression.py`
- `S87` `T` `Justfile`
- `S87` `T` `just/dev/code.just`
- `S87` `T` `src`
- `S87` `T` `tests`
- `S93` `T` `src/vaultspec_a2a/api/schemas/gateway.py, src/vaultspec_a2a/control/worker_management.py, src/vaultspec_a2a/api/internal.py, src/vaultspec_a2a/worker/app.py`
- `S94` `T` `src/vaultspec_a2a/control/worker_management.py, src/vaultspec_a2a/control/health.py`
- `S95` `T` `src/vaultspec_a2a/desktop_tests/test_worker_provenance.py`
- `S98` `T` `src/vaultspec_a2a/streaming/sse_frames.py`
- `S98` `T` `src/vaultspec_a2a/api/event_adapter.py`
- `S99` `T` `tests/streaming`
- `S99` `T` `tests/api`
- `S108` `T` `src/vaultspec_a2a/control/repositories`
- `S109` `T` `src/vaultspec_a2a/control/repositories`
- `S110` `T` `src/vaultspec_a2a/control/repositories`
- `S127` `T` `src/vaultspec_a2a/control/message_service.py`
- `S128` `T` `src/vaultspec_a2a/control/thread_service.py`
- `S129` `T` `src/vaultspec_a2a/control/permission_service.py`
- `S130` `T` `src/vaultspec_a2a/streaming/subscribers.py`
- `S131` `T` `src/vaultspec_a2a/api/websocket.py`
- `S132` `T` `src/vaultspec_a2a/authoring/lifecycle.py`
- `S133` `T` `src/vaultspec_a2a/lifecycle/discovery.py`
- `S134` `T` `src/vaultspec_a2a/graph/enums.py, ../../vaultspec-dashboard-worktrees/main, .vault/audit`
- `S135` `T` `src/vaultspec_a2a/providers/acp_exceptions.py, ../../vaultspec-dashboard-worktrees/main, .vault/audit`
- `S136` `T` `src/vaultspec_a2a/team/team_config.py, ../../vaultspec-dashboard-worktrees/main, .vault/audit`
- `S137` `T` `src/vaultspec_a2a/providers/model_profiles.py, ../../vaultspec-dashboard-worktrees/main, .vault/audit`
- `S138` `T` `src/vaultspec_a2a/providers/_acp_project_mcp.py, ../../vaultspec-dashboard-worktrees/main, .vault/audit`
- `S141` `T` `Justfile`
- `S141` `T` `just/dev/deps.just`
- `S141` `T` `pyproject.toml`
- `S141` `T` `uv.lock`
- `S142` `T` `Justfile`
- `S142` `T` `just/dev/test.just`
- `S142` `T` `src`
- `S142` `T` `tests`
- `S144` `T` `tests/acceptance`
- `S144` `T` `src/vaultspec_a2a/desktop_tests`
- `S144` `T` `src/vaultspec_a2a/service_tests`
- `S153` `T` `src/vaultspec_a2a/desktop_tests/test_worker_provenance.py`
- `S154` `T` `src/vaultspec_a2a/desktop_tests/test_worker_provenance.py`
- `S155` `T` `src/vaultspec_a2a/desktop_tests/test_worker_provenance.py`
- `S156` `T` `src/vaultspec_a2a/desktop_tests/test_worker_provenance.py`
- `S157` `T` `src/vaultspec_a2a/service_tests/test_compose_profile_regression.py`
- `S159` `T` `tests/streaming`
- `S159` `T` `tests/api`
- `S170` `T` `tests/acceptance/test_dashboard_contract.py`
- `S171` `T` `tests/acceptance/test_dashboard_contract.py`
- `S172` `T` `tests/acceptance/test_dashboard_contract.py`
- `S173` `T` `tests/acceptance/test_dashboard_contract.py`
- `S175` `T` `src/vaultspec_a2a/utils/timestamp.py, src/vaultspec_a2a/utils/__init__.py, src/vaultspec_a2a/utils/tests/test_timestamp.py`
- `S176` `T` `src/vaultspec_a2a/utils/timestamp.py, src/vaultspec_a2a/utils/__init__.py, ../../vaultspec-dashboard-worktrees/main, .vault/audit`
- `S177` `T` `src/vaultspec_a2a/api/run_admission.py`
- `S177` `T` `src/vaultspec_a2a/api/routes/gateway.py`
- `S178` `T` `src/vaultspec_a2a/control/event_handlers.py`
- `S178` `T` `src/vaultspec_a2a/control/drain.py`
- `S178` `T` `src/vaultspec_a2a/api/app.py`
- `S179` `T` `src/vaultspec_a2a/api/routes/thread_stream.py`
- `S180` `T` `src/vaultspec_a2a/streaming/sse_frames.py`
- `S180` `T` `src/vaultspec_a2a/api/schemas/events.py`
- `S181` `T` `src/vaultspec_a2a/api/routes/threads.py`
- `S181` `T` `src/vaultspec_a2a/control/thread_service.py`
- `S183` `T` `src/vaultspec_a2a/api/routes/gateway.py`
- `S183` `T` `src/vaultspec_a2a/api/schemas/gateway.py`

