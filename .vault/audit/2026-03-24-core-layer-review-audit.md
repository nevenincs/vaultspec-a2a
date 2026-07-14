---
tags:
  - '#audit'
  - '#core-layer'
date: '2026-03-24'
modified: '2026-03-24'
related:
  - '[[2026-03-23-core-layer-boundary-plan]]'
  - '[[2026-03-23-core-layer-boundary-adr]]'
  - '[[2026-03-23-core-layer-boundary-research]]'
---

# `core-layer` Code Review

## Phase 1: `thread/` Review

**Status:** PASS

### Findings

- P1-001 | LOW | `__init__.py` omits `GitWorkspaceError` from facade re-exports
  `errors.py` defines and exports `GitWorkspaceError` via its own `__all__`, and `test_errors.py`
  acknowledges the omission with a comment ("GitWorkspaceError lives in errors but is NOT
  re-exported by the thread facade"). This is a deliberate design choice, but it is undocumented
  in the plan and creates an asymmetry: callers must import from `thread.errors` directly rather
  than the `thread` facade. Low risk, but the intent should be recorded in `thread/__init__.py`
  as a comment or docstring note so future reviewers do not attempt to "fix" it.

- P1-002 | LOW | `AgentConfigNotFoundError` and `TeamConfigNotFoundError` error messages
  reference the old path `src/vaultspec_a2a/core/presets/…`
  Both classes in `errors.py` (lines 261-295) hardcode the legacy preset path in their
  `__init__` message strings: `"src/vaultspec_a2a/core/presets/agents/{agent_id}.toml"`.
  After migration, the preset directory will live elsewhere (likely `team/presets/` or similar).
  Not a blocking issue for Phase 1, but the stale path will mislead users and developers once
  subsequent phases relocate presets.

- P1-003 | LOW | No test for `AgentConfigNotFoundError`, `TeamConfigNotFoundError`, or
  `NicknameConflictError` in `test_errors.py`
  The three exception classes with custom `__init__` signatures are not exercised by any test in
  `thread/tests/test_errors.py`. The parametrized `test_class_level_defaults` table includes only
  the 12 classes whose `__init__` matches the base `VaultspecError(message)` signature. A call like
  `AgentConfigNotFoundError("coder")` is untested — if a future refactor breaks the custom
  `__init__`, no test catches it. Not critical for Phase 1 correctness, but the coverage gap
  exists.

- P1-004 | LOW | `asyncio_compat.py` is effectively a no-op stub — migration is technically
  complete but the module body is vestigial
  The plan called for "Move `asyncio_compat.py` to `utils/`", which was done correctly
  (`utils/asyncio_compat.py` exists, call sites in `api/app.py` and `worker/app.py` import from
  `..utils.asyncio_compat`). However, the function body is now an empty pass-through with only
  a comment explaining why nothing is done. This is fine architecturally, but reviewers should be
  aware the module's ongoing utility is questionable — it may be a candidate for removal in Phase 7
  cleanup.

### Summary

All plan tasks for Phase 1 were executed correctly:

- `thread/state.py`, `thread/models.py`, `thread/errors.py` created with correct content.
- `ProviderSessionError` added to `errors.py` with appropriate severity/recovery defaults.
- `asyncio_compat.py` moved to `utils/`; call sites updated.
- `thread/__init__.py` re-exports all expected public symbols.
- `thread/tests/` contains `test_state.py`, `test_models.py`, `test_errors.py` with meaningful
  coverage — no mocks, no skips, no infrastructure dependencies (Layer 1 isolation confirmed).
- No imports from `api/`, `database/`, `providers/`, or `telemetry/` in any `thread/` file.
- Original `core/state.py`, `core/models.py`, `core/exceptions.py`, `core/asyncio_compat.py`
  deleted (confirmed absent).
- `core/__init__.py` shim deleted as well (no shim present at time of review).

Four low-severity findings noted, none blocking Phase 2 progression.

## Phase 2: Config Split Review

**Status:** PASS

### Findings

- P2-001 | INFO | Field count matches exactly: 18 domain + 75 infra = 93 total
  Original `core/config.py` had 93 `Field()`-declared fields (confirmed via git history at
  commit `9fe8590`). The split produces 18 in `DomainConfig` and 75 in `InfraConfig` — zero
  fields lost, zero added.

- P2-002 | INFO | All 18 domain field defaults are byte-for-byte identical to originals
  Cross-checked every default value in `domain_config.py` against the original. No regressions:
  `tool_call_debounce_seconds=0.100`, `plan_update_debounce_seconds=0.250`,
  `chunk_flush_interval_seconds=0.050`, `debounce_map_max_entries=1000`,
  `chunk_buffer_max_bytes=4096`, `tool_arg_truncate_len=1000`, `event_queue_maxsize=512`,
  `aget_state_timeout_seconds=10.0`, `context_limit_tokens=120_000`, `chars_per_token=4`,
  `anchor_path_cap=10`, `max_context_refs=50`, `vault_index_cap=50`,
  `mount_token_ceiling=20_000`, `min_remaining_tokens_for_mount=100`,
  `task_queue_pending_horizon=2`, `graph_recursion_limit=100`, `max_cached_graphs=32`.

- P2-003 | INFO | `DomainConfig` imports only `pydantic` and `pydantic_settings` — Layer 1 purity confirmed
  The file imports `Field` from `pydantic` and `BaseSettings, SettingsConfigDict` from
  `pydantic_settings`. No stdlib, no application imports, no infrastructure. Fully compliant
  with D-05's Layer 1 purity requirement.

- P2-004 | INFO | `isinstance(settings, DomainConfig)` is guaranteed True — MRO is correct
  `Settings(DomainConfig, InfraConfig)` resolves MRO as:
  `[Settings, DomainConfig, InfraConfig, BaseSettings, BaseModel, object]`.
  `issubclass(Settings, DomainConfig)` is `True` (verified at runtime). The plan's requirement
  is met without ambiguity.

- P2-005 | INFO | `extra="ignore"` present on `DomainConfig` — infra env vars silently ignored
  `SettingsConfigDict(env_prefix="VAULTSPEC_", extra="ignore")` on `DomainConfig` prevents
  validation errors when infrastructure env vars (e.g. `VAULTSPEC_DATABASE_URL`) are present
  in the environment and `DomainConfig` is instantiated standalone.

- P2-006 | INFO | `env_file` absent from `DomainConfig` — correct per D-05
  Only `InfraConfig` and `Settings` carry `env_file=".env"`. `DomainConfig` instantiated in
  Layer 1 tests will not trigger `.env` file reads. This preserves test isolation cleanly.

- P2-007 | INFO | `alias=` on `DomainConfig` fields does not double-prefix
  All 18 DomainConfig fields use `alias="VAULTSPEC_<NAME>"` alongside
  `env_prefix="VAULTSPEC_"`. Per pydantic-settings behaviour, an explicit `alias` overrides the
  prefix-based env var name (the alias is used verbatim). Verified at runtime: setting
  `VAULTSPEC_TOOL_CALL_DEBOUNCE_SECONDS=0.999` in the environment causes `DomainConfig()` to
  return `tool_call_debounce_seconds=0.999`. No double-prefix bug.

- P2-008 | INFO | Validators and properties correctly partitioned
  `_normalize_blank_internal_token` (`@field_validator`) stays on `InfraConfig` — it owns the
  `internal_token` field. `_derive_service_urls` (`@model_validator(mode="after")`) placed on
  `Settings` — it references `host`, `port`, `worker_host`, `worker_port` (all InfraConfig
  fields) and mutates `gateway_url`/`worker_url`; it cannot live on `DomainConfig` or
  `InfraConfig` alone. All `@property` items (`is_dev`, `resolved_database_backend`,
  `resolved_checkpoint_backend`, `database_path`, `checkpoint_path`,
  `checkpoint_connection_string`, `database_sync_url`) and `validate_postgres_requirement()`
  placed on `Settings` — correct, they cross both domains.

- P2-009 | LOW | `DomainConfig` field classification is correct but `event_queue_maxsize` is borderline
  `event_queue_maxsize` (asyncio queue depth for outgoing events) governs backpressure in the
  aggregator's event loop — this is genuine domain behavior. However it could be argued as an
  IPC tuning knob. The classification in `DomainConfig` is defensible and consistent with the
  ADR D-05 intent (aggregator behavioral knobs belong in domain config). Not a revision item.

- P2-010 | LOW | `DomainConfig` has no `env_file_encoding` in its `SettingsConfigDict`
  `InfraConfig` and `Settings` both specify `env_file_encoding="utf-8"`. `DomainConfig` only
  has `env_prefix` and `extra`. Since `DomainConfig` has no `env_file`, the missing encoding
  setting is harmless — it would only matter if a subclass or future change adds `env_file`
  back. Minor consistency gap, not a defect.

### Summary

Phase 2 implements D-05 correctly across all eight ADR criteria. Field coverage is complete
(93/93), all defaults are preserved, MRO guarantees `isinstance` holds, Layer 1 purity is
maintained, `extra="ignore"` prevents env var pollution, and validator/property placement is
semantically correct. Two low-severity observations noted (P2-009, P2-010), neither blocking.

Phase 2 is approved for progression to Phase 3.

## Phase 3: `context/` Review

**Status:** REVISION REQUIRED

### Findings

**PASS — Completeness and renames applied**

All 6 files are present: `metadata.py`, `preamble.py`, `anchoring.py`, `stage.py`, `rules.py`, `token_budget.py`. The renames from `phase.py` → `stage.py` and `context.py` → `token_budget.py` are correctly applied.

**PASS — `__init__.py` exports**

All public symbols are re-exported with explicit `as` aliases (PEP 484 re-export convention). `PHASE_ORDER`, `ContextRef`, `RuleManager`, `ThreadMetadata`, `build_anchoring_context`, `build_context_preamble`, `compact_context`, `discover_context_refs`, `estimate_tokens`, `generate_nickname`, `infer_phase_from_vault_index`, `prepare_handoff`, `should_compact` — all present. `__all__` is consistent.

**PASS — Within-module relative imports**

`preamble.py` correctly uses `from .metadata import ThreadMetadata`. No cross-file imports are needed elsewhere in `context/` and none are present.

**PASS — `thread.state` import**

`token_budget.py` correctly imports `from vaultspec_a2a.thread.state import TeamState`. `anchoring.py` correctly uses a `TYPE_CHECKING` guard for `TeamState` to avoid a runtime import cycle.

**PASS — No forbidden layer imports**

No imports from `api/`, `database/`, `providers/`, `telemetry/`, or `worker/` found in any `context/` file.

**PASS — Test files present and use canonical locations**

Tests exist for all 6 modules: `test_metadata.py`, `test_preamble.py`, `test_anchoring.py`, `test_stage.py`, `test_rules.py`, `test_token_budget.py`. All import from `vaultspec_a2a.context.*` (canonical new locations).

- P3-001 | HIGH | `control.config` imported in Layer 1 production files — violates plan Phase 3 step 2 and ADR D-05

  `metadata.py` (line 18), `anchoring.py` (line 17), and `token_budget.py` (line 12) all contain:

  ```python
  from vaultspec_a2a.control.config import settings
  ```

  `control/config.py` defines `InfraConfig(BaseSettings)` — a `pydantic_settings` class that reads
  from `.env` and environment variables. This is an infrastructure layer dependency. The plan
  (Phase 3, step 2) explicitly states: "Update imports: `config` -> `domain_config`". These files
  must import from `vaultspec_a2a.domain_config`, not `vaultspec_a2a.control.config`.

  All three accessed fields (`max_context_refs`, `anchor_path_cap`, `chars_per_token`) are
  confirmed to be defined on `DomainConfig` in `domain_config.py` (lines 74, 84, 89). The fix
  is a targeted import substitution with no logic changes.

  **Required fix** (same in all three files): replace
  `from vaultspec_a2a.control.config import settings` with
  `from vaultspec_a2a.domain_config import DomainConfig as _DomainConfig; settings = _DomainConfig()`
  or — if a module-level singleton is exported from `domain_config.py` — import that directly.

- P3-002 | MEDIUM | Test files import `control.config`, coupling test suite to infrastructure

  `test_metadata.py` (line 13) and `test_anchoring.py` (line 4) import:
  `from vaultspec_a2a.control.config import settings`

  This pulls `pydantic_settings` and `.env` file-read behaviour into Layer 1 tests, violating ADR
  D-06 ("zero infrastructure in core tests"). Once production files are fixed per P3-001, mirror
  the same import change in these two test files.

### Summary

Two findings share the same root cause: three production files and two test files import `settings`
from the infrastructure-layer `control.config` instead of the domain-layer `domain_config`. All
accessed fields (`max_context_refs`, `anchor_path_cap`, `chars_per_token`) exist on `DomainConfig`.
The fix is a targeted import swap — no logic changes required. Phase 3 must not progress to Phase 5
until P3-001 is resolved.

---

## Phase 4: `team/` Review

**Status:** PASS

### Findings

**PASS — Completeness**

`team_config.py` and `team/__init__.py` are present. The `presets/` directory contains both `agents/`
(12 TOML files) and `teams/` (10 TOML files), including all `mock-*` test fixtures and `vaultspec-*`
production presets.

**PASS — Preset discovery path**

`team_config.py` (lines 77–78) correctly resolves presets relative to its new location:

```python
_PRESET_AGENTS_DIR = Path(__file__).parent / "presets" / "agents"
_PRESET_TEAMS_DIR  = Path(__file__).parent / "presets" / "teams"
```

Since `__file__` resolves to `src/vaultspec_a2a/team/team_config.py`, both paths land at
`src/vaultspec_a2a/team/presets/{agents,teams}/` — correct.

**PASS — Import correctness: `thread.errors`**

`team_config.py` imports from `vaultspec_a2a.thread.errors`:

```python
from vaultspec_a2a.thread.errors import (
    AgentConfigNotFoundError, ConfigError, TeamConfigNotFoundError,
)
```

This satisfies the Phase 4 plan requirement "Update imports: `exceptions` -> `thread.errors`".

**PASS — Layer 1 purity**

No imports from `api/`, `database/`, `providers/`, `telemetry/`, `worker/`, or `control/` in
`team_config.py` or `team/__init__.py`. Only stdlib (`re`, `tomllib`, `pathlib`, `enum`),
third-party (`pydantic`), and sibling Layer 1 modules (`thread.errors`, `utils.enums`) are used.

**PASS — `__init__.py` exports**

All 17 public symbols from `team_config.py` are re-exported in `team/__init__.py` with explicit
`as` aliases. `__all__` is consistent with the re-exports.

**PASS — Test file present and uses correct import locations**

`tests/test_team_config.py` imports errors from `vaultspec_a2a.thread.errors` (canonical) and
uses a relative import `from ..team_config import ...` — correct for a test inside the package.

- P4-001 | LOW | Stale path reference in `AgentPermissionsConfig` docstring

  Line 121 in `team_config.py` references `src/vaultspec_a2a/core/graph.py` inside the
  `AgentPermissionsConfig` docstring. After Phase 5 completes, `graph.py` will move to `graph/`.
  This is a documentation nit; it does not affect correctness and will resolve naturally during
  Phase 7 cleanup. No action required before Phase 5.

### Summary

Phase 4 implements all plan requirements correctly. Preset discovery, layer boundary, import
updates, `__init__.py` exports, and test isolation all pass. One low-severity stale docstring
path noted (P4-001), not blocking. Phase 4 is approved.

## Phase 5: `graph/` Review

**Status:** REVISION REQUIRED

### Findings

- P5-001 | PASS | `graph/events.py` defines domain event dataclasses (plain `@dataclass`, not Pydantic)
  All 10 required event types present: `MessageChunk`, `ThoughtChunk`, `ToolCallStart`,
  `ToolCallUpdate`, `PermissionRequest`, `PlanUpdate`, `ArtifactUpdate`, `AgentStatus`,
  `TeamStatus`, `ErrorOccurred`. All inherit from `DomainEvent` base with primitive types
  only. Imports exclusively from `graph/enums.py`. ADR D-01 fully satisfied.

- P5-002 | PASS | `graph/enums.py` defines all required domain enums
  `AgentLifecycleState`, `ToolKind`, `ToolCallStatus`, `PermissionType`, `PermissionOptionKind`
  all present as `StrEnum` subclasses. No external infrastructure imports.

- P5-003 | PASS | `api/schemas/enums.py` correctly re-exports from `graph/enums.py`
  All five domain enums imported and re-exported with `as` aliases for backwards compatibility.
  Wire-protocol-only enums (`ServerEventType`, `ClientCommandType`, etc.) correctly remain local.
  Dependency inversion satisfied.

- P5-004 | PASS | `graph/protocols.py` defines `ProviderFactoryProtocol` and `TelemetryHook`
  Both protocols are `@runtime_checkable`. `NullTelemetryHook` implements all three methods
  (`start_span`, `increment_counter`, `record_histogram`) as no-ops. `start_span` correctly
  uses `@contextmanager`. ADR D-04 protocol definitions fully satisfied.

- P5-005 | PASS | `ProviderFactoryProtocol.create()` signature matches `ProviderFactory.create()`
  Signature accepts `provider: Any`, `model: Any | None`, `agent_config: Any | None`,
  `workspace_root: Path | None`, `**kwargs: Any`. Matches confirmed against call sites in
  `compiler.py` lines 134-138 and 211.

- P5-006 | PASS | `compile_team_graph()` accepts `checkpointer: BaseCheckpointSaver | None`
  Line 269: parameter typed `BaseCheckpointSaver | None` from `langgraph.checkpoint.base`.
  No import of `Checkpointer` from `database/` anywhere in `graph/`. ADR D-02 checkpointer
  injection satisfied.

- P5-007 | PASS | `compile_team_graph()` accepts `provider_factory: ProviderFactoryProtocol | None`
  Line 275: parameter present and correctly typed. ADR D-02 provider factory injection satisfied
  at the function signature level.

- P5-008 | HIGH | `compiler.py` imports `settings` from `control.config` — infrastructure boundary violation
  Line 27: `from vaultspec_a2a.control.config import settings`. Used at line 228 in
  `build_initial_vault_index()` for `settings.vault_index_cap`. This couples the graph compiler
  to the infrastructure config layer. ADR D-02 requires the graph layer to be infrastructure-free.
  The value should be accepted as a parameter or sourced from `domain_config`.

- P5-009 | HIGH | `compiler.py` lazy-import fallback imports `ProviderFactory` from `providers/`
  Lines 109-113: `_get_provider_factory()` does `from vaultspec_a2a.providers.factory import ProviderFactory`.
  Called whenever `provider_factory=None` is passed to `compile_team_graph()`,
  `_resolve_model_for_worker()`, and `_resolve_supervisor_model()`. While deferred (not at module
  load time), it is a direct cross-layer dependency from `graph/` into `providers/`. ADR D-02
  states there must be NO import of `ProviderFactory` from `providers/` in `compiler.py`.
  The transition comment acknowledges it is temporary, but it remains a live violation.

- P5-010 | PASS | No `AcpSessionError` reference in `compiler.py`
  `AcpSessionError` does not appear anywhere in `compiler.py`. `ProviderSessionError` is
  imported from `thread.errors` (line 29). ADR D-02 error replacement satisfied.

- P5-011 | HIGH | `nodes/supervisor.py` imports `settings` from `control.config`
  Line 17: `from vaultspec_a2a.control.config import settings`. Used at lines 231 and 234
  for `settings.context_limit_tokens`. A `graph/` node importing from the infrastructure
  config layer is a Layer 1 boundary violation.

- P5-012 | HIGH | `nodes/worker.py` imports `settings` from `control.config`
  Line 16: `from vaultspec_a2a.control.config import settings`. Used at lines 48 and 207
  for `settings.context_limit_tokens`. Same violation as P5-011.

- P5-013 | HIGH | `nodes/vault_reader.py` imports `settings` from `control.config`
  Line 10: `from vaultspec_a2a.control.config import settings`. Used at lines 97 and 101
  for `settings.mount_token_ceiling` and `settings.min_remaining_tokens_for_mount`.
  Same violation class.

- P5-014 | HIGH | `tools/task_queue.py` imports `settings` from `control.config`
  Line 12: `from vaultspec_a2a.control.config import settings`. Used at line 69 for
  `settings.task_queue_pending_horizon`. Same violation class.

- P5-015 | INFO | `TelemetryHook` protocol defined but not wired into compiler or nodes
  `protocols.py` defines `TelemetryHook` and `NullTelemetryHook` correctly per ADR D-04.
  However, `compile_team_graph()` does not accept a `telemetry_hook` parameter, and neither
  `nodes/supervisor.py` nor `nodes/worker.py` accept or use one. The protocol exists but the
  injection point is absent from the compiler signature. If this wiring is deferred to Phase 6,
  the plan should be updated to reflect that explicitly.

- P5-016 | PASS | No imports from `api/`, `database/`, or `telemetry/` in any `graph/` file
  All reviewed files confine imports to: stdlib, `langchain_core`, `langgraph`,
  `vaultspec_a2a.thread.*`, `vaultspec_a2a.context.*`, `vaultspec_a2a.utils.enums`,
  `vaultspec_a2a.team.team_config` (lazy in compiler), and `vaultspec_a2a.control.config`
  (violations flagged separately above).

### Summary

**6 HIGH findings require remediation before Phase 5 can be marked complete:**

| ID     | Severity | File                          | Issue                                              |
|--------|----------|-------------------------------|----------------------------------------------------|
| P5-008 | HIGH     | `graph/compiler.py`           | `settings` import from `control.config`            |
| P5-009 | HIGH     | `graph/compiler.py`           | Lazy `ProviderFactory` import from `providers/`    |
| P5-011 | HIGH     | `graph/nodes/supervisor.py`   | `settings` import from `control.config`            |
| P5-012 | HIGH     | `graph/nodes/worker.py`       | `settings` import from `control.config`            |
| P5-013 | HIGH     | `graph/nodes/vault_reader.py` | `settings` import from `control.config`            |
| P5-014 | HIGH     | `graph/tools/task_queue.py`   | `settings` import from `control.config`            |
| P5-015 | INFO     | `graph/compiler.py`           | `TelemetryHook` parameter absent from compiler sig |

**Recommended remediation path:**
- P5-008, P5-011-P5-014: The 5 `settings` fields used (`vault_index_cap`,
  `context_limit_tokens`, `mount_token_ceiling`, `min_remaining_tokens_for_mount`,
  `task_queue_pending_horizon`) are domain-level limits already present in `domain_config.py`
  (Phase 2 artifact). Replace `settings.*` reads with `DomainConfig().*` or inject a
  `DomainConfig` instance as a parameter.
- P5-009: Remove `_get_provider_factory()`. All callers must provide an explicit
  `provider_factory` argument; remove the `| None` default or raise `TypeError` when `None`.
- P5-015: Add `telemetry_hook: TelemetryHook | None = None` to `compile_team_graph()` if
  ADR D-04 compiler-level wiring is in scope for Phase 5, or explicitly defer to Phase 6.

## Phase 6: `streaming/` + `lifecycle/` Review

**Status:** REVISION REQUIRED

### Findings

- P6-001 | HIGH | `streaming/aggregator.py` imports enums from `api.schemas.enums` — `graph/enums.py` exists but is bypassed

  Lines 27–33 import `AgentLifecycleState`, `PermissionOptionKind`, `PermissionType`, `ToolCallStatus`, and `ToolKind` from `..api.schemas.enums`. `graph/enums.py` already holds the canonical definitions; `api/schemas/enums.py` now re-exports them verbatim (verified: lines 17–21 are `from vaultspec_a2a.graph.enums import X as X`). The aggregator therefore reaches the canonical types via the API re-export layer rather than the source. The fix is a one-import-block change and requires no logic changes.

- P6-002 | HIGH | `streaming/aggregator.py` imports 16 Pydantic wire-protocol event classes from `api.schemas.events` — `graph/events.py` exists but is unused; `api/event_adapter.py` not created

  Lines 34–51 import `AgentStatusEvent`, `ArtifactUpdateEvent`, `ErrorEvent`, `MessageChunkEvent`, `PermissionOption`, `PermissionRequestEvent`, `PlanEntry`, `PlanUpdateEvent`, `ServerEvent`, `TeamStatusEvent`, `ThoughtChunkEvent`, `ToolCallContent`, `ToolCallContentText`, `ToolCallStartEvent`, `ToolCallUpdateEvent`, and `AgentSummary` from `..api.schemas.events`. `graph/events.py` exists with the intended pure-dataclass domain events, but the aggregator does not import from it. Plan task 6.3 (`Create api/event_adapter.py for domain-to-wire event translation`) was not implemented. As a result `streaming/` has a hard compile-time dependency on `api/` — importing `EventAggregator` requires Pydantic and all FastAPI wire-protocol infrastructure. This is the primary BLOCKING violation for the Layer 1 goal.

- P6-003 | HIGH | `streaming/aggregator.py` calls `get_tracer`/`get_meter` from `telemetry.instrumentation` at module level — D-04 hook infrastructure exists but is not wired

  Line 53: `from ..telemetry.instrumentation import get_meter, get_tracer`. Lines 75–94 call these at module import time, creating four OTel instruments as module-level singletons. `graph/protocols.py` defines `TelemetryHook` and `NullTelemetryHook` (D-04 scaffolding is correct), but `EventAggregator.__init__` does not accept a `TelemetryHook` parameter and the module-level OTel singletons are used throughout (~20 call sites). Even after resolving P6-002, this import creates an infrastructure dependency at parse time.

- P6-004 | MEDIUM | `streaming/aggregator.py` uses the global `settings` singleton at 13 call sites — deferred per D-05 but blocks config injection

  Line 52: `from ..control.config import settings`. Used at lines 482, 619, 630, 672, 708, 845–846, 918, 922, 924, 1222, 1449–1451, 1637, 1642 for debounce timers, queue sizing, and truncation limits. `control/` is not a hard Layer 1 violation (it is below `api/`, `database/`, and `providers/`), but ADR D-05 requires progressive parameterization. Not blocking for the current phase goal but should be tracked.

- P6-005 | PASS | `graph/events.py` imports from `graph/enums.py` — correct dependency direction

  Lines 14–19 of `graph/events.py` import domain enums from `.enums` (relative within `graph/`). No violations.

- P6-006 | PASS | `lifecycle/reconciliation.py` is genuinely pure — D-03 fully satisfied

  Zero async functions. Zero database imports. Zero I/O. All stdlib imports are `dataclasses`, `enum`, and `typing`. Domain enum values are replicated as private `StrEnum` subclasses (`_ThreadStatus`, `_RepairStatus`, `_ControlActionType`) to avoid importing database CRUD enums. `compute_reconciliation_actions()` accepts plain `list[ThreadSnapshot]` and four `dict` inputs, returns `list[ReconciliationAction]` (frozen dataclass descriptors). Fully complies with ADR D-03.

- P6-007 | PASS | `database/reconciliation.py` correctly implements the I/O executor side of D-03

  Imports `compute_reconciliation_actions`, `ReconciliationAction`, and `ThreadSnapshot` from `lifecycle.reconciliation`. `probe_checkpoints()` is async with no DB dependency. `execute_reconciliation()` is async and takes an `AsyncSession`. `reconcile_threads_on_startup()` composes both. `api/app.py` line 50 imports `reconcile_threads_on_startup` from `database.reconciliation` — the call site is correct. D-03 is complete and clean.

- P6-008 | PASS | `streaming/__init__.py` re-exports all three required symbols

  Exports `EventAggregator`, `StreamableGraph`, `classify_tool_kind`. Matches plan requirement exactly.

- P6-009 | PASS | `lifecycle/__init__.py` re-exports `ReconciliationAction` and `compute_reconciliation_actions`

  Both public symbols re-exported. Correct.

- P6-010 | PASS | No remaining imports from `core/` in `streaming/` or `lifecycle/`

  Neither file contains any `from.*core` import. The only cross-package import from `streaming/aggregator.py` targeting the refactored modules is `from vaultspec_a2a.thread.errors import EventAggregatorError` (line 25) — correctly targeting `thread/`.

- P6-011 | INFO | D-04 hook path is clear — one constructor change away from complete

  `graph/protocols.py` defines a well-formed `TelemetryHook` protocol (`start_span`, `increment_counter`, `record_histogram`) and a `NullTelemetryHook` no-op. Adding `telemetry_hook: TelemetryHook | None = None` to `EventAggregator.__init__` and replacing the ~20 module-level OTel call sites with hook dispatches would complete D-04. No structural obstacles exist.

### Blocking Assessment for Layer 1 Boundary Enforcement

P6-002 is the primary blocker. `streaming/aggregator.py` cannot be imported without `api/` present because it directly instantiates Pydantic wire-protocol event objects. `graph/events.py` has the correct domain event dataclasses; `api/event_adapter.py` (plan task 6.3) is the missing piece. Until the aggregator emits domain events and a separate adapter translates them, the `api/` import cannot be removed.

P6-003 is a secondary blocker. Module-level OTel calls at lines 75–94 pull in `telemetry/` infrastructure on import regardless of P6-002's resolution.

P6-001 is mechanical (one import block change) and should be fixed alongside P6-002 for consistency.

The reconciliation split (D-03, P6-006 + P6-007) is fully complete and correct — no further work needed there.

**Neither deferred item (D-01 event conversion, D-04 telemetry hook wiring) is merely cosmetic — both create hard import-time infrastructure dependencies that prevent the stated Layer 1 goal.** Given that `graph/events.py`, `graph/enums.py`, `graph/protocols.py`, and `NullTelemetryHook` all exist, the required scaffolding is in place. The remaining work is wiring, not design.

### Checklist Summary

| Check | Result |
|---|---|
| D-01: aggregator imports from `api.schemas.events`? | YES — deferred; `graph/events.py` unused |
| D-01: enums sourced from `graph/enums.py`? | NO — imports via `api.schemas.enums` re-export layer |
| D-03: `lifecycle/reconciliation.py` is pure? | YES — PASS |
| D-03: `compute_reconciliation_actions()` takes data, returns descriptors? | YES — PASS |
| D-03: `database/reconciliation.py` handles I/O? | YES — PASS |
| D-03: `api/app.py` call site uses pure/I/O split? | YES — PASS |
| D-04: aggregator imports from `telemetry.instrumentation`? | YES — module-level; hook not wired |
| D-04: clear path to plug in `TelemetryHook`? | YES — `graph/protocols.py` scaffolding complete |
| General: canonical imports (thread.errors, control.config, etc.)? | YES — `thread.errors` confirmed |
| General: `streaming/__init__.py` re-exports 3 symbols? | YES — PASS |
| General: no remaining `core/` imports? | YES — PASS |
| `api/event_adapter.py` exists? | NO — plan task 6.3 not implemented |

## Phase 7: Cleanup + Overall Architecture Review

**Status:** REVISION REQUIRED

### Findings

- P7-001 | PASS | `core/` directory is fully deleted — confirmed absent from filesystem
  `src/vaultspec_a2a/core/` does not exist. No `__pycache__` remnants found under any `core/`
  path. Phase 7 task 3 (delete `core/` entirely) is complete.

- P7-002 | PASS | Zero `from.*core import` or `from.*core\.` import statements in production code
  All matches for `.core.` are Sphinx-style docstring cross-references in
  `api/__init__.py` (line 5), `providers/probes/openai.py` (line 35),
  `providers/probes/zhipu.py` (line 36), and `providers/probes/claude.py`. Not live import
  statements. `vaultspec_a2a.core` does not appear in any `import` or `from` statement.

- P7-003 | INFO | Stale docstring references in three probe files
  `providers/probes/openai.py:35`, `providers/probes/zhipu.py:36`, `providers/probes/claude.py`
  reference `:attr:~vaultspec_a2a.core.config.Settings.*`. These are Sphinx doc-tool cross-
  references, not runtime code. No import failure. Should be updated to `control.config.Settings`
  to keep Sphinx output accurate. Not blocking.

- P7-004 | INFO | Stale docstring in `api/__init__.py` references old aggregator location
  Line 5: `"They depend on vaultspec_a2a.core.aggregator, which in turn imports from..."` The
  circular import concern described no longer applies after migration. The docstring is stale and
  misleading about current architecture. Minor cleanup item.

- P7-005 | CRITICAL | V-01 NOT resolved — `streaming/aggregator.py` still imports from `api.schemas`
  Lines 27-51: 5 enums from `api.schemas.enums` and 16 Pydantic event classes from
  `api.schemas.events`. ADR D-01 required the aggregator to emit domain event dataclasses from
  `graph/events.py` with an `api/event_adapter.py` for wire translation. That adapter is absent.
  `graph/events.py` domain events exist but are completely unused by the aggregator. Physical
  relocation (`core/` to `streaming/`) occurred without structural correction. Also identified
  as P6-001 and P6-002.

- P7-006 | CRITICAL | V-02 NOT resolved — `streaming/aggregator.py` still imports from `telemetry`
  Line 53: `from ..telemetry.instrumentation import get_meter, get_tracer`. Lines 75-94: module-
  level OTel instrument creation. ADR D-04 required these to be replaced by an optional
  `TelemetryHook` parameter at construction time. `graph/protocols.py` correctly defines
  `TelemetryHook` and `NullTelemetryHook` but they are never wired into `EventAggregator`.
  Importing `streaming.aggregator` still triggers OpenTelemetry SDK initialization at module load.
  Previously identified as P6-003.

- P7-007 | HIGH | V-04 partial — `_get_provider_factory()` retains live `providers/` import
  `graph/compiler.py` lines 109-113: deferred `from vaultspec_a2a.providers.factory import
  ProviderFactory`. Called whenever `provider_factory=None` (the default). ADR D-02 prohibits
  any `providers/` import in `graph/`. `ProviderFactoryProtocol` is correctly defined and typed,
  but the fallback preserves the coupling at call time. Previously identified as P5-009.

- P7-008 | HIGH | V-06 progressive parameterization incomplete — 6 files still import `Settings`
  `graph/compiler.py:26`, `graph/nodes/supervisor.py:17`, `graph/nodes/worker.py:16`,
  `graph/nodes/vault_reader.py:10`, `graph/tools/task_queue.py:12`, and
  `streaming/aggregator.py:52` all import `settings` from `control.config`. All accessed fields
  are `DomainConfig` fields (domain-level limits). The `DomainConfig`/`Settings` split from Phase
  2 is correct, but these files still couple to the full infra-backed singleton. ADR D-05
  requires progressive parameterization to `DomainConfig`. Previously identified as P5-008,
  P5-011 through P5-014, P3-001, P6-004.

- P7-009 | INFO | `api/event_adapter.py` absent — Phase 6 plan task 3 not implemented
  The Phase 6 plan explicitly required this file for domain-to-wire event translation. Its
  absence is the direct cause of P7-005. Previously identified as P6-002.

### Violation Resolution Matrix

| Violation | Status | Notes |
|-----------|--------|-------|
| V-01 | OPEN | `streaming/aggregator.py` lines 27-51 still import `api.schemas.enums` and `api.schemas.events`. `api/event_adapter.py` not created. Domain events in `graph/events.py` unused. |
| V-02 | OPEN | `streaming/aggregator.py` line 53 still imports `telemetry.instrumentation`. Module-level OTel init at lines 75-94. `TelemetryHook` defined in `graph/protocols.py` but not wired. |
| V-03 | RESOLVED | `graph/compiler.py` accepts `BaseCheckpointSaver` as parameter. No `database.checkpoints` import in `graph/`. |
| V-04 | PARTIAL | `ProviderFactoryProtocol` defined and used as parameter type. Fallback `_get_provider_factory()` (lines 109-113) retains a live `providers.factory` import. |
| V-05 | RESOLVED | `lifecycle/reconciliation.py` is purely functional with zero I/O. `database/reconciliation.py` holds the I/O executor. Clean split confirmed. |
| V-06 | PARTIAL | `DomainConfig`/`InfraConfig`/`Settings` split complete (Phase 2 PASS). Six production files still import `Settings` singleton instead of accepting `DomainConfig` as parameter. |

### Architecture Verification

| Module | Expected | Status |
|--------|----------|--------|
| `thread/` | `state.py`, `models.py`, `errors.py` | PRESENT |
| `context/` | `metadata.py`, `preamble.py`, `anchoring.py`, `stage.py`, `rules.py`, `token_budget.py` | PRESENT |
| `team/` | `team_config.py`, `presets/` | PRESENT |
| `graph/` | `compiler.py`, `enums.py`, `events.py`, `protocols.py`, `nodes/`, `tools/` | PRESENT |
| `streaming/` | `aggregator.py` | PRESENT |
| `lifecycle/` | `reconciliation.py` | PRESENT |
| `domain_config.py` | at package root | PRESENT |
| `control/config.py` | Settings facade | PRESENT |
| `database/reconciliation.py` | I/O executor | PRESENT |
| `api/event_adapter.py` | domain-to-wire adapter | ABSENT |

### Circular Import Analysis

No circular import risks detected among the new modules:
- `thread/` imports only framework types (`langgraph`, `langchain_core`)
- `context/` imports from `thread.state` (lower-layer, permitted)
- `team/` imports from `thread.errors` (lower-layer, permitted)
- `graph/` imports from `thread.*`, `utils.enums`, and framework types only (in production files)
- `streaming/` imports `thread.errors` (clean) and `api.schemas.*` (V-01 violation, noted)
- `lifecycle/` has zero internal cross-module imports
- `api/schemas/enums.py` re-exports from `graph.enums` — dependency direction correct

### Overall Verdict

REVISION REQUIRED

The feature branch correctly completed the structural decomposition: `core/` is deleted, all six
module directories exist with the correct files, domain enums and event dataclasses are properly
defined in `graph/`, and V-03 (checkpointer injection) and V-05 (reconciliation split) are
cleanly resolved with no regressions.

However, two CRITICAL violations (V-01 and V-02) from the original research remain open in
`streaming/aggregator.py`. The module was physically relocated from `core/` to `streaming/` but
neither the `api.schemas` coupling (ADR D-01) nor the telemetry coupling (ADR D-04) was
corrected. V-04 and V-06 have the correct scaffolding in place but injection wiring was not
completed.

Required before this branch can be marked complete:

1. P7-005 / V-01 — Create `api/event_adapter.py`. Rewrite `streaming/aggregator.py` to
   emit domain events from `graph/events.py`; remove all `api.schemas` imports from the file.
2. P7-006 / V-02 — Wire `TelemetryHook` into `EventAggregator.__init__` with
   `NullTelemetryHook` as default; remove module-level `get_tracer`/`get_meter` calls.
3. P7-007 / V-04 — ~~Delete `_get_provider_factory()` fallback in `graph/compiler.py`;
   require explicit `provider_factory` injection at all call sites.~~ **CLOSED by Phase 8d.**
4. P7-008 / V-06 — Replace `from control.config import settings` with `DomainConfig`
   parameter injection in 5 `graph/` files and `streaming/aggregator.py`.

---

## Phase 8d: Provider Factory DI Review

**Status:** PASS

### Findings

- `_get_provider_factory()` is completely absent from `graph/compiler.py`. No trace of
  the function or any `from vaultspec_a2a.providers` import at module level.

- `compile_team_graph()` declares `provider_factory: ProviderFactoryProtocol` as a
  required keyword-only parameter (after `*`, line 265). There is no default value and
  no `None`-fallback path. A missing argument raises `TypeError` at the call site before
  any graph compilation begins.

- The three internal topology helpers all carry the same keyword-only signature:
  - `_compile_star()` — `*, provider_factory: ProviderFactoryProtocol` (line 394)
  - `_compile_pipeline()` — `*, provider_factory: ProviderFactoryProtocol` (line 528)
  - `_compile_pipeline_loop()` — `*, provider_factory: ProviderFactoryProtocol` (line 699)

  All three receive `provider_factory=provider_factory` forwarded from `compile_team_graph()`
  and pass it down to `_resolve_model_for_worker()` and `_resolve_supervisor_model()`, which
  are also keyword-only.

- All call sites pass `provider_factory=` explicitly:

  | File | Call site |
  |---|---|
  | `graph/tests/test_compiler.py` | All 11 `compile_team_graph()` calls use `provider_factory=pf` or `provider_factory=ProviderFactory` |
  | `graph/tests/test_graph_execution.py` | All 3 `compile_team_graph()` calls use `provider_factory=pf` |
  | `graph/tests/test_e2e_live.py` | line 136 — `provider_factory=pf` |
  | `worker/executor.py` | line 972 — `provider_factory=self._provider_factory` |
  | `tests/preps/_runner.py` | line 64 — `provider_factory=ProviderFactory` |
  | `docker/run.py` | line 130 — `provider_factory=ProviderFactory` |

- The only remaining `providers` import in `graph/` is in test files
  (`from vaultspec_a2a.providers.factory import ProviderFactory`). Test files are outside
  the Layer 1 boundary rule; this is the correct injection point for the concrete factory.

- ADR D-02 satisfied: `graph/compiler.py` imports zero symbols from
  `vaultspec_a2a.providers`. The `ProviderFactoryProtocol` it consumes lives in
  `graph/protocols.py` (Layer 1 peer). P7-007 / V-04 is fully closed.

---

## Phase 8b+8c: Settings Swap Review

**Status:** PASS

### Findings

- P8BC-001 | PASS | `domain_config.py` exports `DomainConfig` class and `domain_config` singleton at module scope (line 138), both in `__all__` (line 141).
- P8BC-002 | PASS | `context/metadata.py` — import is `from vaultspec_a2a.domain_config import domain_config` (line 18); usage `domain_config.max_context_refs` (line 130). Field exists on `DomainConfig`.
- P8BC-003 | PASS | `context/anchoring.py` — import is `from vaultspec_a2a.domain_config import domain_config` (line 17); usage `domain_config.anchor_path_cap` (line 50). Field exists on `DomainConfig`.
- P8BC-004 | PASS | `context/token_budget.py` — import is `from vaultspec_a2a.domain_config import domain_config` (line 12); usage `domain_config.chars_per_token` (line 42). Field exists on `DomainConfig`.
- P8BC-005 | PASS | `graph/compiler.py` — import is `from vaultspec_a2a.domain_config import domain_config` (line 26); usage `domain_config.vault_index_cap` confirmed present. No `control.config` import. The only `settings` string in the file is a comment token inside a code comment (line 368: `# TOML-05: apply per-preset graph settings.`), not an import.
- P8BC-006 | PASS | `graph/nodes/supervisor.py` — import is `from vaultspec_a2a.domain_config import domain_config` (line 17); usage `domain_config.context_limit_tokens` (lines 231–232). Field exists on `DomainConfig`.
- P8BC-007 | PASS | `graph/nodes/worker.py` — import is `from vaultspec_a2a.domain_config import domain_config` (line 16); usage `domain_config.context_limit_tokens` (lines 46–47). Field exists on `DomainConfig`.
- P8BC-008 | PASS | `graph/nodes/vault_reader.py` — import is `from vaultspec_a2a.domain_config import domain_config` (line 10); usage `domain_config.mount_token_ceiling` (line 97) and `domain_config.min_remaining_tokens_for_mount` (line 101). Both fields exist on `DomainConfig`.
- P8BC-009 | PASS | `graph/tools/task_queue.py` — import is `from vaultspec_a2a.domain_config import domain_config` (line 12); usage `domain_config.task_queue_pending_horizon` (line 69). Field exists on `DomainConfig`.
- P8BC-010 | PASS | Zero `from vaultspec_a2a.control.config import settings` occurrences in any `context/` or `graph/` production file.
- P8BC-011 | INFO | Stale docstring in `context/metadata.py` line 93 reads `"Returns at most ``settings.max_context_refs`` results."` — references old symbol name. Production code is correct; only the docstring is stale. Not a functional defect.
- P8BC-012 | INFO | Two test files (`context/tests/test_anchoring.py:81`, `context/tests/test_metadata.py:198`) contain comments referencing `settings.anchor_path_cap` / `settings.max_context_refs`. Per plan Phase 8b step 2 these were in scope for update but are comments only — no import or runtime impact.

### Summary

All 8 production files correctly import `domain_config` from `vaultspec_a2a.domain_config` and access the expected field names. Every field accessed (`max_context_refs`, `anchor_path_cap`, `chars_per_token`, `vault_index_cap`, `context_limit_tokens`, `mount_token_ceiling`, `min_remaining_tokens_for_mount`, `task_queue_pending_horizon`) is present on `DomainConfig` with matching names. The singleton and `__all__` are correctly established in Phase 8a. Two stale docstring/comment references to the old `settings` symbol are cosmetic and carry no runtime risk.

## Phase 8e: Domain Event Conversion Review

**Status:** REVISION REQUIRED

### Findings

**Checklist Results**

- P8E-001 | PASS | `streaming/aggregator.py` has ZERO `from ..api` imports. Grep for `from.*api` returns no matches. The module-level `api.schemas.events` imports that existed pre-refactor are fully removed.
- P8E-002 | PASS | Aggregator imports enums from `..graph.enums` (lines 32–38: `AgentLifecycleState`, `PermissionOptionKind`, `PermissionType`, `ToolCallStatus`, `ToolKind`). Zero `api.schemas.enums` imports. Zero `control.config` imports.
- P8E-003 | PASS | All 10 domain event types are imported from `..graph.events` (lines 39–51). Every emit method constructs domain dataclasses: `MessageChunk` (lines 659, 792), `ThoughtChunk` (811), `ToolCallStart` (848), `ToolCallUpdate` (899), `PermissionRequest` (957, 1070), `ArtifactUpdate` (1187), `PlanUpdate` (1210), `ErrorOccurred` (1237), `AgentStatus` (769), `TeamStatus` (1295). No Pydantic wire-event constructors appear.
- P8E-004 | PASS | `SequencedEvent` is correctly defined as a plain `@dataclass` wrapping `event: DomainEvent` and `sequence: int` (lines 72–83). The subscriber queue type is `asyncio.Queue[SequencedEvent]` (line 278). The docstring correctly documents its role as a wire-protocol-concern carrier.
- P8E-005 | PASS | `api/event_adapter.py` exists and handles all 10 domain event types in `domain_to_wire()` via a `match` statement. A fallback `case _:` raises `TypeError` for unmapped types. The `sequenced_to_wire()` convenience wrapper is present. No domain event type is absent.
- P8E-006 | FAIL | **`locations` field dropped in `ToolCallStartEvent` and `ToolCallUpdateEvent` construction.** Both domain events carry `locations: list[dict[str, str | int | None]]` and both wire schema models declare `locations: list[ToolCallLocation]` (with `default_factory=list`). The adapter constructs `ToolCallStartEvent` (lines 96–106) and `ToolCallUpdateEvent` (lines 116–126) without mapping domain `locations` dicts to `ToolCallLocation(path=..., line=...)` objects. File-location data present in domain events is silently discarded before wire delivery. **This is a functional data-loss defect.**
- P8E-007 | PASS | `PlanEntry` mapping correctly constructs `PlanEntry(content=..., status=PlanEntryStatus(...), priority=PlanEntryPriority(...))` from domain `list[dict[str, str]]`. `PermissionOption` mapping correctly constructs `PermissionOption(option_id=..., name=..., kind=PermissionOptionKind(...))`. `AgentSummary` mapping handles all six required fields; `provider` and `model` are correctly omitted (both optional on wire schema, absent from domain dict). `ToolCallContentText` is correctly constructed from dicts filtering on `content_type == "text"`.
- P8E-008 | PASS | `api/websocket.py` imports `sequenced_to_wire` from `.event_adapter` (line 28) and calls it in `_writer_loop` (lines 627–631): `wire_event = sequenced_to_wire(event) if isinstance(event, SequencedEvent) else event`. The branch handles both domain-originated `SequencedEvent` objects and pre-serialised relay dicts from `broadcast_to_thread`.
- P8E-009 | PASS | `streaming/__init__.py` re-exports `SequencedEvent` in both the import list (line 5) and `__all__` (line 12).
- P8E-010 | INFO | `AgentSummary` wire model has `provider: Provider | None = None` and `model: Model | None = None` fields. The `TeamStatus` domain event stores agents as `list[dict[str, str]]` — plain string dicts that cannot carry typed `Provider`/`Model` enum values. Provider and model are silently absent from team status wire events. This is an existing domain model limitation, not introduced by Phase 8e, and carries no regression risk.
- P8E-011 | INFO | `api/event_adapter.py` imports `AgentLifecycleState` from `..api.schemas.enums` (line 32) for use in the `TeamStatus` → `AgentSummary` mapping. This is correct: the adapter sits in Layer 2 (`api/`) and constructing wire-protocol Pydantic models from `api.schemas.enums` types is its explicit responsibility. No boundary violation.
- P8E-012 | INFO | The `sequenced_to_dict()` function (lines 231–235) uses `dataclasses.asdict()` on the domain event. For events with enum fields (`ToolKind`, `ToolCallStatus`, `AgentLifecycleState`, `PermissionType`), `asdict()` preserves the enum objects — callers consuming the dict via the relay path must handle enum serialisation separately. This is not introduced by Phase 8e but is worth noting for the relay path.

### Required Fix Before Merge

**P8E-006 — `locations` mapping in `api/event_adapter.py`**

The adapter must map `event.locations` to `list[ToolCallLocation]` for both `ToolCallStart` and `ToolCallUpdate` cases. The fix is mechanical:

```python
# ToolCallStart case — add before constructing ToolCallStartEvent:
locations = [
    ToolCallLocation(
        path=loc.get("path", ""),
        line=loc.get("line"),  # int | None
    )
    for loc in event.locations
]
# then pass locations=locations to ToolCallStartEvent(...)

# ToolCallUpdate case — add conditional mapping:
upd_locations: list[ToolCallLocation] | None = None
if event.locations is not None:
    upd_locations = [
        ToolCallLocation(path=loc.get("path", ""), line=loc.get("line"))
        for loc in event.locations
    ]
# then pass locations=upd_locations to ToolCallUpdateEvent(...)
```

`ToolCallLocation` is already exported from `api.schemas.events` — only the import and mapping lines need adding.

### Summary

Phase 8e is architecturally sound. The aggregator is fully clean of `api.schemas` imports, all 10 domain event types are correctly emitted as dataclasses, `SequencedEvent` is correctly defined and re-exported, and `websocket.py` correctly calls the adapter before sending. One functional defect (P8E-006) requires a fix before merge: `locations` data carried on `ToolCallStart` and `ToolCallUpdate` domain events is not mapped to `ToolCallLocation` objects in the adapter, causing silent data loss for file-location annotations on tool calls.

---

## Phase 8f+8g: Telemetry Hooks + Settings Swap Review

**Status:** PASS

### Findings

**Checklist 1 — `streaming/aggregator.py` free of `telemetry/` imports**

PASS. The import block (lines 16–52) contains zero imports from any
`telemetry/` package. The only telemetry-related import is
`from ..graph.protocols import NullTelemetryHook, TelemetryHook` — a
Layer 1 peer import, not a Layer 2 import.

**Checklist 2 — `streaming/aggregator.py` free of `control.config` imports**

PASS. No `control.config` or `settings` import exists anywhere in the file.
The settings swap (Phase 8g) is complete: `domain_config` is imported at
line 31 via `from ..domain_config import domain_config` and used at all
13 former `settings.*` access sites (verified below).

**Checklist 3 — ALL 6 module-level OTel instruments removed**

PASS. The plan identified module-level definitions at lines 75–94 of the
pre-refactor file (`_tracer`, `_meter`, and 4 instrument variables). None
of these exist in the current file. There are no module-level `get_tracer`,
`get_meter`, `_counter`, or `_histogram` definitions anywhere in the file.

**Checklist 4 — `NullTelemetryHook.start_span()` yields a usable object**

PASS. `NullTelemetryHook.start_span()` is a `@contextmanager` that yields
`_NULL_SPAN` — a singleton `_NullSpan` instance. `_NullSpan` has a
`set_attribute(key, value) -> None` method. The aggregator calls
`span.set_attribute(...)` at two sites (lines 1843, 1939) — both within
`with self._telemetry.start_span(...) as span:` blocks. `_NullSpan`
silently absorbs these calls. The other two `start_span` usages (lines 566,
652) use `with ... :` without `as span:`, so no attribute access occurs.
All four call sites are handled correctly.

**Checklist 5 — `OTelAggregatorHook` matches `TelemetryHook` protocol**

PASS. Protocol signature comparison:

| Method | Protocol | `OTelAggregatorHook` |
|---|---|---|
| `start_span(name, **attrs)` | `AbstractContextManager[Any]` | `@contextmanager` — structurally satisfies |
| `increment_counter(name, value=1, **attrs)` | `None` | `None` — exact match |
| `record_histogram(name, value, **attrs)` | `None` | `None` — exact match |

One observation: `OTelAggregatorHook.start_span` is annotated `-> Any`
rather than `-> AbstractContextManager[Any]`. This is minor annotation
looseness, not a runtime violation — `@contextmanager` functions return
`contextlib.GeneratorContextManager` which satisfies `AbstractContextManager`.

The class satisfies `TelemetryHook` structurally via duck typing, which is
correct for `@runtime_checkable Protocol` usage.

**Checklist 6 — Hook wired correctly in `api/app.py`**

PASS. Line 1149 of `api/app.py`:

```python
aggregator = EventAggregator(telemetry=OTelAggregatorHook())
```

`OTelAggregatorHook` is imported at line 59 via
`from ..telemetry.aggregator_hook import OTelAggregatorHook`. The `telemetry=`
keyword matches `EventAggregator.__init__`'s parameter name exactly. The hook
is passed at construction time as required by ADR D-04.

**Checklist 7 — All 13 `settings.X` → `domain_config.X` swaps correct**

PASS. All 13 usages confirmed — all call `domain_config.<field>`:

| Line | Field accessed |
|---|---|
| 475 | `domain_config.event_queue_maxsize` |
| 616 | `domain_config.tool_call_debounce_seconds` |
| 627 | `domain_config.plan_update_debounce_seconds` |
| 670 | `domain_config.chunk_flush_interval_seconds` |
| 708 | `domain_config.chunk_buffer_max_bytes` |
| 837 | `domain_config.tool_arg_truncate_len` |
| 838 | `domain_config.tool_arg_truncate_len` (truncation suffix) |
| 911 | `domain_config.tool_call_debounce_seconds` |
| 915 | `domain_config.debounce_map_max_entries` |
| 1219 | `domain_config.plan_update_debounce_seconds` |
| 1452 | `domain_config.tool_arg_truncate_len` |
| 1641 | comment referencing `domain_config.aget_state_timeout_seconds` |
| 1643 | `domain_config.aget_state_timeout_seconds` |

Zero `settings` references remain in the file.

**Additional: `telemetry/aggregator_hook.py` structure**

The new file exists at `src/vaultspec_a2a/telemetry/aggregator_hook.py`.
It implements the three required methods. Lazy instrument creation in
`increment_counter` and `record_histogram` (dict-backed `_counters` /
`_histograms`) is correct — instruments are created once on first use.
`get_tracer` and `get_meter` are called eagerly at `__init__` time (standard
OTel practice). No concerns.

**Minor observations (non-blocking)**

- P8fg-001 | LOW | `OTelAggregatorHook.start_span` return annotation is `Any`
  Tightening to `-> AbstractContextManager[Any]` would match the protocol
  declaration and improve type-checker visibility. Runtime behaviour is
  unaffected.

- P8fg-002 | INFO | `flush_chunks` span does not capture the yielded span object
  The `with self._telemetry.start_span("aggregator.flush_chunks", ...):` at
  line 652 uses no `as span:`. No attributes are set on it. This is consistent
  with the intent — the span marks duration only. Not an issue.

**ADR D-04 compliance:** Fully implemented. `streaming/aggregator.py` has
zero `telemetry/` imports, zero `control.config` imports, zero module-level
OTel instrument definitions, and relies entirely on the injected
`TelemetryHook`. `NullTelemetryHook` is the default. The real OTel hook is
isolated in `telemetry/aggregator_hook.py` and wired at the API boundary in
`api/app.py`.

---

## Phase 8h: Final Boundary + Architecture Gate Review

**Status:** PASS

### Layer 1 Boundary

Searched all production `.py` files in `thread/`, `context/`, `team/`, `graph/`, `lifecycle/`, and `domain_config.py` for imports from Layer 2+ packages (`api/`, `database/`, `providers/`, `telemetry/`, `control/`, `worker/`, `streaming/`).

**Result: ZERO violations.**

Evidence:
- `thread/` — zero live import matches. One grep hit in `errors.py` is a docstring comment, not an import statement.
- `context/` — zero matches. All previously-flagged files (P3-001) now correctly import `domain_config` from `vaultspec_a2a.domain_config` (P8BC-002 through P8BC-004 confirmed).
- `team/` — zero matches.
- `graph/` — zero absolute cross-layer import paths. All `..` relative imports within `graph/` resolve only to sibling submodules (`nodes/` → `tools/`, `compiler.py` → `nodes/`). No path targets `api/`, `database/`, `providers/`, `telemetry/`, `control/`, `worker/`, or `streaming/`.
- `lifecycle/` — zero matches. `lifecycle/reconciliation.py` imports only `dataclasses`, `enum`, and `typing`.
- `domain_config.py` — imports only `pydantic` and `pydantic_settings`. Zero application-layer imports.

### Layer 1.5 Boundary

Searched all production `.py` files in `streaming/` (excluding `tests/`) for imports from `api/`, `database/`, `providers/`, `telemetry/`, `control/`, `worker/`.

**Result: ZERO violations.**

Evidence from `streaming/aggregator.py` top-level imports (lines 16–52): `asyncio`, `json`, `logging`, `time`, `collections`, `dataclasses`, `datetime`, `typing`, `uuid`, `langgraph.types`, `vaultspec_a2a.thread.errors` (Layer 1 peer), `vaultspec_a2a.domain_config` (Layer 1 peer), `vaultspec_a2a.graph.enums` (Layer 1 peer), `vaultspec_a2a.graph.events` (Layer 1 peer), `vaultspec_a2a.graph.protocols` (Layer 1 peer). The previously CRITICAL V-01 (`api.schemas.*`) and V-02 (`telemetry.instrumentation`) imports are fully absent.

### Violation Resolution Matrix

| Violation | Status | Evidence |
|-----------|--------|----------|
| V-01 (aggregator → api.schemas) | RESOLVED | `streaming/aggregator.py` has zero `api` imports. `api/event_adapter.py` exists. Aggregator emits domain events from `graph/events.py`. All 10 domain event constructors confirmed (Phase 8e P8E-003). |
| V-02 (aggregator → telemetry) | RESOLVED | `streaming/aggregator.py` has zero `telemetry` imports. Module-level `get_tracer`/`get_meter` calls removed. `NullTelemetryHook` wired at construction time (Phase 8fg confirmed). `telemetry/aggregator_hook.py` exists as real OTel hook. |
| V-03 (graph → database.checkpoints) | RESOLVED | `graph/compiler.py` uses `BaseCheckpointSaver` from `langgraph.checkpoint.base` only. Zero `database` imports in any `graph/` production file. |
| V-04 (graph → providers) | RESOLVED | `_get_provider_factory()` deleted. `compile_team_graph()` requires `provider_factory: ProviderFactoryProtocol` as mandatory keyword-only parameter. Zero `providers` imports in any `graph/` production file (Phase 8d PASS). |
| V-05 (reconciliation → database.crud) | RESOLVED | `lifecycle/reconciliation.py` is stdlib-only. `database/reconciliation.py` holds the I/O executor. Call site in `api/app.py` confirmed correct. |
| V-06 (settings singleton) | RESOLVED | Zero `from vaultspec_a2a.control.config import settings` in any Layer 1 production file. All 9 previously-coupled files import `domain_config` from `vaultspec_a2a.domain_config`. `domain_config.py` exports singleton with no infrastructure coupling. |

### Architecture Completeness

| Artifact | Location | Status |
|---|---|---|
| `graph/events.py` — domain event dataclasses | `src/vaultspec_a2a/graph/events.py` | PRESENT |
| `graph/enums.py` — domain enums | `src/vaultspec_a2a/graph/enums.py` | PRESENT |
| `graph/protocols.py` — `ProviderFactoryProtocol`, `TelemetryHook`, `NullTelemetryHook` | `src/vaultspec_a2a/graph/protocols.py` | PRESENT |
| `api/event_adapter.py` — domain → wire translation | `src/vaultspec_a2a/api/event_adapter.py` | PRESENT |
| `telemetry/aggregator_hook.py` — real OTel hook | `src/vaultspec_a2a/telemetry/aggregator_hook.py` | PRESENT |
| `lifecycle/reconciliation.py` — pure decision logic | `src/vaultspec_a2a/lifecycle/reconciliation.py` | PRESENT |
| `database/reconciliation.py` — I/O executor | `src/vaultspec_a2a/database/reconciliation.py` | PRESENT |

All 7 required architecture artifacts are present.

### Open Non-Blocking Item

**P8E-006** (carried from Phase 8e): `api/event_adapter.py` drops `locations` data when constructing `ToolCallStartEvent` and `ToolCallUpdateEvent` wire objects. This is a functional data-loss defect in the adapter (Layer 2), not a boundary violation. It does not affect Layer 1 purity and is not a gate blocker for boundary enforcement, but must be resolved before production shipment.

### Overall Verdict

**PASS**

All 6 ADR boundary violations are fully resolved. Layer 1 boundary is clean across all five directories (`thread/`, `context/`, `team/`, `graph/`, `lifecycle/`) and `domain_config.py`. Layer 1.5 (`streaming/`) boundary is clean. All 7 required architecture artifacts exist. The `core/` module is fully deleted with zero stale imports. Domain event dataclasses, enums, protocols, telemetry hook wiring, and reconciliation I/O split are correctly implemented and wired. This branch satisfies all criteria of `docs/adrs/040-layer-boundary-enforcement.md`.
