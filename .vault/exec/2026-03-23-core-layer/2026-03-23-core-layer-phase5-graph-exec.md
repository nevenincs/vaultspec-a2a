---
tags:
  - '#exec'
  - '#core-layer'
date: '2026-03-23'
modified: '2026-07-15'
related:
  - '[[2026-03-23-core-layer-boundary-plan]]'
---

# core-layer phase-5 graph extraction

## summary

Extracted `graph/` module from `core/` per ADR D-01, D-02, D-04.  The graph
layer now owns compilation, nodes, tools, domain events, domain enums, and
dependency-injection protocols.  All three boundary violations identified in
the ADR (`Checkpointer`, `ProviderFactory`, `AcpSessionError`) are removed
from the new module.

## changes

- **`graph/enums.py`** -- Canonical definitions of `ToolKind`,
  `PermissionType`, `PermissionOptionKind`, `ToolCallStatus`,
  `AgentLifecycleState`.  `api/schemas/enums.py` re-exports from here.

- **`graph/events.py`** -- Plain `@dataclass` domain events (D-01):
  `DomainEvent`, `MessageChunk`, `ThoughtChunk`, `ToolCallStart`,
  `ToolCallUpdate`, `PermissionRequest`, `PlanUpdate`, `ArtifactUpdate`,
  `AgentStatus`, `TeamStatus`, `ErrorOccurred`.

- **`graph/protocols.py`** -- Dependency-injection protocols (D-02, D-04):
  `ProviderFactoryProtocol`, `TelemetryHook`, `NullTelemetryHook`.

- **`graph/compiler.py`** -- From `core/graph.py`.  `Checkpointer` replaced
  with `BaseCheckpointSaver` (framework type).  `ProviderFactory` replaced
  with `ProviderFactoryProtocol` parameter (lazy fallback during transition).
  `AcpSessionError` replaced with `ProviderSessionError` from
  `thread.errors`.

- **`graph/nodes/`** -- `supervisor.py`, `worker.py`, `vault_reader.py`
  (renamed from `mount.py`).  All imports updated to use absolute paths
  through `context/`, `control/`, `thread/`.

- **`graph/tools/task_queue.py`** -- From `core/task_queue.py`.

- **`graph/tests/`** -- Full test mirror: `test_compiler.py`,
  `test_graph_execution.py`, `test_e2e_live.py`, `test_task_queue.py`,
  `nodes/test_supervisor.py`, `nodes/test_worker.py`,
  `nodes/test_vault_reader.py`, `nodes/test_worker_integration.py`.

- **Shims** -- `core/graph.py`, `core/nodes/__init__.py`,
  `core/nodes/supervisor.py`, `core/nodes/worker.py`,
  `core/nodes/mount.py`, `core/task_queue.py` all replaced with
  re-export shims.

- **`core/__init__.py`** -- Graph symbols moved from `_LAZY_IMPORTS` to
  `_REDIRECTS`: `build_initial_vault_index`, `compile_team_graph`,
  `create_supervisor_node`, `create_worker_node`,
  `create_mark_task_complete_tool`.

## verification

- `ruff check` -- 0 errors on `graph/` + `core/`
- `ruff format --check` -- 0 reformats needed
- graph/tests (non-ACP): 38 passed
- graph/tests/test_compiler.py (non-ACP subset): 11 passed
- core/tests (excluding graph compilation): 315 passed
- core/nodes/tests (via shims): 25 passed
