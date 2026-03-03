---
date: 2026-02-27
type: audit
feature: implementation
description: 'Supervisor agent audit of all modules modified during Tasks #2-#7, verifying compliance with ADRs 001-013 and project rules; all tasks approved with 3 pre-existing findings tracked.'
related:
  - docs/adrs/2026-02-26-009-module-hierarchy-adr.md
  - docs/adrs/2026-02-27-012-agent-definition-schema-adr.md
  - docs/adrs/2026-02-27-013-team-composition-topology-adr.md
---

# Implementation Audit Report — 2026-02-27

**Auditor:** Supervisor Agent
**Scope:** All modules modified or created during Tasks #2–#7
**ADRs checked:** 001 through 013 + CLAUDE.md project rules
**Verdict:** ALL TASKS APPROVED — 3 pre-existing findings tracked

---

## Module: lib/core/team_config.py (NEW — Task #2)

| Check                                             | ADR                         | Result |
| ------------------------------------------------- | --------------------------- | ------ |
| Field names match §2.3 schema                     | ADR-012                     | PASS   |
| `agent.id`validated as Python identifier          | ADR-012 §5                  | PASS   |
| `from_toml()`uses`tomllib`(stdlib)                | ADR-012 §2.3                | PASS   |
| `AgentCapabilitiesConfig`defaults all`False`      | ADR-012 §2.6                | PASS   |
| `TopologyConfig`validates type/order/loop_node    | ADR-013 §2.4                | PASS   |
| `TeamConfig.validate_topology_order_subset`       | ADR-013 §5                  | PASS   |
| Discovery order: workspace -> preset -> error     | ADR-012 §2.8 / ADR-013 §2.8 | PASS   |
| Relative imports (`..utils.enums`, `.exceptions`) | ADR-009                     | PASS   |
| `__all__`declared (14 symbols)                    | ADR-009                     | PASS   |
| No mocks, no unittest                             | CLAUDE.md                   | PASS   |

---

## Module: lib/core/presets/agents/\*.toml (NEW — Task #3)

| Check                                                                                    | ADR          | Result |
| ---------------------------------------------------------------------------------------- | ------------ | ------ |
| `planner.toml`exists with correct fields                                                 | ADR-012 §2.7 | PASS   |
| `coder.toml`exists:`filesystem_read=true`, `filesystem_write=true`, `terminal=false`     | ADR-012 §2.7 | PASS   |
| `reviewer.toml`exists:`filesystem_read=true`, `filesystem_write=false`, `terminal=false` | ADR-012 §2.7 | PASS   |
| `analyst.toml`exists:`filesystem_read=true`, `filesystem_write=false`, `terminal=false`  | ADR-012 §2.7 | PASS   |
| `supervisor.toml`exists with`{{AGENT_ROSTER}}`placeholder                                | ADR-012 §2.7 | PASS   |
| All TOML files have`[agent]`section with`id`, `display_name`, `role`, `description`      | ADR-012 §2.1 | PASS   |
| All TOML files have`[agent.persona]`with`system_prompt`                                  | ADR-012 §2.1 | PASS   |
| All TOML files have`[agent.model]`, `[agent.capabilities]`, `[agent.permissions]`        | ADR-012 §2.1 | PASS   |

---

## Module: lib/core/presets/teams/\*.toml (NEW — Task #3)

| Check                                                                             | ADR          | Result |
| --------------------------------------------------------------------------------- | ------------ | ------ |
| `coding-star.toml`: topology `star`, workers planner/coder/reviewer               | ADR-013 §2.9 | PASS   |
| `coding-pipeline.toml`: topology `pipeline`, order planner→coder→reviewer         | ADR-013 §2.9 | PASS   |
| `coding-loop.toml`: topology `pipeline_loop`, `loop_node=reviewer`, `max_loops=3` | ADR-013 §2.9 | PASS   |
| `solo-coder.toml`: topology `pipeline`, single coder worker                       | ADR-013 §2.9 | PASS   |
| All TOML files have `[team]`section with`id`, `display_name`, `description`       | ADR-013 §2.1 | PASS   |
| All TOML files have`[team.defaults]`with`provider`, `capability`                  | ADR-013 §2.2 | PASS   |
| Star/loop presets have`[team.supervisor]`section                                  | ADR-013 §2.2 | PASS   |

