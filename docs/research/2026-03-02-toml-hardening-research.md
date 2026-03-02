# TOML Team Configuration Enhancement — Research

**Date**: 2026-03-02
**Author**: docs-researcher (langgraph-hardening team)
**Task**: TOML-R (Task 43)
**Status**: Complete

---

## Executive Summary

This document covers five research scopes for hardening the TOML-based team configuration system:

1. **Naming** — Professional, function-descriptive names for the 4 built-in presets
2. **Model Fallback Chain** — TOML schema + implementation path for provider failover
3. **Permissions / Auto-Approve** — TOML-level `auto_approve` flag and code paths
4. **Persona Definitions** — Team-level `[team.persona]` block proposal
5. **LangGraph / Protocol Exposure** — Schema features not yet surfaced in TOML

---

## Scope 1 — Naming

### Current State

The four built-in presets use topology-descriptive IDs:

| File | Current ID | Current display_name |
|------|-----------|---------------------|
| `coding-star.toml` | `coding-star` | `Coding Star Team` |
| `coding-pipeline.toml` | `coding-pipeline` | `Coding Pipeline Team` |
| `coding-loop.toml` | `coding-loop` | `Coding Loop Team` |
| `solo-coder.toml` | `solo-coder` | `Solo Coder` |

These names expose internal topology implementation details (`star`, `pipeline`, `loop`) rather than communicating the team's functional purpose to an end user.

ADR-013 §2.9 lists these as "built-in presets" but provides no naming convention.

### Problems

- `coding-star` tells a user nothing about *why* they would choose this preset
- `coding-loop` vs `coding-pipeline` requires knowledge of LangGraph topologies to differentiate
- No namespace prefix — the `solo-coder` ID could collide with user-defined presets
- `display_name` values are nearly identical to the IDs (just title-cased topology labels)

### Recommended Names

The naming convention should follow: `vaultspec-{function}-{qualifier}` where function describes the workflow purpose and qualifier differentiates teams operating similarly.

| Current ID | Proposed ID | Proposed display_name | Rationale |
|-----------|------------|----------------------|-----------|
| `coding-star` | `vaultspec-adaptive-coder` | `Vaultspec Adaptive Coder` | Star topology supervisor dynamically routes — adaptive routing |
| `coding-pipeline` | `vaultspec-structured-coder` | `Vaultspec Structured Coder` | Fixed pipeline — predictable, structured flow |
| `coding-loop` | `vaultspec-iterative-coder` | `Vaultspec Iterative Coder` | Review loop — iterative refinement until acceptance |
| `solo-coder` | `vaultspec-solo-coder` | `Vaultspec Solo Coder` | Single worker — minimal, direct execution |

### Description Field

Each preset should have a `description` field (the field exists in `TeamConfig` but is absent from all 4 current preset files). Recommended descriptions:

```toml
# vaultspec-adaptive-coder
description = """
Supervisor-driven team with dynamic routing. The Grand Architect supervisor
dispatches to a planner, high-capacity coder, and reviewer as needed.
Best for open-ended tasks where the optimal sequence is not known upfront.
"""

# vaultspec-structured-coder
description = """
Fixed pipeline: planner → coder → reviewer. Predictable, auditable flow
with no dynamic routing. Best for well-defined tasks with clear acceptance
criteria.
"""

# vaultspec-iterative-coder
description = """
Pipeline with a review loop: planner → coder → reviewer, looping back
to the coder up to 3 times until the reviewer approves. Best for tasks
requiring quality assurance before delivery.
"""

# vaultspec-solo-coder
description = """
Single coder worker, no supervisor. Minimal overhead for simple,
self-contained tasks. Fastest to spin up; no planning or review phase.
"""
```

### Migration

The `id` field is used as the `team_preset` column in the database and in `DispatchRequest`. A rename requires either:
1. A DB migration adding the new IDs (both old and new resolve via `load_team_config`)
2. A compatibility shim in `load_team_config()` that maps old IDs → new TOML files

