---
adr_id: 012
title: Agent Definition Schema (TOML Config)
date: 2026-02-27
status: Proposed
related:
  - docs/adrs/002-llm-context-provider-abstraction.md
  - docs/adrs/008-orchestration-topology-pipeline.md
  - docs/adrs/009-approved-module-hierarchy.md
  - docs/adrs/013-team-composition-topology.md
---

# ADR-012: Agent Definition Schema (TOML Config)

**Date:** 2026-02-27
**Status:** Proposed

## 1. Context & Problem Statement

`compile_team_graph()` currently accepts raw `BaseChatModel` instances with
zero role, persona, or tool configuration. Every worker node receives an
identical hardcoded system prompt: `"You are a helpful expert assistant."`.
The supervisor routes by text-parsing worker names against a flat list — with
no capability metadata, no description, and no per-agent model selection.

The Architecture Distilled document (§1.5, §1.6 — now deprecated) originally
specified per-role personas, tool scoping, and filesystem isolation for each
agent. Both were lost in the LangGraph migration. This ADR reinstates them as
a formal, serializable config schema.

**Core problem:** An agent's identity, persona, model binding, and capability
scope are currently scattered across call-site construction code with no
canonical definition. There is no way to compose a team without writing Python.

## 2. Decision

Each logical agent role is defined by a TOML file located at:

```text
{workspace_root}/.vaultspec/agents/{agent_id}.toml
```

A set of **built-in default agent definitions** is bundled inside the package
at `lib/core/presets/agents/` and loaded as fallbacks when no workspace
override exists.

The canonical schema is a Pydantic model (`AgentConfig`) defined in
`lib/core/team_config.py`, validated via `tomllib` (stdlib Python 3.11+).

### 2.1 TOML Schema

```toml
# .vaultspec/agents/coder.toml

[agent]
id          = "coder"
display_name = "Coder"
role        = "coder"
description = """
Implements features and fixes bugs. Writes production-ready code given
a clear specification from the Planner. Always runs tests after changes.
"""

[agent.persona]
system_prompt = """
You are an expert software engineer. You receive precise task specifications
and implement them with clean, well-structured code. After every change, run
the relevant tests and report results. Do not ask clarifying questions —
act on the specification provided.
"""

[agent.model]
provider   = "claude"   # Provider enum: claude | gemini | openai | zhipu
capability = "high"     # Model enum: low | mid | high | max

[agent.capabilities]
# Maps directly to ACP _initialize_session() clientCapabilities flags
# (lib/providers/acp_chat_model.py:469)
filesystem_read  = true
filesystem_write = true
terminal         = false

[agent.permissions]
# Node names listed here map to compile(..., interrupt_before=[...])
# Populated at graph compilation time from all agents' permission lists.
require_approval_for = ["fs.writeTextFile"]
```

### 2.2 Full Field Reference

| Field                                    | Type        | Required | Description                                                                                                                                                                                       |
| ---------------------------------------- | ----------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `agent.id`                               | `str`       | Yes      | Unique identifier. Must match filename stem. Used as LangGraph node name.                                                                                                                         |
| `agent.display_name`                     | `str`       | Yes      | Human-readable name. Stored in `add_node(metadata={"display_name": ...})`.                                                                                                                        |
| `agent.role`                             | `str`       | Yes      | Semantic role enum: `planner`, `coder`, `reviewer`, `analyst`, `supervisor`, `custom`.                                                                                                            |
| `agent.description`                      | `str`       | Yes      | Plain-language description of this agent's responsibilities. Injected into the supervisor's system prompt for LLM-driven routing.                                                                 |
| `agent.persona.system_prompt`            | `str`       | Yes      | Full system prompt. Passed to `create_worker_node(model, system_prompt, name)` (worker.py:64).                                                                                                    |
| `agent.model.provider`                   | `str`       | No       | Override team default provider. Values: `claude`, `gemini`, `openai`, `zhipu`.                                                                                                                    |
| `agent.model.capability`                 | `str`       | No       | Override team default capability level. Values: `low`, `mid`, `high`, `max`.                                                                                                                      |
| `agent.model.provider_fallback`          | `list[str]` | No       | Ordered fallback provider list. If the primary provider fails or is unavailable, providers are tried in order. Same three-level override precedence as `provider`/`capability` (§2.3 in ADR-013). |
| `agent.capabilities.filesystem_read`     | `bool`      | No       | ACP `fs.readTextFile` flag (default `false`).                                                                                                                                                     |
| `agent.capabilities.filesystem_write`    | `bool`      | No       | ACP `fs.writeTextFile` flag (default `false`).                                                                                                                                                    |
| `agent.capabilities.terminal`            | `bool`      | No       | ACP `terminal` flag (default `false`).                                                                                                                                                            |
| `agent.permissions.require_approval_for` | `list[str]` | No       | ACP capability names requiring human approval. Contributes to graph `interrupt_before`.                                                                                                           |

