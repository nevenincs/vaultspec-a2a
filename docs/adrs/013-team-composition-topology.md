---
adr_id: 013
title: Team Composition & Topology (TOML Config)
date: 2026-02-27
status: Proposed
related:
  - docs/adrs/008-orchestration-topology-pipeline.md
  - docs/adrs/009-approved-module-hierarchy.md
  - docs/adrs/011-frontend-backend-contract.md
  - docs/adrs/012-agent-definition-schema.md
---

# ADR-013: Team Composition & Topology (TOML Config)

**Date:** 2026-02-27
**Status:** Proposed

## 1. Context & Problem Statement

`compile_team_graph()` currently accepts a flat `dict[str, BaseChatModel]`
with no concept of team identity, topology choice, or agent ordering. The
supervisor is always present; the graph is always a "star" where every worker
reports back to the supervisor. There is no way to select a team for a thread
(`CreateThreadRequest` has no `team_preset` field), and `TeamState` carries
no team identity.

The research synthesis identified three concrete topology patterns that are
directly expressible with the LangGraph APIs already present in the codebase:

| Topology | LangGraph API | When to Use |
| --- | --- | --- |
| `star` | `add_conditional_edges(supervisor, ...)` | Open-ended tasks needing dynamic routing |
| `pipeline` | `add_sequence(order)` | Fixed-order workflows (plan → code → review) |
| `pipeline_loop` | `add_sequence()` + `add_conditional_edges(loop_node)` | Iterative refinement (code → review → revise) |

None of these alternatives are implemented; only `star` exists, hardcoded
in `graph.py`. This ADR formalizes all three as config-driven options.

## 2. Decision

Each team preset is defined by a TOML file at:

```text
{workspace_root}/.vaultspec/teams/{team_id}.toml
```

Built-in presets ship in `lib/core/presets/teams/`. A new `TeamConfig`
Pydantic model in `lib/core/team_config.py` validates and deserializes these
files. `compile_team_graph()` is refactored to accept a `TeamConfig` instead
of raw `BaseChatModel` dicts.

### 2.1 TOML Schema

#### Star Topology (current behavior, now configurable)

```toml
# .vaultspec/teams/open-team.toml

[team]
id          = "open-team"
display_name = "Open Team"
description  = "General-purpose team with dynamic supervisor routing."

[team.defaults]
provider   = "claude"
capability = "mid"

[team.supervisor]
provider   = "claude"
capability = "max"

[team.topology]
type = "star"

[[team.workers]]
agent_id = "planner"

[[team.workers]]
agent_id = "coder"
# Per-worker model override (merges with team defaults, then agent TOML):
model.capability = "high"

[[team.workers]]
agent_id = "reviewer"
```

#### Pipeline Topology

```toml
# .vaultspec/teams/pipeline-team.toml

[team]
id           = "pipeline-team"
display_name = "Pipeline Team"
description  = "Sequential plan → code → review pipeline."

[team.defaults]
provider   = "claude"
capability = "mid"

[team.topology]
type  = "pipeline"
order = ["planner", "coder", "reviewer"]
# No supervisor section — pipeline does not require a supervisor node.

[[team.workers]]
agent_id = "planner"

[[team.workers]]
agent_id = "coder"

[[team.workers]]
agent_id = "reviewer"
```

#### Pipeline-Loop Topology

```toml
# .vaultspec/teams/loop-team.toml

[team]
id           = "loop-team"
display_name = "Loop Team"
description  = "Iterative code → review → revise loop with up to 3 cycles."

[team.defaults]
provider   = "claude"
capability = "mid"

[team.topology]
type      = "pipeline_loop"
order     = ["planner", "coder", "reviewer"]
loop_node = "reviewer"      # This node's output decides: "revise" → coder | END
max_loops = 3

[[team.workers]]
agent_id = "planner"

[[team.workers]]
agent_id = "coder"

[[team.workers]]
agent_id = "reviewer"
```

### 2.2 Full Field Reference

**`[team]` block:**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `team.id` | `str` | Yes | Unique identifier. Must match filename stem. |
| `team.display_name` | `str` | Yes | Human-readable name surfaced on the frontend. |
| `team.description` | `str` | No | Purpose description, shown in team picker UI. |

