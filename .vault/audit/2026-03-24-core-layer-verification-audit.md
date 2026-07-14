---
tags:
  - '#audit'
  - '#core-layer'
date: '2026-03-24'
modified: '2026-03-24'
related:
  - '[[2026-03-23-core-layer-boundary-adr]]'
  - '[[2026-03-23-core-layer-boundary-research]]'
  - '[[2026-03-24-core-layer-isolation-plan]]'
---

# core-layer-verification — independent code review

Independent audit of the core-layer decomposition claims against code on disk
as of 2026-03-24. Every finding was verified by direct file inspection and grep,
not by trusting agent output.

---

## claim 1: all 6 violations (v-01 through v-06) are resolved

### v-01 — aggregator → api.schemas

**VERIFIED.**

`src/vaultspec_a2a/streaming/` has been decomposed into sub-modules. No file in
`streaming/` imports from `api.schemas` or `api.*` at all. Grep across the
entire `streaming/` tree (excluding tests) returned zero matches for
`from.*api\.`.

The original `aggregator.py` (now a thin composition root) imports only from
`..graph.*` (Layer 1 enums/events/protocols) and sibling streaming sub-modules.

### v-02 — aggregator → telemetry

**VERIFIED.**

No file in `streaming/` imports from `telemetry.*`. The OpenTelemetry coupling
is replaced by the `TelemetryHook` protocol defined in `graph/protocols.py`.
The concrete `NullTelemetryHook` ships in that same file. Callers inject a real
`TelemetryHook` at construction time (the `worker/executor.py` is responsible
for wiring the concrete telemetry implementation).

### v-03 — graph → database

**VERIFIED.**

`graph/compiler.py` imports from:
- `langchain_core.language_models`, `langgraph.*` (third-party)
- `vaultspec_a2a.domain_config`, `vaultspec_a2a.thread.*`, `vaultspec_a2a.utils.enums` (Layer 1)
- `graph.protocols.ProviderFactoryProtocol` (intra-layer protocol)
- `graph.nodes.*` (intra-layer)

Zero imports from `database.*`. The `Checkpointer` parameter is typed as
`langgraph.checkpoint.base.BaseCheckpointSaver`, a third-party abstract base
class with no dependency on the project's own database layer. The concrete
checkpointer is injected by `worker/executor.py`.

### v-04 — graph → providers

**VERIFIED.**

`graph/compiler.py` no longer imports `ProviderFactory` or `AcpSessionError`
from `providers.*`. Instead it declares `ProviderFactoryProtocol` (a
structural `Protocol`) in `graph/protocols.py` and accepts the factory as a
constructor argument typed against that protocol. The concrete `ProviderFactory`
is injected by `worker/executor.py` at runtime.

### v-05 — reconciliation → database

**VERIFIED.**

`lifecycle/reconciliation.py` contains only standard-library imports
(`__future__`, `dataclasses`, `enum`, `typing`). All database CRUD calls,
`ControlActionResultStatus`, `ControlActionType`, `RepairStatus`,
`ThreadStatus`, and async I/O are gone. The file defines pure dataclasses
(`ReconciliationAction`) and a pure function (`compute_reconciliation_actions`)
that reasons about state transitions without executing any database queries.
The database layer is now responsible for applying the decisions returned from
this function.

### v-06 — global settings singleton coupling in layer 1

**VERIFIED.**

No file under `thread/`, `context/`, `team/`, `graph/`, `lifecycle/`, or
`domain_config.py` imports from `control.config` or references the `settings`
singleton. Grep for `from.*control\.config` across all five directories returned
zero production matches (one hit was inside `streaming/tests/`, which is
acceptable — test infrastructure may reference infrastructure config).

`domain_config.py` introduces a focused `DomainConfig(BaseSettings)` that
contains **only** behavioral knobs (debounce windows, buffer sizes, token
budgets, recursion limits, LRU cache size). It excludes all infrastructure
values: no database URLs, ports, API keys, filesystem paths, or IPC parameters.
The singleton `domain_config = DomainConfig()` at line 138 is a legitimate
Layer 1 dependency because it reads only `VAULTSPEC_`-prefixed env vars that
govern core logic, not deployment topology.