Option 2 is lower risk: keep the old `.toml` files as symlinks or thin wrappers delegating to the new files. This preserves existing thread records without a schema migration.

---

## Scope 2 — Model Fallback Chain

### Current State

**`lib/core/team_config.py`** — `TeamDefaultsConfig`:
```python
class TeamDefaultsConfig(BaseModel):
    provider: Provider = Provider.CLAUDE
    capability: ModelCapability = ModelCapability.STANDARD
```

No `provider_fallback` list. The `ModelConfig` used in `WorkerRef` and `AgentConfig` similarly has no fallback list.

**`lib/core/graph.py`** — `_resolve_model_for_worker()` (single-pass):
```python
provider = (
    worker_ref.model.provider
    or agent_config.model.provider
    or team_config.defaults.provider
    or Provider.CLAUDE
)
# ... single ProviderFactory.create(provider, ...) call — raises ValueError on failure
```

**`lib/providers/factory.py`** — `ProviderFactory.create()`:
```python
def create(self, provider: Provider, ...) -> BaseChatModel:
    if provider == Provider.CLAUDE:
        if not (self._settings.anthropic_api_key or self._settings.claude_code_oauth_token):
            raise ValueError("No Anthropic credentials found")
        ...
    elif provider == Provider.GEMINI:
        ...
    else:
        raise ValueError(f"Unsupported provider: {provider}")
```

Raises `ValueError` immediately. No retry, no fallback.

### Proposed TOML Schema

Add `provider_fallback` at the `[team.defaults]` level:

```toml
[team.defaults]
provider = "claude"
capability = "standard"
provider_fallback = ["gemini", "openai"]   # NEW: ordered fallback list
```

Also add at per-worker `[model]` level (within `[[team.workers]]`):

```toml
[[team.workers]]
name = "coder"
agent = "coder"

  [team.workers.model]
  provider = "claude"
  capability = "high"
  provider_fallback = ["gemini"]            # NEW: worker-level override
```

### Pydantic Schema Changes

**`lib/core/team_config.py`**:
```python
class TeamDefaultsConfig(BaseModel):
    provider: Provider = Provider.CLAUDE
    capability: ModelCapability = ModelCapability.STANDARD
    provider_fallback: list[Provider] = Field(default_factory=list)  # NEW

class ModelConfig(BaseModel):
    provider: Provider | None = None
    capability: ModelCapability | None = None
    name: str | None = None
    provider_fallback: list[Provider] = Field(default_factory=list)  # NEW
```

### Implementation Path in `_resolve_model_for_worker()`

```python
def _resolve_model_for_worker(...) -> BaseChatModel:
    primary_provider = (
        worker_ref.model.provider
        or agent_config.model.provider
        or team_config.defaults.provider
        or Provider.CLAUDE
    )
    # Build fallback chain: worker override > defaults > empty
    fallback_chain = (
        worker_ref.model.provider_fallback
        or agent_config.model.provider_fallback
        or team_config.defaults.provider_fallback
        or []
    )
    providers_to_try = [primary_provider, *fallback_chain]
    last_exc: Exception | None = None
    for provider in providers_to_try:
        try:
            return factory.create(provider, capability, model_name)
        except ValueError as exc:
            _logger.warning(
                "Provider %s unavailable for worker %s: %s — trying next",
                provider, worker_ref.name, exc,
            )
            last_exc = exc
    raise ValueError(
        f"All providers exhausted for worker {worker_ref.name}: "
        f"{providers_to_try}"
    ) from last_exc
```

### ADR Impact

ADR-012 §3 (model block) and ADR-013 §2.3 (model resolution precedence) need amendments to document:
1. `provider_fallback` field addition
2. Fallback inheritance rules (worker override > team defaults)
3. Logging behavior on fallback

---

## Scope 3 — Permissions / Auto-Approve

### Current State