**`[team.defaults]` block:**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `team.defaults.provider` | `str` | No | Default provider for all workers (overridden per-agent). |
| `team.defaults.capability` | `str` | No | Default capability level (overridden per-agent). |
| `team.defaults.provider_fallback` | `list[str]` | No | Ordered fallback provider list (lowest priority in three-level chain). |

**`[team.supervisor]` block** (required only for `star` and `pipeline_loop`):

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `team.supervisor.provider` | `str` | No | Supervisor provider (defaults to `team.defaults.provider`). |
| `team.supervisor.capability` | `str` | No | Supervisor capability (defaults to `max` if omitted). |

**`[team.topology]` block:**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `team.topology.type` | `str` | Yes | `star`, `pipeline`, or `pipeline_loop`. |
| `team.topology.order` | `list[str]` | `pipeline`/`pipeline_loop` only | Ordered list of `agent_id` values. |
| `team.topology.loop_node` | `str` | `pipeline_loop` only | Agent whose output triggers the conditional edge back into the loop. |
| `team.topology.max_loops` | `int` | No | Maximum iterations before forcing END (default: `3`). |

**`[[team.workers]]` array:**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `agent_id` | `str` | Yes | References `agents/{agent_id}.toml`. |
| `model.provider` | `str` | No | Per-worker provider override. Wins over `team.defaults` and agent TOML. |
| `model.capability` | `str` | No | Per-worker capability override. |
| `model.provider_fallback` | `list[str]` | No | Per-worker fallback provider list (highest priority in three-level chain). |

**`[team.permissions]` block:**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `team.permissions.auto_approve` | `bool` | No | When `true`, all ACP permission requests are auto-approved (autonomous mode). Default: `false`. |

**`[team.persona]` block:**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `team.persona.directive` | `str` | No | Additional directive text appended to the supervisor system prompt. |
| `team.persona.supervisor_display_name` | `str` | No | Override the supervisor's display name in UI and events. |

**`[team.graph]` block:**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `team.graph.step_timeout_seconds` | `int` | No | Per-node execution timeout in seconds. `null` means no timeout. |
| `team.graph.recursion_limit` | `int` | No | LangGraph recursion limit passed to `compile()`. Default: `25`. Range: `1`–`500`. |

### 2.3 Model Resolution Precedence

Model binding follows a strict three-level override chain:

```text
[[team.workers]] model.* (highest priority)
    ↓
agent TOML [agent.model].*
    ↓
[team.defaults].* (lowest priority / fallback)
```

`ProviderFactory.create(provider, capability)` is called once per worker
with the resolved values. The `provider_fallback` list follows the same
three-level chain: worker override wins over agent TOML, which wins over
team defaults. Lists are not merged — the highest-priority non-empty list
is used verbatim.

### 2.4 Pydantic Models (`lib/core/team_config.py`)

```python
import tomllib
from pathlib import Path
from pydantic import BaseModel, Field, model_validator
from ..utils.enums import Provider, Model


class WorkerOverrideConfig(BaseModel):
    provider: Provider | None = None
    capability: Model | None = None
    provider_fallback: list[Provider] = Field(default_factory=list)


class WorkerRef(BaseModel):
    agent_id: str
    model: WorkerOverrideConfig = Field(default_factory=WorkerOverrideConfig)


class TopologyConfig(BaseModel):
    type: str                              # "star" | "pipeline" | "pipeline_loop"
    order: list[str] = Field(default_factory=list)
    loop_node: str | None = None
    max_loops: int = 3

    @model_validator(mode="after")
    def validate_topology(self) -> "TopologyConfig":
        if self.type in ("pipeline", "pipeline_loop") and not self.order:
            raise ValueError(f"topology.order required for type={self.type!r}")
        if self.type == "pipeline_loop" and self.loop_node is None:
            raise ValueError("topology.loop_node required for type='pipeline_loop'")
        return self


class SupervisorConfig(BaseModel):
    provider: Provider | None = None
    capability: Model | None = None


class TeamDefaultsConfig(BaseModel):
    provider: Provider | None = None
    capability: Model | None = None
    provider_fallback: list[Provider] = Field(default_factory=list)


class TeamPermissionsConfig(BaseModel):
    auto_approve: bool = False


class TeamPersonaConfig(BaseModel):
    directive: str | None = None
    supervisor_display_name: str | None = None


class TeamGraphConfig(BaseModel):
    step_timeout_seconds: int | None = None
    recursion_limit: int = Field(default=25, ge=1, le=500)


class TeamConfig(BaseModel):
    id: str
    display_name: str
    description: str = ""
    defaults: TeamDefaultsConfig = Field(default_factory=TeamDefaultsConfig)
    supervisor: SupervisorConfig = Field(default_factory=SupervisorConfig)
    topology: TopologyConfig
    workers: list[WorkerRef]
    permissions: TeamPermissionsConfig = Field(default_factory=TeamPermissionsConfig)
    persona: TeamPersonaConfig = Field(default_factory=TeamPersonaConfig)
    graph: TeamGraphConfig = Field(default_factory=TeamGraphConfig)

    @classmethod
    def from_toml(cls, path: Path) -> "TeamConfig":
        with path.open("rb") as f:
            data = tomllib.load(f)
        return cls.model_validate(data["team"])
```