**Nuance worth noting:** `domain_config.py` still uses `pydantic-settings`
(`BaseSettings`) as its base class. This does introduce `pydantic-settings`
as a Layer 1 dependency. Whether that counts as "infrastructure coupling" is
debatable — `pydantic-settings` is a configuration parsing library, not a
database, network, or telemetry dependency. Given the research document's
framing (concern was environment-backed global state with 80+ mixed values,
including API keys and ports), the scoped `DomainConfig` resolves the spirit of
V-06. The `pydantic-settings` dependency is a reasonable trade-off and not a
boundary violation in the same category as pulling in SQLAlchemy or
OpenTelemetry.

**Overall Claim 1 verdict: VERIFIED — all 6 violations are resolved.**

---

## claim 2: layer 1 (thread/, context/, team/, graph/, lifecycle/, domain_config.py) has zero imports from layer 2+

**VERIFIED.**

Full grep of all `from vaultspec_a2a.*` absolute imports across the five
directories and `domain_config.py` (production files only, tests excluded):

Every import resolves to one of:
- `vaultspec_a2a.domain_config` — Layer 1 domain config
- `vaultspec_a2a.thread.*` — Layer 1
- `vaultspec_a2a.context.*` — Layer 1
- `vaultspec_a2a.team.team_config` — Layer 1
- `vaultspec_a2a.graph.*` — Layer 1
- `vaultspec_a2a.utils.enums` — shared utility (no infrastructure dependencies)
- `vaultspec_a2a.protocols` — shared protocols

The only pattern match returned by the broad cross-layer grep was:
- `graph/events.py:7` — a **docstring** comment saying "Core never imports from
  `api.schemas`". This is documentation text, not an import statement.
- `graph/compiler.py:37` — `from .nodes.worker import WorkerNode,
  create_worker_node` — intra-layer import (worker node is in `graph/nodes/`,
  not in `worker/`).
- `thread/errors.py:150` — a **comment** in a docstring. Not an import.
- `graph/nodes/__init__.py:4` — intra-module re-export.

None of these are actual cross-layer violations.

**Claim 2 verdict: VERIFIED.**

---

## claim 3: layer 1.5 (streaming/) has zero imports from api/, database/, providers/, telemetry/, control/

**VERIFIED.**

Grep for `from.*api\.\|from.*database\|from.*providers\|from.*telemetry\|from.*worker\|from.*control\.`
across `streaming/` (excluding tests) returned **zero matches**.

All streaming sub-modules import only from:
- Python standard library
- `langgraph.*` / `langchain_core.*` (third-party)
- `..domain_config` (Layer 1)
- `..graph.*` (Layer 1 enums, events, protocols)
- `..thread.*` (Layer 1)
- Sibling streaming sub-modules

**Claim 3 verdict: VERIFIED.**

---

## claim 4: aggregator monolith decomposed into 6 sub-modules

**VERIFIED — with a size qualification.**

The sub-modules exist and contain real implementations:

| file | lines |
|------|-------|
| `streaming/aggregator.py` | 326 |
| `streaming/types.py` | 203 |
| `streaming/subscribers.py` | 199 |
| `streaming/buffering.py` | 235 |
| `streaming/emitters.py` | 629 |
| `streaming/transformer.py` | 469 |
| `streaming/ingest.py` | 214 |
| total | 2,275 |

`aggregator.py` at 326 lines is **not** below the claimed "< 400 lines
composition root" — but it is within the stated threshold. Its imports confirm
it is a composition root: it imports `BufferingManager`, `EventEmitters`,
`IngestManager`, `SubscriberManager` from siblings, and delegates to them.

The `emitters.py` at 629 lines is substantial. It is not a thin delegation
shim — it contains the bulk of the event-emission logic. Whether that
represents good decomposition or just relocation of the monolith's body into a
single large file is a design judgment call, not a falsifiable claim. What is
objectively true is that the monolith **was** split across 7 files (including
`aggregator.py`), each with a distinct responsibility:

- `types.py` — data types, protocols, helper functions (`SequencedEvent`,
  `StreamableGraph`, `classify_tool_kind`)
- `subscribers.py` — subscriber registry and dispatch
- `buffering.py` — chunk buffering and eviction
- `emitters.py` — all event-emission methods (the largest piece)
- `transformer.py` — LangGraph stream event → domain event transformation
- `ingest.py` — entry point for consuming LangGraph stream output
- `aggregator.py` — composition root wiring all sub-managers together