### 2.3 Pydantic Model (`lib/core/team_config.py`)

```python
import tomllib
from pathlib import Path
from pydantic import BaseModel, Field
from ..utils.enums import Provider, Model


class AgentCapabilitiesConfig(BaseModel):
    filesystem_read: bool = False
    filesystem_write: bool = False
    terminal: bool = False


class AgentPermissionsConfig(BaseModel):
    require_approval_for: list[str] = Field(default_factory=list)


class AgentModelConfig(BaseModel):
    provider: Provider | None = None
    capability: Model | None = None
    provider_fallback: list[Provider] = Field(default_factory=list)


class AgentPersonaConfig(BaseModel):
    system_prompt: str


class AgentConfig(BaseModel):
    id: str
    display_name: str
    role: str
    description: str
    persona: AgentPersonaConfig
    model: AgentModelConfig = Field(default_factory=AgentModelConfig)
    capabilities: AgentCapabilitiesConfig = Field(default_factory=AgentCapabilitiesConfig)
    permissions: AgentPermissionsConfig = Field(default_factory=AgentPermissionsConfig)

    @classmethod
    def from_toml(cls, path: Path) -> "AgentConfig":
        with path.open("rb") as f:
            data = tomllib.load(f)
        return cls.model_validate(data["agent"])
```

### 2.4 SDK Mapping — How Each Field Becomes LangGraph Code

| TOML Field                                        | SDK API                                                                       | File:Line               |
| ------------------------------------------------- | ----------------------------------------------------------------------------- | ----------------------- |
| `agent.id`                                        | `builder.add_node(name, ...)` — node name                                     | `state.py:575`          |
| `agent.display_name`, `agent.role`                | `builder.add_node(name, action, metadata={"display_name": ..., "role": ...})` | `state.py:575`          |
| `agent.description`                               | Injected into supervisor system prompt roster                                 | `graph.py` (future)     |
| `agent.persona.system_prompt`                     | `create_worker_node(model, system_prompt, name)`                              | `worker.py:64`          |
| `agent.model.provider` + `agent.model.capability` | `ProviderFactory.create(provider, capability)`                                | `factory.py`            |
| `agent.capabilities.filesystem_read`              | `_initialize_session()` → `fs.readTextFile` flag                              | `acp_chat_model.py:469` |
| `agent.capabilities.filesystem_write`             | `_initialize_session()` → `fs.writeTextFile` flag                             | `acp_chat_model.py:469` |
| `agent.capabilities.terminal`                     | `_initialize_session()` → `terminal` flag                                     | `acp_chat_model.py:469` |
| `agent.permissions.require_approval_for`          | Aggregated across team → `builder.compile(interrupt_before=[...])`            | `state.py:1035`         |

### 2.5 Node Metadata Carrier

Agent identity fields (`display_name`, `role`, `description`) are stored as
LangGraph node metadata, **not** in `TeamState`. This avoids polluting the
serializable `TypedDict` and keeps agent identity as graph-level metadata:

```python
builder.add_node(
    agent_config.id,
    worker_node,
    metadata={
        "display_name": agent_config.display_name,
        "role": agent_config.role,
        "description": agent_config.description,
    },
)
```

The event aggregator extracts `metadata` from the compiled graph's
`StateNodeSpec` when emitting `AgentStatusEvent` and `TeamStatusEvent`.
`AgentSummary` in the wire contract (ADR-011) gains `role`, `display_name`,
and `description` fields sourced from this metadata.

### 2.6 ACP Capability Binding

`AcpChatModel._initialize_session()` currently hardcodes all ACP capability
flags to `False` (acp_chat_model.py:469). The `AgentCapabilitiesConfig` fields
map 1:1:

```python
# Before (hardcoded — current state):
"clientCapabilities": {
    "fs": {"readTextFile": False, "writeTextFile": False},
    "terminal": False,
}

# After (driven by AgentConfig):
"clientCapabilities": {
    "fs": {
        "readTextFile": agent_config.capabilities.filesystem_read,
        "writeTextFile": agent_config.capabilities.filesystem_write,
    },
    "terminal": agent_config.capabilities.terminal,
}
```

| `AcpChatModel` gains an `agent_config: AgentConfig | None = None` field. |
`compile_team_graph()` injects the config when constructing each model
via `ProviderFactory`.

### 2.7 Built-in Preset Agents

The following agent definitions ship as package defaults in
`lib/core/presets/agents/`:

| File            | Role       | Capabilities                                                       |
| --------------- | ---------- | ------------------------------------------------------------------ |
| `planner.toml`  | `planner`  | `filesystem_read=true`, `terminal=false`, `filesystem_write=false` |
| `coder.toml`    | `coder`    | `filesystem_read=true`, `filesystem_write=true`, `terminal=false`  |
| `reviewer.toml` | `reviewer` | `filesystem_read=true`, `filesystem_write=false`, `terminal=false` |
| `analyst.toml`  | `analyst`  | `filesystem_read=true`, `filesystem_write=false`, `terminal=false` |