### 2.5 Topology → StateGraph Compilation

`compile_team_graph()` is refactored from accepting raw model dicts to
accepting a `TeamConfig` + resolved `AgentConfig` list. The three topology
types compile to distinct LangGraph graph structures:

#### Star (`add_conditional_edges`)

```python
# Current behavior generalized.
builder.add_node("supervisor", supervisor_node, metadata={...})
for agent_config in resolved_agents:
    builder.add_node(agent_config.id, worker_node, metadata={...})
    builder.add_edge(agent_config.id, "supervisor")

builder.add_edge(START, "supervisor")
route_map = {a.id: a.id for a in resolved_agents}
route_map["FINISH"] = END
builder.add_conditional_edges("supervisor", lambda s: s["next"], route_map)
```

#### Pipeline (`add_sequence`)

```python
# No supervisor node needed.
node_names = []
for agent_id in team_config.topology.order:
    agent_config = resolved_agents_by_id[agent_id]
    builder.add_node(agent_config.id, worker_node, metadata={...})
    node_names.append(agent_config.id)

builder.add_edge(START, node_names[0])
builder.add_sequence(node_names)           # state.py:889 — auto-wires consecutive edges
# add_sequence handles: node_names[0]→[1]→[2]→...→END
```

#### Pipeline-Loop (`add_sequence` + `add_conditional_edges`)

```python
# Supervisor needed only if loop_node requires external routing.
# The loop_node itself performs the conditional: "revise" → coder | END.
order = team_config.topology.order
loop_node_id = team_config.topology.loop_node
pre_loop = [aid for aid in order if aid != loop_node_id]

for agent_id in order:
    agent_config = resolved_agents_by_id[agent_id]
    builder.add_node(agent_config.id, worker_node, metadata={...})

builder.add_edge(START, pre_loop[0])
builder.add_sequence(pre_loop + [loop_node_id])   # planner→coder→reviewer

# reviewer routes back to coder or to END
loop_target = pre_loop[-1]  # "coder" — the last pre-loop node
builder.add_conditional_edges(
    loop_node_id,
    lambda state: state["next"],                   # state.py:839
    {"revise": loop_target, "FINISH": END},
)
```

The `max_loops` guard is enforced by tracking iteration count in
`TeamState.loop_count: int` (new field, default 0, incremented by
loop_node, forced to `FINISH` when `loop_count >= max_loops`).

### 2.6 Supervisor Prompt Enhancement

In `star` topology, the supervisor's system prompt is enhanced with the
agent description roster from each `AgentConfig.description`. This replaces
the current bare worker-name list and enables LLM-driven routing based on
agent capabilities:

```python
# Current (bare name list):
f"Your active team members are: {', '.join(workers)}."

# After ADR-013:
roster = "\n".join(
    f"- {cfg.display_name} ({cfg.id}): {cfg.description}"
    for cfg in resolved_agents
)
f"Your team members and their specializations:\n{roster}"
```

This is the mechanism by which TOML `description` fields influence routing —
the supervisor LLM reads them and selects agents accordingly.

### 2.7 Permission Gating (Superseded)

> **Note:** The original `interrupt_before` assembly described here has been
> superseded. The graph now **always** compiles with `interrupt_before=[]`.