**Claim 4 verdict: VERIFIED — decomposition is real. The boundary between
`emitters.py` (629 lines) and `transformer.py` (469 lines) suggests the split
is coarser than ideal, but the monolith is genuinely split and not merely
renamed.**

---

## claim 5: providerfactory uses instance methods (not classmethod)

**VERIFIED.**

`providers/factory.py` line 238:

```python
class ProviderFactory:
    def create(
        self,
        provider: Provider,
        model: "Model | str | None" = None,
        ...
    ) -> BaseChatModel:
```

`def create(self, ...)` — instance method, no `@classmethod` decorator.

`graph/protocols.py` defines `ProviderFactoryProtocol` as a structural
`Protocol` with `def create(self, provider: Any, ...)`. The graph layer depends
only on this protocol. No `# type: ignore[arg-type]` suppression related to
`ProviderFactory` exists in the codebase. The two remaining `type: ignore`
comments in `compiler.py` (lines 383 and 519) are unrelated to
`ProviderFactory` — they suppress LangGraph internal type annotation gaps.

**Claim 5 verdict: VERIFIED.**

---

## claim 6: event adapter handles all content types (toolcallcontentdiff, toolcallcontentterminal)

**VERIFIED.**

`api/event_adapter.py` imports all three content type classes at the top of
the file (lines 50-53):

```python
ToolCallContent,
ToolCallContentDiff,
ToolCallContentTerminal,
ToolCallContentText,
```

The `_content_to_wire()` helper (line 67) branches on content type:
- `"text"` → `ToolCallContentText`
- `"diff"` → `ToolCallContentDiff`
- `"terminal"` → `ToolCallContentTerminal`

The `domain_to_wire()` function handles all 9 domain event types defined in
`graph/events.py`:

| domain event | wire event | handled |
|---|---|---|
| `MessageChunk` | `MessageChunkEvent` | yes |
| `ThoughtChunk` | `ThoughtChunkEvent` | yes |
| `ToolCallStart` | `ToolCallStartEvent` | yes |
| `ToolCallUpdate` | `ToolCallUpdateEvent` | yes |
| `PermissionRequest` | `PermissionRequestEvent` | yes |
| `PlanUpdate` | `PlanUpdateEvent` | yes |
| `ArtifactUpdate` | `ArtifactUpdateEvent` | yes |
| `AgentStatus` | `AgentStatusEvent` | yes |
| `TeamStatus` | `TeamStatusEvent` | yes |
| `ErrorOccurred` | `ErrorEvent` | yes |

The `case _:` branch (line 256) raises `TypeError` for any unmapped type,
ensuring future domain events fail loudly rather than silently.

**Claim 6 verdict: VERIFIED.**

---

## claim 7: 977 tests pass

**NOT VERIFIED — per instructions, tests were not run.**

Test execution was explicitly excluded from scope. This claim cannot be
confirmed or denied from static analysis alone.

---

## summary

| claim | verdict | notes |
|---|---|---|
| V-01 aggregator → api.schemas resolved | VERIFIED | zero api.* imports in streaming/ |
| V-02 aggregator → telemetry resolved | VERIFIED | TelemetryHook protocol replaces OTel SDK |
| V-03 graph → database resolved | VERIFIED | BaseCheckpointSaver injected, no database.* imports |
| V-04 graph → providers resolved | VERIFIED | ProviderFactoryProtocol; factory injected |
| V-05 reconciliation → database resolved | VERIFIED | pure stdlib-only file |
| V-06 config coupling resolved | VERIFIED | domain_config.py is scoped to behavioral knobs only |
| Layer 1 zero cross-layer imports | VERIFIED | all absolute imports resolve within Layer 1 + utils |
| Layer 1.5 streaming zero cross-layer imports | VERIFIED | zero matches across all 7 streaming files |
| aggregator decomposed into 6 sub-modules | VERIFIED | 7 files including composition root; emitters.py is large |
| ProviderFactory uses instance method | VERIFIED | `def create(self, ...)`, no @classmethod |
| type: ignore[arg-type] for ProviderFactory gone | VERIFIED | remaining suppressions are unrelated to ProviderFactory |
| event_adapter handles all content types | VERIFIED | all 9 domain events + 3 content variants mapped |
| 977 tests pass | NOT VERIFIED | not in scope per instructions |

**All verifiable claims check out. No false claims were found.**