**`autonomous` flag flow** (traced through codebase):
```
CreateThreadRequest.autonomous: bool = False
  → POST /threads endpoint
    → DispatchRequest(autonomous=req.autonomous)
      → worker executor._handle_ingest()
        → compile_team_graph(autonomous=autonomous)
          → _compile_star_graph() / _compile_pipeline_graph() / _compile_pipeline_loop_graph()
            → create_worker_node(model, prompt, name, autonomous=autonomous)
              → if not autonomous and hasattr(model, "permission_callback"):
                    effective_model = model.model_copy(
                        update={"permission_callback": _interrupt_permission_callback}
                    )
```

`interrupt_before=[]` always — the interrupt mechanism is the `interrupt()` call inside `worker_node`, not pre-node graph pauses.

**`AgentPermissionsConfig`** (ADR-012 §6, `lib/core/team_config.py`):
```python
class AgentPermissionsConfig(BaseModel):
    require_approval_for: list[str] = Field(default_factory=list)
```

ADR-013 §2.7 states that `require_approval_for` populates `interrupt_before` at compile time — but the actual code uses `interrupt_before=[]` always. This is an ADR-013 violation that was intentionally superseded during the autonomous mode implementation sprint (per MEMORY.md: "interrupt_before=[] always — this is a hard architectural decision, overriding ADR-013 §2.7").

The `require_approval_for` field exists in the schema but has no runtime effect.

### Problems

1. No TOML-level way to declare that a team should default to headless/autonomous mode
2. `require_approval_for` is dead code — populated from TOML but never consumed
3. Users must pass `autonomous=true` in every `CreateThreadRequest` for headless teams
4. ADR-013 §2.7 documents a code path that does not exist

### Proposed TOML Schema

Add `[team.permissions]` block:

```toml
[team.permissions]
auto_approve = true           # NEW: team defaults to autonomous mode
                              # Overridden per-request by CreateThreadRequest.autonomous
```

### Pydantic Schema Changes

**New `TeamPermissionsConfig`** in `lib/core/team_config.py`:
```python
class TeamPermissionsConfig(BaseModel):
    auto_approve: bool = False           # default: supervised
    require_approval_for: list[str] = Field(default_factory=list)  # reserved (future)
```

**Updated `TeamConfig`**:
```python
class TeamConfig(BaseModel):
    ...
    permissions: TeamPermissionsConfig = Field(default_factory=TeamPermissionsConfig)
```

### Endpoint Integration

In `POST /threads` endpoint (`lib/api/endpoints.py`), after loading `TeamConfig`:
```python
team_config = load_team_config(req.team_preset)
# If the team declares auto_approve, use it as the default.
# An explicit autonomous field in the request body overrides the team default.
effective_autonomous = (
    req.autonomous
    if req.autonomous is not None          # explicit override
    else team_config.permissions.auto_approve  # team default
)
```

This requires `CreateThreadRequest.autonomous` to become `bool | None` (currently `bool = False`). `None` means "use team default"; `False` means "supervised even if team default is auto_approve".

### Dead Code Cleanup

`AgentPermissionsConfig.require_approval_for` should either:
- Be removed if ADR-013 §2.7 is officially superseded
- Be documented as "reserved for future use" with a comment
- Be wired up (not recommended — adds complexity, interrupt_before=[] is an intentional architectural decision)

Recommendation: add a `# NOTE: interrupt_before=[] always; this field is reserved` comment and update ADR-013 §2.7 to reflect the actual implementation.

### `vaultspec-solo-coder` Preset Recommendation

The solo-coder preset has no supervisor, minimal overhead, and is most likely to be used in headless scripts. Recommend:

```toml
# solo-coder.toml (or vaultspec-solo-coder.toml)
[team.permissions]
auto_approve = true    # solo-coder is headless by default
```

---

## Scope 4 — Persona Definitions

### Current State