Permission gating is handled entirely by the `permission_callback` closure
wired into each worker node at compile time (see `lib/core/graph.py`). When
`autonomous=False`, the callback calls `interrupt()` to suspend the graph
and emit a `PermissionRequestEvent`; when `autonomous=True`, the callback
auto-approves.

`agent.permissions.require_approval_for` in `AgentPermissionsConfig`
(ADR-012) is retained in the schema for forward-compatibility but is
**not currently consumed** by the graph compilation pipeline. The field
may be used in a future fine-grained per-tool approval implementation.

### 2.8 Config Discovery Order

```text
1. {workspace_root}/.vaultspec/teams/{team_id}.toml   (workspace override)
2. lib/core/presets/teams/{team_id}.toml               (bundled default)
3. Raise TeamConfigNotFoundError                        (fail fast)
```

### 2.9 Built-in Preset Teams

| File | Topology | Workers | Use Case |
| --- | --- | --- | --- |
| `coding-star.toml` | `star` | planner, coder, reviewer | Open-ended coding tasks |
| `coding-pipeline.toml` | `pipeline` | planner, coder, reviewer | Structured delivery tasks |
| `coding-loop.toml` | `pipeline_loop` | planner, coder, reviewer | Iterative quality refinement |
| `solo-coder.toml` | `pipeline` | coder only | Single-agent quick fixes |

## 3. Rationale

### Topology Must Be Declared in Config, Not Emerge at Runtime

`StateGraph` is compiled once and is immutable after `compile()`. The graph
topology (which nodes exist, which edges connect them) is fixed at
compilation. `Command(goto=...)` provides runtime routing flexibility
**within** the declared edge set — it cannot add new edges at runtime.
Therefore, topology must be a compile-time declaration, which means it must
come from config.

### LLM-Driven Routing Over Declarative TOML Edges