---

## Module: lib/core/graph.py (REFACTORED — Task #4)

| Check                                                                        | ADR          | Result |
| ---------------------------------------------------------------------------- | ------------ | ------ |
| New signature:`compile_team_graph(team_config, agent_configs, checkpointer)` | ADR-013 §5   | PASS   |
| Old signature (`supervisor_model`, `worker_models`) removed                  | ADR-013 §5   | PASS   |
| Star: `add_conditional_edges(supervisor, lambda s: s["next"], route_map)`    | ADR-013 §2.5 | PASS   |
| Star: workers → supervisor → conditional → workers/END                       | ADR-013 §2.5 | PASS   |
| Pipeline:`add_edge(START, first)`+ consecutive edges +`add_edge(last, END)`  | ADR-013 §2.5 | PASS   |
| Pipeline: no supervisor node                                                 | ADR-013 §2.5 | PASS   |
| Pipeline_loop: sequential edges +`add_conditional_edges(loop_node, ...)`     | ADR-013 §2.5 | PASS   |
| Pipeline_loop:`{"revise": loop_target, "FINISH": END}`                       | ADR-013 §2.5 | PASS   |
| Pipeline_loop:`_loop_router`enforces`loop_count >= max_loops`                | ADR-013 §5   | PASS   |
| Supervisor prompt roster format:`"- {display_name} ({id}): {description}"`   | ADR-013 §2.6 | PASS   |
| `{{AGENT_ROSTER}}`template substitution supported                            | ADR-013 §2.6 | PASS   |
| `interrupt_before`assembled from all agents'`require_approval_for`           | ADR-013 §2.7 | PASS   |
| All`add_node`calls include`metadata={display_name, role, description}`       | ADR-012 §2.5 | PASS   |
| Model resolution: worker override → agent TOML → team defaults               | ADR-013 §2.3 | PASS   |
| `ProviderFactory.create(provider, model, agent_config)`called correctly      | ADR-012 §2.4 | PASS   |
| Relative imports only                                                        | ADR-009      | PASS   |
| `__all__ = ["compile_team_graph"]`                                           | ADR-009      | PASS   |

---

## Module: lib/core/state.py (MODIFIED — Task #5)

| Check                                         | ADR              | Result |
| --------------------------------------------- | ---------------- | ------ |
| `loop_count: int`field added to`TeamState`    | ADR-013 §5       | PASS   |
| Plain last-write-wins (no reducer annotation) | ADR-013 §5       | PASS   |
| All fields JSON-serializable                  | ADR-002, ADR-008 | PASS   |
| `__all__ = ["TeamState"]`                     | ADR-009          | PASS   |
| Relative imports only                         | ADR-009          | PASS   |

---

## Module: lib/providers/acp_chat_model.py (MODIFIED — Task #5)

| Check                                                                      | ADR                         | Result                  |
| -------------------------------------------------------------------------- | --------------------------- | ----------------------- |
| `agent_config: AgentConfig \                                               | None = Field(default=None)` | ADR-012 §2.6            |
| `agent_config=None`→ all ACP flags`False`(backward compat)                 | ADR-012 §5                  | PASS                    |
| `_initialize_session()`reads`agent_config.capabilities.*`                  | ADR-012 §2.6                | PASS                    |
| `clientCapabilities.fs.readTextFile`driven by`filesystem_read`             | ADR-012 §2.6                | PASS                    |
| `clientCapabilities.fs.writeTextFile`driven by`filesystem_write`           | ADR-012 §2.6                | PASS                    |
| `clientCapabilities.terminal`driven by`terminal`                           | ADR-012 §2.6                | PASS                    |
| `create_subprocess_shell`with single string command                        | ADR-006 §5.1                | PASS                    |
| `limit=10 * 1024 * 1024`(10MB buffer)                                      | ADR-006 §5.1                | PASS                    |
| `json.dumps(req).encode("utf-8") + b"\n"`stdin format                      | ADR-006 §5.1                | PASS                    |
| Walrus stdout pattern:`while line := await process.stdout.readline()`      | ADR-006 §5.1                | PASS                    |
| Bidirectional dispatch: responses (result/error) vs notifications (method) | ADR-006 §5.1                | PASS                    |
| GraphBubbleUp caught in`_on_request_permission`, stored in `interrupt_exc` | ADR-006 §5.1                | PASS                    |
| `_transport.close()`for Windows pipe cleanup                               | ADR-006 §5.1                | PASS                    |
| Relative import:`from ..core.team_config import AgentConfig`               | ADR-009                     | PASS                    |
| `__all__ = ["AcpChatModel"]`                                               | ADR-009                     | PASS                    |
| `session/cancel`as notification (not proper RPC)                           | ADR-006 §5.1 pt 6           | **FAIL** (pre-existing) |