Workspace-local files at `.vaultspec/agents/{id}.toml` shadow preset defaults.

### 2.8 Config Discovery Order

```text
1. {workspace_root}/.vaultspec/agents/{agent_id}.toml   (workspace override)
2. lib/core/presets/agents/{agent_id}.toml               (bundled default)
3. Raise AgentConfigNotFoundError                         (fail fast)
```

## 3. Rationale

### Why TOML?

TOML is the Python stdlib default for config since 3.11 (`tomllib`). It is
expressive enough for nested structures, has unambiguous multiline string
syntax (essential for system prompts), and requires zero third-party
dependencies. YAML introduces ambiguity (Norway problem). JSON prohibits
comments. Both are inferior for human-authored config files.

### Why Agent-Metadata-on-Node, Not TeamState?

`StateNodeSpec.metadata` (langgraph `_node.py:87`) is the LangGraph-native
carrier for static per-node information. Adding `role`/`display_name` to
`TeamState` would require every node update to include these redundant fields,
pollute the SQLite checkpointer schema, and couple identity to the mutable
message-passing channel — semantically wrong.

### Why Capability-Level Model Binding?

`Model` enum values (`LOW`, `MID`, `HIGH`, `MAX`) abstract concrete model
version strings (ADR-002 §3, `utils/enums.py`). Agents declare a capability
level, not a model version. This insulates agent TOML files from model
churn — when `claude-4.6-sonnet` becomes `claude-5-sonnet`, only `MODEL_MAP`
changes, not every agent file.

### Why Per-Agent ACP Flags Over Tool-Level Filtering?

ACP capability flags are negotiated during session initialization (a single
JSON-RPC `initialize` call at subprocess startup). This is the correct
interception point — before the LLM even receives its first prompt. Filtering
at the graph level (post-generation) would require parsing the LLM's tool-call
output after the fact, introducing race conditions and making the permission
model harder to reason about.

## 4. Rejected Alternatives

### Python Dict / TypedDict Agent Definitions (DeepAgents Pattern)

DeepAgents passes `SubAgent` `TypedDict`s directly in Python code:
`create_deep_agent(subagents=[{name: "coder", system_prompt: "..."}])`.
This is ergonomic for library authors, but for Vaultspec, agent definitions
must be user-editable without writing Python. TOML files allow non-developer
users to customize personas and capability scopes.

### A2A AgentCard (HTTP Discovery)

A2A's `AgentCard` at `/.well-known/agent.json` is designed for external HTTP
discovery of independently-deployed agent services. Our agents are compiled
LangGraph nodes inside a single process — HTTP discovery adds network overhead
and protocol complexity with zero benefit.

### Embedding Config in TeamState

Adding `agent_roster: dict[str, AgentConfig]` to `TeamState` would break the
SQLite checkpointer (Pydantic models are not JSON-serializable by default) and
conflates immutable configuration with mutable execution state.

## 5. Implementation Constraints

- `AgentConfig` must be fully validated before `compile_team_graph()` is
  called. Invalid TOML raises `pydantic.ValidationError` at startup, not
  at runtime.
- `agent.id` must be a valid Python identifier (no spaces, no hyphens) since
  it becomes a LangGraph node name.
- `AcpChatModel` must remain backward-compatible: `agent_config=None` must
  produce the current hardcoded-`False` behavior for all ACP capability flags.
- System prompts in TOML are loaded verbatim — no interpolation, no template
  variables for v1.

## 6. Wire Contract Impact (ADR-011 Amendment)

The following fields are added to ADR-011 schemas:

**`AgentSummary`** (used in `TeamStatusEvent` and `TeamStatusResponse`):

```python
class AgentSummary(BaseModel):
    agent_id: str
    node_name: str
    state: AgentLifecycleState
    provider: Provider
    model: Model
    # NEW:
    role: str
    display_name: str
    description: str
```

Source: node metadata extracted from `compiled_graph.nodes[node_name].metadata`
at aggregator emit time.

## 7. References

- `lib/core/graph.py` — current `compile_team_graph()` entry point
- `lib/core/nodes/worker.py:64` — `create_worker_node(model, system_prompt, name)`
- `lib/providers/acp_chat_model.py:469` — `_initialize_session()` ACP flags
- `lib/providers/factory.py` — `ProviderFactory.create(provider, capability)`
- `lib/utils/enums.py` — `Provider`, `Model`, `MODEL_MAP`
- LangGraph `state.py:575` — `StateGraph.add_node(name, action, metadata=...)`
- LangGraph `_node.py:87` — `StateNodeSpec.metadata`
- LangGraph `state.py:1035` — `compile(interrupt_before=[...])`
- [ADR-013](013-team-composition-topology.md) — Team Composition & Topology
- [ADR-009](009-approved-module-hierarchy.md) — Approved Module Hierarchy