The research unanimously shows that every multi-agent framework (A2A,
DeepAgents, CrewAI's hierarchical mode) uses LLM-driven routing where the
supervisor reads agent descriptions and decides delegation. Declarative TOML
edge tables (e.g., `coder → reviewer`) would replicate topology in two places
(both `[team.topology.order]` and an explicit edge table), introduce
redundancy, and remove the supervisor's ability to skip steps when appropriate.

The `[team.topology.type]` field declares the **structural pattern**
(star/pipeline/loop); the LLM decides **which agent within that pattern** acts
next. These are orthogonal concerns.

### `lib/core/team_config.py` Over a New `lib/teams/` Submodule

A full `lib/teams/` submodule (loader + registry + Pydantic models + tests)
adds structural overhead for a feature that is, at its core, two Pydantic
model trees and a `tomllib.load()` call. For v1, co-locating `team_config.py`
in `lib/core/` alongside `graph.py` minimizes the module surface. If team
management grows (e.g., team versioning, team-to-thread mapping, team registry
persistence), promotion to a standalone submodule is the correct next step.

### Per-Worker Model Override, Not Orchestrator-Decided

The research considered having the orchestrator dynamically select model
capability based on task complexity. This requires a planning layer that does
not exist and introduces runtime non-determinism. Explicit per-agent model
binding in config is predictable, auditable, and directly maps to the existing
`ProviderFactory.create(provider, capability)` signature.

## 4. Rejected Alternatives

### Runtime Team Assembly (No Config Files)

Having the caller construct the team at API call time (passing agent
definitions as JSON in `CreateThreadRequest`) was considered. Rejected because:
(a) it exposes implementation details over the wire, (b) it prevents
workspace-local customization without code changes, and (c) it makes
team composition invisible to the UI team picker.

### Single Monolithic Config File

One `team.toml` per workspace listing all agents and teams. Rejected because
agents are reusable across teams — a `coder` agent definition should not
be duplicated inside every team file that uses it.

### CrewAI `Process.sequential` / `Process.hierarchical` Pattern

CrewAI uses a single `process=` enum on the crew to select topology. This is
superficially similar to our `topology.type` but CrewAI's process types are
rigid (sequential is strictly linear; hierarchical always uses a manager LLM).
Our `pipeline_loop` topology has no CrewAI equivalent. The explicit
`[team.topology]` table is more expressive.

## 5. Implementation Constraints

- `TeamConfig` validation must confirm that every `agent_id` in
  `[[team.workers]]` resolves to a loadable `AgentConfig` (either workspace
  or preset). This check happens at graph compilation time, not TOML parse
  time.
- `topology.order` agent IDs must be a subset of `[[team.workers]]` agent IDs.
- `topology.loop_node` must appear in `topology.order`.
- `TeamState` gains one new field: `loop_count: int` (default 0), used by the
  pipeline_loop guard. All existing checkpointed states default to `0`.
- `compile_team_graph()` new signature:

```python
def compile_team_graph(
    team_config: TeamConfig,
    agent_configs: dict[str, AgentConfig],
    checkpointer: AsyncSqliteSaver | None = None,
) -> Any:
    ...
```

The old signature (`supervisor_model`, `worker_models`) is removed. Call sites
must migrate to loading `TeamConfig` + `AgentConfig` and passing them in.

## 6. Wire Contract Impact (ADR-011 Amendment)

### `CreateThreadRequest`

```python
class CreateThreadRequest(BaseModel):
    title: str | None = None
    initial_message: str
    # NEW: select a team preset by ID
    team_preset: str | None = None       # e.g. "coding-star"
    # DEPRECATED (kept for backward compat, ignored if team_preset set):
    provider: Provider | None = None
    model: Model | None = None
```

When `team_preset` is `None`, the system falls back to the single-agent
behavior using `provider`/`model` with the built-in `solo-coder` preset.

**Note**: When `team_preset` is specified, the `provider` and `model` fields
are **ignored**. Models are defined statically in team TOML configuration
(§2.3). Per-request model overrides are not supported. To use different models,
create a custom team preset in the workspace or modify bundled presets.

### New REST Endpoint: Team Presets

```text
GET /teams  →  TeamPresetsResponse
```

```python
class TeamPresetSummary(BaseModel):
    id: str
    display_name: str
    description: str
    topology: str
    worker_count: int

class TeamPresetsResponse(BaseModel):
    presets: list[TeamPresetSummary]
```

This endpoint powers the team picker in the frontend thread creation flow.

## 7. Module Hierarchy Impact (ADR-009 Amendment)

`lib/core/` gains:

```text
lib/core/
├── team_config.py       # NEW: AgentConfig, TeamConfig Pydantic models + TOML loaders
├── presets/             # NEW: bundled default config files
│   ├── agents/
│   │   ├── planner.toml
│   │   ├── coder.toml
│   │   ├── reviewer.toml
│   │   └── analyst.toml
│   └── teams/
│       ├── coding-star.toml
│       ├── coding-pipeline.toml
│       ├── coding-loop.toml
│       └── solo-coder.toml
├── tests/
│   └── test_team_config.py   # NEW: validates TOML loading + model resolution
```

`lib/core/__init__.py` facade gains `TeamConfig`, `AgentConfig` exports.

## 8. References

- `lib/core/graph.py` — `compile_team_graph()` entry point (to be refactored)
- `lib/core/state.py` — `TeamState` TypedDict (gains `loop_count`)
- `lib/core/nodes/worker.py:64` — `create_worker_node(model, system_prompt, name)`
- `lib/core/nodes/supervisor.py` — `create_supervisor_node()` (prompt enhanced)
- `lib/providers/factory.py` — `ProviderFactory.create(provider, capability)`
- `lib/api/schemas/rest.py` — `CreateThreadRequest` (gains `team_preset`)
- LangGraph `state.py:575` — `StateGraph.add_node(name, action, metadata=...)`
- LangGraph `state.py:839` — `StateGraph.add_conditional_edges(...)`
- LangGraph `state.py:889` — `StateGraph.add_sequence(nodes)`
- LangGraph `state.py:1035` — `StateGraph.compile(interrupt_before=[...])`
- [ADR-012](012-agent-definition-schema.md) — Agent Definition Schema
- [ADR-011](011-frontend-backend-contract.md) — Frontend-Backend Wire Contract
- [ADR-009](009-approved-module-hierarchy.md) — Approved Module Hierarchy
- [ADR-008](008-orchestration-topology-pipeline.md) — Orchestration Topology & Pipeline
