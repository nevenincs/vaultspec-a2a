# Cross-Module Structural Audit

**Date**: 2026-03-06
**Auditor**: codebase-researcher
**Scope**: All 10 submodules under `src/vaultspec_a2a/`

---

## 1. Stale `lib.` References

After Task #42 batch-fixed actionable paths, a full sweep confirms:

- **Total raw hits**: 17 (down from original 27)
- **Actionable (actual imports)**: 0 -- all remaining are docstrings/comments
- **Genuine stale reference**: 1 -- `api/tests/__init__.py:1` contains a comment with `lib.` path
- **Non-actionable**: 16 -- all in `docs/adrs/*.md`, `docs/audits/*.md`, and code comments describing historical migration

**Verdict**: No runtime impact. The single test `__init__.py` comment is cosmetic.

---

## 2. Deep Imports Bypassing Facades

The following cross-module imports reach into submodule internals rather than importing from the facade (`__init__.py`):

### CRITICAL (private symbol access)

| Consumer | Imported Symbol | Source (deep path) | Facade Available? |
|---|---|---|---|
| `workspace/git_ops.py` | `_git_mutex` | `workspace/sandbox.py` | No (private) |
| `telemetry/middleware.py` | `_SDK_DISABLED` | `telemetry/instrumentation.py` | No (private) |

These are intra-module private shares -- acceptable since both consumer and source are in the same submodule. No cross-module private leaks found.

### HIGH (cross-module deep imports)

| Consumer | Imported Symbol | Source (deep path) | Should Use Facade? |
|---|---|---|---|
| `api/endpoints.py` | `build_initial_vault_index` | `core.graph` | Yes -- available via `core.__init__` lazy import |
| `api/app.py` | `EventAggregator` | `core.aggregator` | Yes -- available via `core.__init__` lazy import |
| `api/app.py` | `settings` | `core.config` | Yes -- `core.settings` |
| `worker/executor.py` | `compile_team_graph` | `core.graph` | Yes -- available via `core.__init__` lazy import |
| `worker/executor.py` | `build_initial_vault_index` | `core.graph` | Yes -- available via `core.__init__` lazy import |
| `worker/app.py` | `EventAggregator` | `core.aggregator` | Yes -- available via `core.__init__` lazy import |

**Note**: The `core.aggregator` and `core.graph` deep imports are partially justified by the lazy-import pattern in `core/__init__.py` -- direct imports avoid the `__getattr__` overhead on hot paths (lifespan startup, worker dispatch). However, they violate ADR facade policy.

### MED (api/schemas deep imports)

| Consumer | Imported Symbol | Source (deep path) |
|---|---|---|
| `core/aggregator.py` | Multiple event schemas | `api.schemas.events` |
| `core/nodes/supervisor.py` | `PlanApprovalPayload` | `api.schemas.events` |
| `worker/app.py` | `DispatchRequest` | `api.schemas.requests` |

The `api/schemas/__init__.py` facade re-exports 62 symbols. These deep imports are unnecessary -- all symbols are available at `api.schemas.*`.

---

## 3. Facade Gaps

Symbols that are public API but missing from their submodule's `__init__.py`:

### Fixed during this sprint

| Symbol | Module | Fix Task |
|---|---|---|
| `StreamableGraph` | `core/__init__.py` | ADR-027 compliance sprint |
| `WorkerNode` | `core/nodes/worker.py` | ADR-027 compliance sprint |
| `build_initial_vault_index` | `core/__init__.py` | Task #35 (added to lazy imports) |
| `run_migrations` | `database/__init__.py` | ADR-029 sprint |
| `update_thread` | `database/__init__.py` | ADR-029 sprint |
| `backfill_teamstate_sdd_fields` | `database/__init__.py` | ADR-029 sprint |

### Remaining gaps (LOW priority)

| Symbol | Module | Notes |
|---|---|---|
| `RuleManager` | `core/__init__.py` | Used only by worker/supervisor nodes internally; not needed at facade level unless external consumers emerge |
| `AcpChatModel` | `providers/__init__.py` | Available via lazy `__getattr__`; not in `__all__` but resolves at runtime |
| `TelemetryMiddleware` | `telemetry/__init__.py` | Exported in `__all__` but only consumed by `api/app.py` via deep import |

**Verdict**: No blocking facade gaps remain. All HIGH/CRIT gaps were resolved in earlier sprints.

---

## 4. Dead Code

### Confirmed dead -- deleted this sprint

| Item | Location | LOC | Task |
|---|---|---|---|
| 27 `.figma.tsx` files | `src/ui/src/app/components/` | 905 | Task #18 |
| `is_palindrome.py` | `utils/` (deleted ADR-027 sprint) | ~15 | ADR-027 |
| `plan_approval.py` | `core/nodes/` (deleted WS2 sprint) | ~80 | LangGraph alignment |
| `"researcher"` role entry | `core/phase.py` `_ROLE_TO_PHASE` | 1 line | ADR-027 |

### Confirmed alive (false positives from initial scan)

| Item | Why alive |
|---|---|
| `_GraphInterrupt` in `aggregator.py` | Used in `isinstance` check at line 1528 |
| `GraphInterrupt` in `test_aggregator.py` | Raised by `_InterruptingGraph.astream` at line 1075 |
| `mcp/server.py` tool functions | Registered dynamically by MCP framework, not imported |
| `evals/` entry points | Invoked via `python -m evals.suites.*`, not imported |
| CLI subcommands in `cli/` | Registered via `click` decorators, not direct imports |

### Potential dead code (needs manual verification)

| Item | Location | Notes |
|---|---|---|
| `_CacheControlMiddleware` | `api/app.py` | Only useful if SPA build dir exists; no-op otherwise. Alive but conditional. |
| `backfill_teamstate_sdd_fields()` | `database/migrations.py` | Called once at lifespan startup; will become dead after all existing DBs are migrated |

---

## 5. Circular Import Management

Two managed circular dependency cycles exist, both handled correctly:

### Cycle 1: `core` <-> `api.schemas`
- **Direction**: `core.aggregator` imports event types from `api.schemas.events`; `api.schemas` imports `TeamState` from `core.state`
- **Mitigation**: No `__init__.py`-level cross-import. Both sides import from submodules directly, avoiding circular resolution at package init time.

### Cycle 2: `core` <-> `providers`
- **Direction**: `core.graph` imports `create_chat_model` from `providers.factory`; `providers.acp_chat_model` imports `TeamConfig` from `core.team_config`
- **Mitigation**: `core.__init__.py` uses lazy `__getattr__` for `compile_team_graph` and `build_initial_vault_index` (both in `core.graph`). `providers/__init__.py` uses lazy `__getattr__` for `create_chat_model`, `AcpChatModel`, `GeminiChatModel`.

### No unmanaged cycles detected
A dependency graph traversal confirms no other circular paths exist between the 10 submodules.

---

## Summary

| Category | Total Found | Resolved | Remaining | Severity |
|---|---|---|---|---|
| Stale `lib.` refs | 27 | 26 | 1 (comment) | LOW |
| Deep imports | 12 | 0 | 12 | MED (6 HIGH, 6 justified) |
| Facade gaps | 9 | 6 | 3 | LOW |
| Dead code | ~1001 LOC | ~1001 LOC | 0 confirmed | CLEAR |
| Circular imports | 2 cycles | 2 managed | 0 unmanaged | CLEAR |

**Overall structural health**: GOOD. No blocking issues. The 6 HIGH deep imports in Section 2 are the primary candidates for cleanup in a future hygiene pass -- each has a facade-level equivalent available.