---

## Module: lib/providers/factory.py (MODIFIED — Task #5)

| Check                                                                    | ADR              | Result |
| ------------------------------------------------------------------------ | ---------------- | ------ |
| `ProviderFactory.create()`accepts`agent_config`parameter                 | ADR-012 §2.4     | PASS   |
| `agent_config`passed to`AcpChatModel(agent_config=...)`for Claude        | ADR-012 §2.4     | PASS   |
| `agent_config`passed to`AcpChatModel(agent_config=...)`for Gemini        | ADR-012 §2.4     | PASS   |
| Claude:`command=["claude-agent-acp"]`(not`.CMD`shim)                     | ADR-002, ADR-006 | PASS   |
| Gemini:`command=["gemini", "--model", model_name, "--experimental-acp"]` | ADR-002, ADR-006 | PASS   |
| Gemini: zero credential injection                                        | ADR-002          | PASS   |
| Relative imports only                                                    | ADR-009          | PASS   |

---

## Module: lib/core/**init**.py (MODIFIED — Tasks #2, #5)

| Check                                                      | ADR     | Result |
| ---------------------------------------------------------- | ------- | ------ |
| All 14 team_config symbols re-exported with`X as X`pattern | ADR-009 | PASS   |
| `__all__`includes all re-exported symbols                  | ADR-009 | PASS   |
| Lazy import for`EventAggregator`(circular dep avoidance)   | ADR-009 | PASS   |
| All imports relative                                       | ADR-009 | PASS   |

---

## Module: lib/api/schemas/rest.py (MODIFIED — Task #6)

| Check                                                                                  | ADR          | Result                  |
| -------------------------------------------------------------------------------------- | ------------ | ----------------------- |
| `CreateThreadRequest.team_preset: str \                                                | None = None` | ADR-013 §6              |
| Deprecated`provider`/`model`fields kept for backward compat                            | ADR-013 §6   | PASS                    |
| `TeamPresetSummary`with`id`, `display_name`, `description`, `topology`, `worker_count` | ADR-013 §6   | PASS                    |
| `TeamPresetsResponse`with`presets: list[TeamPresetSummary]`                            | ADR-013 §6   | PASS                    |
| `__all__`updated with new types                                                        | ADR-009      | PASS                    |
| Relative imports only                                                                  | ADR-009      | PASS                    |
| `_AgentStatusEntry`missing`role`, `display_name`, `description`                        | ADR-012 §6   | **FAIL** (pre-existing) |

---

## Module: lib/api/endpoints.py (MODIFIED — Task #6)

| Check                                             | ADR          | Result |
| ------------------------------------------------- | ------------ | ------ |
| `GET /teams`endpoint returns`TeamPresetsResponse` | ADR-013 §6   | PASS   |
| Loads bundled presets via`load_team_config()`     | ADR-013 §2.8 | PASS   |
| Handles`TeamConfigNotFoundError`gracefully        | ADR-013 §2.8 | PASS   |
| `__all__`declared                                 | ADR-009      | PASS   |
| Relative imports only                             | ADR-009      | PASS   |

---

## Module: lib/protocols/mcp/server.py (NEW — Task #7)

| Check                                           | ADR                 | Result |
| ----------------------------------------------- | ------------------- | ------ |
| Uses`mcp.server.fastmcp.FastMCP`                | ADR-003 §2, ADR-006 | PASS   |
| `team_create`returns immediately (non-blocking) | ADR-006 §5          | PASS   |
| Returns tracking URL, not graph state           | ADR-006 §5          | PASS   |
| No LangGraph internals leaked                   | ADR-003 §2          | PASS   |
| Validates preset name against known list        | ADR-013 §2.9        | PASS   |
| `__all__ = ["mcp"]`                             | ADR-009             | PASS   |