**`lib/core/presets/agents/supervisor.toml`**:
```toml
[agent]
id = "supervisor"
display_name = "Grand Architect"
role = "supervisor"

[agent.persona]
system_prompt = """
You are Grand Architect, an expert software engineering team supervisor...
{{AGENT_ROSTER}}
...routing instructions...
...vaultspec pipeline docs...
"""
```

**`lib/core/graph.py`** — `_build_supervisor_prompt()`:
```python
def _build_supervisor_prompt(team_config: TeamConfig, agent_config: AgentConfig) -> str:
    roster = _build_agent_roster(team_config)
    base = agent_config.persona.system_prompt
    if "{{AGENT_ROSTER}}" in base:
        return base.replace("{{AGENT_ROSTER}}", roster)
    return base + "\n\n" + roster
```

The supervisor persona is entirely defined in `supervisor.toml`. There is no mechanism for a team TOML to inject team-specific behavioral directives into the supervisor prompt.

**Problems**:
- `vaultspec-adaptive-coder` and `vaultspec-iterative-coder` should give different routing guidance to their supervisors
- Currently every team gets the exact same supervisor prompt regardless of topology
- No way to specialize the supervisor's persona (e.g., "for this team, prioritize review quality over speed")

### Proposed TOML Schema

Add `[team.persona]` block:

```toml
[team.persona]
# Injected into the supervisor system prompt as a team-specific behavioral directive.
# Inserted after the agent roster. Supports plain text or markdown.
directive = """
This team operates in iterative mode. When the reviewer requests changes,
route back to the coder. Accept output only when the reviewer explicitly
marks the task APPROVED. Prioritize correctness over speed — loop up to
3 times before escalating.
"""
```

Also add an optional `supervisor_display_name` override:
```toml
[team.persona]
supervisor_display_name = "Quality Arbiter"   # overrides supervisor.toml display_name for this team
directive = "..."
```

### Pydantic Schema Changes

**New `TeamPersonaConfig`** in `lib/core/team_config.py`:
```python
class TeamPersonaConfig(BaseModel):
    directive: str | None = None
    supervisor_display_name: str | None = None
```

**Updated `TeamConfig`**:
```python
class TeamConfig(BaseModel):
    ...
    persona: TeamPersonaConfig = Field(default_factory=TeamPersonaConfig)
```

### Implementation in `_build_supervisor_prompt()`

```python
def _build_supervisor_prompt(team_config: TeamConfig, agent_config: AgentConfig) -> str:
    roster = _build_agent_roster(team_config)
    base = agent_config.persona.system_prompt

    # Inject roster
    if "{{AGENT_ROSTER}}" in base:
        prompt = base.replace("{{AGENT_ROSTER}}", roster)
    else:
        prompt = base + "\n\n" + roster

    # Inject team-level directive if present
    if team_config.persona.directive:
        prompt = prompt + "\n\n## Team Directive\n\n" + team_config.persona.directive

    return prompt
```

### Display Name Override

In `_build_agent_roster()` or wherever the supervisor's `display_name` is referenced:
```python
supervisor_name = (
    team_config.persona.supervisor_display_name
    or agent_config.display_name
    or "Supervisor"
)
```

### Recommended Directives per Preset

**`vaultspec-adaptive-coder`**:
```
Route dynamically based on task needs. You may skip the planning phase
for simple tasks. Use the reviewer only when correctness is uncertain.
```

**`vaultspec-structured-coder`**:
```
Always route planner → coder → reviewer in strict sequence. Do not skip
phases. Each agent must complete before the next begins.
```

**`vaultspec-iterative-coder`**:
```
Route planner → coder → reviewer. If the reviewer requests changes, route
back to the coder. Accept output only when the reviewer explicitly outputs
APPROVED. Maximum iterations: 3.
```

**`vaultspec-solo-coder`**: No supervisor, no directive needed.

---

## Scope 5 — LangGraph / Protocol Exposure

### Currently Exposed in TOML

From ADR-013 and the existing preset files:

| Feature | TOML field | Location |
|---------|-----------|----------|
| Topology | `[team.topology] type` | `TeamConfig` |
| Pipeline order | `[team.topology] order` | `PipelineConfig` |
| Loop node | `[team.topology] loop_node` | `PipelineLoopConfig` |
| Max loops | `[team.topology] max_loops` | `PipelineLoopConfig` |
| Provider | `[team.defaults] provider` | `TeamDefaultsConfig` |
| Capability | `[team.defaults] capability` | `TeamDefaultsConfig` |
| Worker model | `[[team.workers]] [model]` | `WorkerRef.model` |

### Not Yet Exposed — Gap Analysis

#### 1. `step_timeout` / `graph_node_timeout_seconds`

**Current**: `settings.graph_node_timeout_seconds = 300` (global, from env var only).

**Graph wiring** (`lib/core/graph.py`):
```python
compiled = graph.compile(
    checkpointer=checkpointer,
    interrupt_before=[],
).with_config({"step_timeout": settings.graph_node_timeout_seconds})
```

`step_timeout` is a Pregel-level config — it limits per-node execution time. Currently only configurable globally via env var.

**Proposed TOML**:
```toml
[team.graph]
step_timeout_seconds = 120    # per-node timeout; overrides global settings value
```

**Implementation**: Pass through `TeamConfig.graph.step_timeout_seconds` to `compiled.with_config()` in `compile_team_graph()`.

#### 2. `recursion_limit`

**Current**: `settings.graph_node_timeout_seconds` covers node timeout but `recursion_limit` (max supersteps) is not exposed. LangGraph default is 25.

**Proposed TOML**:
```toml
[team.graph]
recursion_limit = 50    # max supersteps; default 25 in LangGraph
```

**Implementation**: `compiled.with_config({"recursion_limit": team_config.graph.recursion_limit})`.

#### 3. `RetryPolicy`

**Current**: No retry policy wired. `_resolve_model_for_worker` raises on first failure.

**Proposed TOML**:
```toml
[team.graph]
retry_on_exception = true       # enable RetryPolicy on graph nodes
max_attempts = 3                # RetryPolicy(max_attempts=3)
retry_on_timeout = true         # retry on asyncio.TimeoutError
```

**Implementation** (`lib/core/graph.py`):
```python
from langgraph.pregel import RetryPolicy

retry_policy: RetryPolicy | None = None
if team_config.graph.retry_on_exception:
    retry_policy = RetryPolicy(
        max_attempts=team_config.graph.max_attempts,
        retry_on=(asyncio.TimeoutError,) if team_config.graph.retry_on_timeout else (Exception,),
    )
# Then pass to graph.add_node(..., retry=retry_policy)
```

Note: RetryPolicy is attached per-node at `add_node()` time, not at `compile()`. This means `team_config.graph` settings must be threaded into `_compile_*_graph()` functions.

#### 4. `thread_id_prefix`

**Current**: Thread IDs are UUIDs. No namespace prefix.

**Proposed TOML**:
```toml
[team]
thread_id_prefix = "vs-adaptive-"    # prepended to UUID for readable thread IDs
```

Low priority — thread IDs are internal. Cosmetic only.

#### 5. `interrupt_before` (dead code reconciliation)

**Current**: `interrupt_before=[]` always. ADR-013 §2.7 documents `require_approval_for` populating `interrupt_before`. This is dead code.

**Recommendation**: Do NOT expose `interrupt_before` in TOML. The `interrupt()` mechanism inside `worker_node` is the correct architectural pattern. Update ADR-013 §2.7 to explicitly document this supersession. Remove `require_approval_for` from `AgentPermissionsConfig` or keep with a clear deprecation comment.

#### 6. Subgraph Isolation (`checkpointer=None`)

**Current**: All nodes share the team graph checkpointer. Subgraph isolation (passing `checkpointer=None` to inner compiled graphs) is not used.