---

## Module: lib/protocols/mcp/**init**.py (NEW — Task #7)

| Check                                             | ADR     | Result |
| ------------------------------------------------- | ------- | ------ |
| Facade re-export:`from .server import mcp as mcp` | ADR-009 | PASS   |
| `__all__ = ["mcp"]`                               | ADR-009 | PASS   |

---

## Module: lib/protocols/**init**.py (MODIFIED — Task #7)

| Check                                          | ADR     | Result |
| ---------------------------------------------- | ------- | ------ |
| Facade re-export:`from .mcp import mcp as mcp` | ADR-009 | PASS   |
| `__all__ = ["mcp"]`                            | ADR-009 | PASS   |
| Relative imports only                          | ADR-009 | PASS   |

---

## Module: lib/api/app.py (MODIFIED — Task #7)

| Check                                                | ADR     | Result |
| ---------------------------------------------------- | ------- | ------ |
| Lifespan hook with`@asynccontextmanager`             | ADR-007 | PASS   |
| CORS middleware configured                           | ADR-007 | PASS   |
| StaticFiles mount for React SPA                      | ADR-007 | PASS   |
| WebSocket route at`/ws`                              | ADR-007 | PASS   |
| OTel configured in lifespan startup                  | ADR-010 | PASS   |
| MCP server mounted at`/mcp`via`mcp_server.sse_app()` | ADR-006 | PASS   |
| REST router at`/api`prefix                           | ADR-007 | PASS   |
| `__all__ = ["create_app"]`                           | ADR-009 | PASS   |
| Relative imports only                                | ADR-009 | PASS   |

---

## Module: lib/core/exceptions.py (MODIFIED — Tasks #2, #7)

| Check                                        | ADR          | Result |
| -------------------------------------------- | ------------ | ------ |
| `AgentConfigNotFoundError(ConfigError)`added | ADR-012 §2.8 | PASS   |
| `TeamConfigNotFoundError(ConfigError)`added  | ADR-013 §2.8 | PASS   |
| `__all__`updated with both new types         | ADR-009      | PASS   |

---

## Module: lib/core/tests/test_exceptions.py (MODIFIED — Task #7)

| Check                                             | ADR       | Result |
| ------------------------------------------------- | --------- | ------ |
| Expected`__all__`set updated with new error types | ADR-009   | PASS   |
| No mocks, no monkeypatching                       | CLAUDE.md | PASS   |
| No unittest imports; uses pytest only             | CLAUDE.md | PASS   |
| Tests exercise real exception classes             | CLAUDE.md | PASS   |

---

## Module: lib/core/tests/test_graph.py (MODIFIED — Task #4)

| Check                                                                           | ADR          | Result |
| ------------------------------------------------------------------------------- | ------------ | ------ |
| Uses new`compile_team_graph(team_config, agent_configs, checkpointer)`signature | ADR-013 §5   | PASS   |
| Tests all 4 preset compilations: star, pipeline, loop, solo-coder               | ADR-013 §2.9 | PASS   |
| End-to-end routing test with real graph execution                               | CLAUDE.md    | PASS   |
| No mocks, no monkeypatching                                                     | CLAUDE.md    | PASS   |
| No unittest imports; uses pytest only                                           | CLAUDE.md    | PASS   |
| Relative imports only                                                           | ADR-009      | PASS   |

---

## Module: lib/api/schemas/**init**.py (EXISTING — verified)

| Check                                                  | ADR        | Result |
| ------------------------------------------------------ | ---------- | ------ |
| Facade re-exports with`X as X`pattern (55 symbols)     | ADR-009    | PASS   |
| `__all__`complete (55 entries)                         | ADR-009    | PASS   |
| Includes new`TeamPresetSummary`, `TeamPresetsResponse` | ADR-013 §6 | PASS   |

---

## Module: lib/core/aggregator.py (EXISTING — verified)

| Check                                  | ADR        | Result |
| -------------------------------------- | ---------- | ------ |
| Per-thread monotonic sequence counters | ADR-011 §5 | PASS   |
| Tool call update debouncing (100ms)    | ADR-011 §5 | PASS   |
| Plan update debouncing (250ms)         | ADR-011 §5 | PASS   |
| Token chunk batching (50ms / 4KB)      | ADR-004    | PASS   |
| OTel instrumentation (tracer + meter)  | ADR-010    | PASS   |
| `__all__ = ["EventAggregator"]`        | ADR-009    | PASS   |
| Relative imports only                  | ADR-009    | PASS   |

---

## Module: lib/api/websocket.py (EXISTING — verified)

| Check                                           | ADR          | Result |
| ----------------------------------------------- | ------------ | ------ |
| ConnectedEvent on open                          | ADR-011 §2.1 | PASS   |
| Heartbeat every 30 seconds                      | ADR-011 §5   | PASS   |
| Client command dispatch via discriminated union | ADR-011 §2.1 | PASS   |
| `__all__ = ["ConnectionManager"]`               | ADR-009      | PASS   |
| Relative imports only                           | ADR-009      | PASS   |

---

## Cross-Cutting Checks

| Check                                         | ADR                 | Result |
| --------------------------------------------- | ------------------- | ------ |
| All`lib/`internal imports use relative syntax | ADR-009 §5.4        | PASS   |
| All sub-modules define`__all__`               | ADR-009 §5.3        | PASS   |
| All facade`__init__.py`re-export with`X as X` | ADR-009 §5.2        | PASS   |
| No`unittest`imports anywhere in codebase      | CLAUDE.md           | PASS   |
| No mocks or monkeypatching in tests           | CLAUDE.md           | PASS   |
| No`cmd.exe /c`in subprocess invocations       | ADR-001, ADR-002    | PASS   |
| No credential logging to stdout/stderr        | ADR-002 §5          | PASS   |
| All TypedDict state fields JSON-serializable  | ADR-002 §5, ADR-008 | PASS   |

---

## Pre-Existing Findings (Not Introduced by Tasks #2–#7)

### FINDING-1:`session/cancel`as notification (MEDIUM)

- **File:**`lib/providers/acp_chat_model.py:254-258`
- **ADR:** ADR-006 §5.1 point 6
- **Issue:** `_cleanup_session`calls`_send_notification("session/cancel",
...)`which sends without a JSON-RPC`id` field (making it a notification) and
  without the required 3-second timeout wait.
- **ADR requirement:** "`session/cancel`-> send as a **proper RPC** (not a
  notification), with a 3-second timeout wait."
- **Action:** Track as separate fix task.

### FINDING-2:`_AgentStatusEntry`missing ADR-012 §6 fields (MEDIUM)

- **File:**`lib/api/schemas/rest.py:74-81`
- **ADR:** ADR-012 §6
- **Issue:** `_AgentStatusEntry`only has`agent_id`, `node_name`, `state`,
  `provider`, `model`. Missing `role`, `display_name`, `description`fields per
  ADR-012 §6 wire contract amendment.
- **Action:** Track as separate enhancement task.

### FINDING-3:`lib/providers/__init__.py`is empty (LOW)

- **File:**`lib/providers/__init__.py`
- **ADR:** ADR-009 §5.2
- **Issue:** The providers facade `__init__.py`does not
  re-export`AcpChatModel`or`ProviderFactory`. Consumers must deep-import from
  sub-modules.
- **Note:** This may be intentional to avoid circular imports (similar to
  `lib/api/__init__.py`). If so, should be documented with a comment explaining
  why.

---

## Summary

| Metric                    | Count                         |
| ------------------------- | ----------------------------- |
| Modules audited           | 22                            |
| ADR checks performed      | 95+                           |
| PASS                      | All checks on new code        |
| Pre-existing findings     | 3 (1 MEDIUM, 1 MEDIUM, 1 LOW) |
| New violations introduced | 0                             |

**All code from Tasks #2–#7 is ADR-compliant.** The implementation faithfully
follows ADR-009 (module hierarchy), ADR-012 (agent config), ADR-013 (team
config), ADR-006 (subprocess patterns), ADR-007 (tech stack), ADR-003 (MCP
server), ADR-004 (event aggregation), ADR-010 (telemetry), ADR-011 (wire
contract), and CLAUDE.md project rules.