**Not applicable for TOML**: This is an implementation detail, not a user-configurable option.

### Proposed `[team.graph]` Block (Consolidated)

```toml
[team.graph]
step_timeout_seconds = 300     # per-node execution timeout (seconds); default: global setting
recursion_limit = 25           # max LangGraph supersteps; default: 25
retry_on_exception = false     # enable RetryPolicy on worker nodes
max_attempts = 3               # RetryPolicy max_attempts (only if retry_on_exception=true)
```

### Pydantic Schema Changes

**New `TeamGraphConfig`** in `lib/core/team_config.py`:
```python
class TeamGraphConfig(BaseModel):
    step_timeout_seconds: int | None = None     # None → use global settings value
    recursion_limit: int = 25
    retry_on_exception: bool = False
    max_attempts: int = 3
```

**Updated `TeamConfig`**:
```python
class TeamConfig(BaseModel):
    ...
    graph: TeamGraphConfig = Field(default_factory=TeamGraphConfig)
```

---

## Implementation Priority

| Change | Risk | Effort | Priority |
|--------|------|--------|----------|
| Rename preset IDs (with compat shim) | LOW | LOW | HIGH |
| Add `description` to all presets | LOW | LOW | HIGH |
| `[team.permissions] auto_approve` | MEDIUM | MEDIUM | HIGH |
| `[team.persona] directive` | LOW | LOW | MEDIUM |
| `[team.graph] step_timeout_seconds` | LOW | LOW | MEDIUM |
| `[team.graph] recursion_limit` | LOW | LOW | MEDIUM |
| `provider_fallback` chain | MEDIUM | MEDIUM | MEDIUM |
| `[team.graph] retry_on_exception` | MEDIUM | HIGH | LOW |
| Dead code: `require_approval_for` | LOW | LOW | LOW |
| ADR-013 §2.7 amendment | LOW | LOW | HIGH |

---

## Files Requiring Changes

### TOML Presets
- `lib/core/presets/teams/coding-star.toml` → rename + add `[team.permissions]`, `[team.persona]`, `[team.graph]`
- `lib/core/presets/teams/coding-pipeline.toml` → same
- `lib/core/presets/teams/coding-loop.toml` → same (+ `auto_approve = false`, directive for loop guidance)
- `lib/core/presets/teams/solo-coder.toml` → same (+ `auto_approve = true`)

### Python Schema
- `lib/core/team_config.py` — add `TeamPermissionsConfig`, `TeamPersonaConfig`, `TeamGraphConfig`; update `TeamConfig`

### Core Graph
- `lib/core/graph.py` — `_build_supervisor_prompt()` (persona directive injection), `_resolve_model_for_worker()` (fallback chain), `compile_team_graph()` (step_timeout, recursion_limit from team config)

### API Endpoint
- `lib/api/endpoints.py` — `CreateThreadRequest.autonomous: bool | None = None`, team default resolution

### ADRs
- `docs/adrs/012-agent-definition-schema.md` — add `provider_fallback` to model block
- `docs/adrs/013-team-composition-topology.md` — add new blocks (`[team.permissions]`, `[team.persona]`, `[team.graph]`), amend §2.7 to supersede `interrupt_before` approach, add `provider_fallback`

---

## References

- `lib/core/team_config.py` — Pydantic models for all TOML config
- `lib/core/presets/teams/*.toml` — all 4 built-in preset files
- `lib/core/presets/agents/supervisor.toml` — supervisor persona template
- `lib/core/graph.py` — `_resolve_model_for_worker()`, `_build_supervisor_prompt()`, `compile_team_graph()`
- `lib/providers/factory.py` — `ProviderFactory.create()` (raises on failure)
- `docs/adrs/012-agent-definition-schema.md` — agent TOML schema
- `docs/adrs/013-team-composition-topology.md` — team TOML schema, §2.3 model resolution, §2.7 interrupt_before, §2.9 preset list
