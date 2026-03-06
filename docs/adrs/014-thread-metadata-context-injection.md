---
adr_id: 014
title: Thread Metadata & Context Injection
date: 2026-02-28
status: Proposed
related:
  - docs/adrs/008-orchestration-topology-pipeline.md
  - docs/adrs/011-frontend-backend-contract.md
  - docs/adrs/012-agent-definition-schema.md
  - docs/adrs/013-team-composition-topology.md
---

# ADR-014: Thread Metadata & Context Injection

**Date:** 2026-02-28
**Status:** Proposed

## 1. Context & Problem Statement

Every `POST /threads` compiles a new graph instance from a team preset
(ADR-013). Each thread is identified by an opaque UUID, receives a bare
`initial_message`, and carries zero provenance information. There are six
concrete gaps:

| Gap                            | Current State                                                                                                                                | Impact                                                                                                                                                                                                                                                           |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **No human-readable identity** | Thread IDs are UUIDs (`a3f2...`).                                                                                                            | Unusable in the UI sidebar — users cannot distinguish threads at a glance.                                                                                                                                                                                       |
| **No source repository**       | Not tracked.                                                                                                                                 | When the orchestrator serves multiple repos, there is no way to attribute a thread to a project.                                                                                                                                                                 |
| **No source branch**           | Not tracked.                                                                                                                                 | No way to correlate a thread with a feature branch. CI traceability is broken.                                                                                                                                                                                   |
| **No caller identification**   | Not tracked.                                                                                                                                 | Cannot distinguish whether Claude CLI, Gemini CLI, the REST API, or the MCP bridge initiated the work.                                                                                                                                                           |
| **No feature tag**             | Not tracked.                                                                                                                                 | The vaultspec SDD pipeline mandates a `feature_tag` that groups all research, ADR, plan, and execution documents. Agents reference `.vault/{stage}/yyyy-mm-dd-<feature>-*` paths in their system prompts but have no mechanism to receive the `<feature>` value. |
| **No workspace binding**       | `Settings.workspace_root` exists but is never threaded from the endpoint to `load_team_config()`, `load_agent_config()`, or the ACP session. | Workspace-local TOML overrides (ADR-012 §2.8, ADR-013 §2.8) are dead code. Agents cannot resolve `.vault/` paths to real filesystem locations.                                                                                                                   |

The net effect: agents are launched into a vacuum. The supervisor's system
prompt says "check `.vault/` for existing artifacts" but the agent has no
idea _which_ workspace, _which_ feature, or _which_ documents are relevant.

### 1.1 The Vaultspec SDD Pipeline

The target workflow is:

```text
Feature Request
    │
    ├─ Research   → .vault/research/yyyy-mm-dd-<feature>-<phase>-research.md
    ├─ ADR        → .vault/adrs/nnn-<feature>.md
    ├─ Plan       → .vault/plan/yyyy-mm-dd-<feature>-<phase>-plan.md
    └─ Execute    → .vault/exec/yyyy-mm-dd-<feature>/yyyy-mm-dd-<feature>-<phase>-<step>.md
                  → .vault/exec/yyyy-mm-dd-<feature>/yyyy-mm-dd-<feature>-review.md
```

Every document in the pipeline carries a YAML frontmatter `tags:` field:

```yaml
tags: ['#plan', '#auth-flow']
```

The `feature_tag` (e.g., `auth-flow`) is the grouping key. All four agent
presets (supervisor, planner, coder, reviewer) reference this convention in
their system prompts but receive no runtime binding to a concrete value.

## 2. Decision

### 2.1 ThreadMetadata Model

A new Pydantic model captures all provenance and context information at
thread creation time:

```python
from pydantic import BaseModel, Field


class ContextRef(BaseModel):
    """Reference to a context document in the .vault hierarchy."""

    path: str                   # Relative to workspace_root.
                                # e.g. ".vault/research/2026-02-28-auth-research.md"
    stage: str                  # "research" | "adr" | "plan" | "exec"
    summary: str = ""           # Optional one-line summary for the context preamble.


class ThreadMetadata(BaseModel):
    """Provenance and context attached to an orchestration thread."""

    # --- Identity ---
    nickname: str               # Human-friendly name. Unique per orchestrator instance.
                                # e.g. "auth-flow-star-a3f2"

    # --- Provenance ---
    workspace_root: str         # Absolute path to the source workspace.
                                # e.g. "Y:/code/vaultspec-worktrees/main"
    source_repo: str = ""       # Repository URL or local identifier.
                                # e.g. "github.com/org/vaultspec"
    source_branch: str = ""     # Branch name. e.g. "feat/auth-flow"
    callee: str = ""            # Initiating client. Values: "claude-cli",
                                # "gemini-cli", "api", "mcp-bridge", or custom.

    # --- SDD Pipeline Context ---
    feature_tag: str = ""       # Groups all .vault documents for this feature.
                                # e.g. "auth-flow". Maps to #<feature> in frontmatter tags.
    context_refs: list[ContextRef] = Field(default_factory=list)
                                # Explicit document references. Auto-discovery (§2.4)
                                # populates this if the caller provides only feature_tag.
```

### 2.2 CreateThreadRequest Amendment

```python
class CreateThreadRequest(BaseModel):
    title: str | None = None
    initial_message: str
    team_preset: str | None = None

    # NEW (ADR-014):
    metadata: ThreadMetadata | None = None

    # DEPRECATED (ADR-013 §6 — kept for backward compat):
    provider: Provider | None = None
    model: Model | None = None
```

When `metadata` is `None`, the orchestrator operates in legacy mode —
identical to today's behaviour (no context injection, no workspace binding,
UUID-only identity).

When `metadata` is provided:

1. `metadata.workspace_root` is threaded to `load_team_config()` and
   `load_agent_config()`, enabling workspace-local TOML overrides.
2. `metadata.feature_tag` triggers auto-discovery of `.vault/` documents
   (§2.4) if `metadata.context_refs` is empty.
3. `metadata.nickname` is stored in the DB for UI display.
4. A **context preamble** SystemMessage is injected into the graph input
   (§2.3).

### 2.3 Context Preamble Injection

A `SystemMessage` is prepended to the graph input's message list at thread
creation time. It gives every agent in the graph awareness of the project
context without modifying system prompts or graph compilation:

```python
# In create_thread_endpoint, after auto-discovery:
preamble_parts = [
    f"## Project Context",
    f"- **Workspace:** {metadata.workspace_root}",
    f"- **Feature:** {metadata.feature_tag}",
]

if metadata.source_repo:
    preamble_parts.append(f"- **Repository:** {metadata.source_repo}")
if metadata.source_branch:
    preamble_parts.append(f"- **Branch:** {metadata.source_branch}")

if metadata.context_refs:
    preamble_parts.append("\n## Available Context Documents")
    preamble_parts.append(
        "The following documents are available in the workspace. "
        "Read them as needed using your filesystem capabilities."
    )
    for ref in metadata.context_refs:
        line = f"- **[{ref.stage}]** `{ref.path}`"
        if ref.summary:
            line += f" — {ref.summary}"
        preamble_parts.append(line)

preamble = "\n".join(preamble_parts)

graph_input = {
    "messages": [
        SystemMessage(content=preamble),
        HumanMessage(content=body.initial_message),
    ]
}
```

**Why a SystemMessage in graph_input, not a template variable in TOML?**

ADR-012 §5 explicitly constrains: _"System prompts in TOML are loaded
verbatim — no interpolation, no template variables for v1."_ The context
preamble lives in the message stream, not the system prompt, which:

- Preserves ADR-012's constraint.
- Persists through LangGraph checkpointing (it is a regular message).
- Survives `compact_context()` — the compaction algorithm preserves all
  leading `SystemMessage` instances before the first non-system message.
- Is visible to every node in the graph via `state["messages"]`.
- Does not require changes to `create_worker_node()` or
  `create_supervisor_node()`.

**Message ordering inside a node's `ainvoke()` call:**

```text
[1] SystemMessage(content=system_prompt)     ← from TOML, prepended by worker_node/supervisor_node
[2] SystemMessage(content=context_preamble)  ← from graph_input, first in state["messages"]
[3] HumanMessage(content=initial_message)    ← from graph_input, second in state["messages"]
[4..] ...subsequent messages...              ← from prior node outputs
```

The role definition (TOML) sits above the project context (preamble) which
sits above the conversation. This is the correct priority ordering for LLM
attention.

### 2.4 Auto-Discovery of `.vault` Documents

When `metadata.feature_tag` is set but `metadata.context_refs` is empty,
the endpoint scans the workspace for matching documents using the naming
convention from the SDD pipeline:

```python
import glob
from pathlib import Path


def discover_context_refs(
    workspace_root: Path,
    feature_tag: str,
) -> list[ContextRef]:
    """Scan .vault/ for documents matching the feature tag."""
    refs: list[ContextRef] = []
    stage_patterns: dict[str, str] = {
        "research": ".vault/research/*{tag}*.md",
        "adr":      ".vault/adrs/*{tag}*.md",
        "plan":     ".vault/plan/*{tag}*.md",
        "exec":     ".vault/exec/*{tag}*/**/*.md",
    }
    for stage, pattern in stage_patterns.items():
        resolved = pattern.replace("{tag}", feature_tag)
        for match in sorted(workspace_root.glob(resolved)):
            refs.append(ContextRef(
                path=str(match.relative_to(workspace_root)),
                stage=stage,
            ))
    return refs
```

Discovery is filename-based (glob), not content-based (no YAML frontmatter
parsing). This is O(1) filesystem calls per stage pattern — fast enough for
synchronous execution in the endpoint handler.

**When `context_refs` is explicitly provided:** auto-discovery is skipped.
The caller's explicit list takes precedence. This allows callers to:

- Include documents outside the `.vault/` hierarchy.
- Exclude irrelevant documents that happen to match the feature tag.
- Reference documents from a prior feature (cross-feature context).

### 2.5 ThreadModel Amendment (DB Schema)

`ThreadModel` gains a `metadata` column to persist `ThreadMetadata` as
serialized JSON. The existing unused `agent_config` column is repurposed
as `metadata`:

```python
class ThreadModel(Base):
    __tablename__ = "threads"

    id: Mapped[str] = mapped_column(primary_key=True)
    title: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=_utcnow, onupdate=_utcnow)
    status: Mapped[str] = mapped_column(default="submitted")

    # RENAMED from agent_config (ADR-014):
    # Stores ThreadMetadata.model_dump_json(). NULL for legacy threads.
    metadata: Mapped[str | None] = mapped_column(Text, default=None)

    # ... relationships unchanged ...
```

**Migration note:** The column rename (`agent_config` → `metadata`) is
safe because `agent_config` was never populated — all existing rows have
`NULL` in this column.

A unique index on `nickname` prevents collision:

```python
__table_args__ = (
    Index("ix_threads_nickname", "nickname", unique=True),
)
```

Where `nickname` is extracted as a generated/virtual column or enforced at
the application layer. For SQLite (no virtual columns on expressions), the
application-layer uniqueness check is preferred — `crud.create_thread()`
raises `NicknameConflictError` if a thread with the same nickname already
exists.

### 2.6 Workspace Root Binding

`metadata.workspace_root` is threaded through the endpoint to all config
loaders:

```python
# In create_thread_endpoint:
ws_root = Path(metadata.workspace_root) if metadata else None

team_config = load_team_config(body.team_preset, workspace_root=ws_root)

for worker_ref in team_config.workers:
    agent_configs[worker_ref.agent_id] = load_agent_config(
        worker_ref.agent_id, workspace_root=ws_root
    )
```

This activates the workspace-local override paths that were already
implemented but never invoked (ADR-012 §2.8, ADR-013 §2.8):

```text
1. {workspace_root}/.vaultspec/agents/{agent_id}.toml   (now reachable)
2. src/vaultspec_a2a/core/presets/agents/{agent_id}.toml               (bundled fallback)
```

### 2.7 ACP Session Workspace Binding

`AcpChatModel` subprocess execution must be scoped to the workspace:

```python
# In AcpChatModel._start_process():
cwd = self._workspace_root or Path.cwd()
process = await asyncio.create_subprocess_shell(
    cmd,
    stdin=PIPE, stdout=PIPE, stderr=PIPE,
    cwd=str(cwd),      # ← workspace-scoped
)
```

`_sandbox_path()` validation uses this same `cwd` root. `AcpChatModel`
| gains a `workspace_root: Path | None = None` Pydantic field, set by |
`ProviderFactory.create()` when `metadata.workspace_root` is available.

### 2.8 Wire Contract Amendments

#### ThreadSummary (existing, amended)

```python
class ThreadSummary(BaseModel):
    thread_id: str
    title: str | None = None
    status: str
    created_at: datetime
    updated_at: datetime
    # NEW (ADR-014):
    nickname: str | None = None
    feature_tag: str | None = None
    source_branch: str | None = None
    callee: str | None = None
```

These fields power the thread list sidebar: display nickname instead of
UUID, show the feature tag as a badge, show the branch, show a callee icon.

#### New REST Endpoint: Thread Metadata

```text
GET /threads/{thread_id}/metadata  →  ThreadMetadata | 404
```

Returns the full `ThreadMetadata` object for a thread. Used by the
inspector panel for detailed provenance display.

#### WebSocket `connected` Event Amendment

The `connected` event (sent on subscribe) gains a `metadata` field so the
client receives thread context without a separate REST call:

```python
class ConnectedEvent(BaseModel):
    type: Literal["connected"] = "connected"
    thread_id: str
    last_sequence: int
    # NEW:
    metadata: ThreadMetadata | None = None
```

### 2.9 Nickname Generation

When `metadata.nickname` is not explicitly provided by the caller, the
endpoint auto-generates one:

```python
def generate_nickname(
    feature_tag: str,
    topology: str,
    thread_id: str,
) -> str:
    """Generate a human-friendly thread nickname.

    Format: {feature_tag}-{topology}-{4-char-hex}
    Example: "auth-flow-star-a3f2"
    """
    short_hash = thread_id[:4]
    if feature_tag:
        return f"{feature_tag}-{topology}-{short_hash}"
    return f"thread-{topology}-{short_hash}"
```

This produces names like `auth-flow-star-a3f2` or `refactor-pipeline-b7c1`
— short, unique, and immediately recognizable in the UI.

## 3. Rationale

### Context Preamble Over Template Interpolation

ADR-012 explicitly forbids template variable interpolation in system prompts
for v1. The context preamble as a SystemMessage in `graph_input` achieves
the same goal — agents know the workspace, feature, and available
documents — without amending ADR-012. The preamble is a message, not a
template expansion.

### Document References Over Document Contents

Injecting full document contents into the initial messages would consume
thousands of tokens before the first agent even reasons about the task.
The agents already have ACP filesystem read capability (ADR-012 §2.6).
Providing _references_ (paths + stage labels) lets agents self-serve:
the planner reads research and ADRs, the coder reads the plan, the
reviewer reads the plan and exec records. Each agent pulls exactly what
it needs, when it needs it.

### Metadata in DB Over Metadata in TeamState

`ThreadMetadata` is immutable after creation — it describes the thread's
provenance, not its execution state. Storing it in the DB (`ThreadModel`)
keeps `TeamState` lean and avoids inflating the SQLite checkpointer with
redundant data on every state transition. The context preamble in
`state["messages"]` is the runtime carrier.

### Feature Tag as Discovery Key Over Frontmatter Parsing

Filename-based glob discovery (`*{feature_tag}*.md`) is O(1) filesystem
calls. Parsing YAML frontmatter from every `.md` file under `.vault/`
would be O(n) file reads — impractical for workspaces with hundreds of
documents.

### Workspace Root Explicit Over CWD-Inherited

The orchestrator process may serve threads from multiple repositories
concurrently. Inheriting `Path.cwd()` as the workspace root would bind
all threads to a single directory. Explicit `workspace_root` per-thread
enables multi-repo orchestration without process-level isolation.

### Repurposing `agent_config` Column

`ThreadModel.agent_config` was added speculatively but never populated —
every row in the database has `NULL`. Renaming it to `metadata` reuses the
existing schema slot. A column rename in SQLite requires `ALTER TABLE ...
RENAME COLUMN` (supported since SQLite 3.25.0 / Python 3.8+), which is
a zero-copy metadata operation.

## 4. Rejected Alternatives

### Metadata as LangGraph Config (`configurable`)

LangGraph's `config["configurable"]` dict is persisted by the checkpointer.
We could store metadata there:

```python
config = {
    "configurable": {
        "thread_id": thread.id,
        "metadata": metadata.model_dump(),
    }
}
```

Rejected because: (a) `configurable` is meant for LangGraph-internal
routing keys, not application-level metadata; (b) it would be invisible
to REST queries without loading the full checkpoint; (c) it pollutes
the checkpointer namespace.

### Full Document Injection as Messages

Loading all context documents and injecting their contents as messages:

```python
for ref in context_refs:
    content = (workspace_root / ref.path).read_text()
    graph_input["messages"].append(SystemMessage(content=content))
```

Rejected because: (a) research documents can be 5,000–20,000 tokens each;
(b) 3–5 documents would consume 15,000–100,000 tokens before any agent
acts; (c) agents would receive documents irrelevant to their role (the
coder does not need the research synthesis); (d) exceeds context windows
for smaller models used by some agents.

### Per-Role Document Mapping in Team Config

Adding stage-to-role mappings in the team TOML:

```toml
[team.context_mapping]
planner = ["research", "adr"]
coder   = ["plan"]
reviewer = ["plan", "exec"]
```

Rejected for v1 because: (a) it couples document semantics to team config;
(b) it requires changes to graph compilation (different context per node);
(c) the reference-based approach already enables selective reading — agents
read what they need from the list. This is a valid v2 optimization that
can be layered on without breaking changes.

### Metadata as a Separate Database Table

A `thread_metadata` table with a 1:1 relationship to `threads`. Rejected
because: (a) metadata is always accessed with the thread (no standalone
queries); (b) a JSON column on the existing table avoids the join; (c)
the metadata is a single Pydantic model — no relational normalization
benefit.

### Auto-Detecting Callee from User-Agent

HTTP `User-Agent` headers could identify Claude CLI vs. Gemini CLI.
Rejected as the sole mechanism because: (a) MCP bridge requests have no
User-Agent; (b) programmatic REST clients may not set meaningful headers;
(c) explicit declaration by the caller is more reliable. Auto-detection
can be a fallback when `callee` is empty.

## 5. Implementation Constraints

- `metadata.workspace_root` must be validated as an existing directory
  before threading it to config loaders. Return HTTP 422 if the path
  does not exist or is not a directory.
- `metadata.workspace_root` must not escape the OS-allowed filesystem
  boundaries. On Windows, UNC paths and drive letters are valid.
  Symlink traversal out of the workspace is explicitly allowed (tools
  like `node_modules/.bin` rely on symlinks).
- `metadata.nickname` must be a valid slug: lowercase alphanumeric +
  hyphens, 3–64 characters. Validated by Pydantic field constraint.
- `metadata.context_refs[].path` must be relative (no absolute paths).
  Resolved against `workspace_root` at preamble construction time.
  Paths that resolve outside `workspace_root` are silently excluded.
- `discover_context_refs()` must have a hard cap on results (e.g., 50
  documents) to prevent pathological workspaces from generating a
  context preamble that exceeds reasonable token budgets.
- The `metadata` column stores `ThreadMetadata.model_dump_json()`. Reads
  deserialize via `ThreadMetadata.model_validate_json()`. Schema
  evolution is handled by Pydantic's permissive-by-default parsing
  (unknown fields are ignored, missing optional fields get defaults).
- `compact_context()` must preserve the context preamble SystemMessage.
  The current implementation already preserves all leading SystemMessages
  — no code change required, but a regression test must be added.

## 6. Module Hierarchy Impact (ADR-009 Amendment)

```text
src/vaultspec_a2a/core/
├── team_config.py       # GAINS: ThreadMetadata, ContextRef models +
│                        #        discover_context_refs() function
├── ...

src/vaultspec_a2a/api/
├── schemas/
│   ├── rest.py          # AMENDED: CreateThreadRequest gains metadata field
│   │                    #          ThreadSummary gains nickname, feature_tag, etc.
│   └── ...
├── endpoints.py         # AMENDED: create_thread_endpoint threads workspace_root,
│                        #          builds context preamble, auto-discovers docs
└── ...

src/vaultspec_a2a/database/
├── models.py            # AMENDED: ThreadModel.agent_config → metadata
├── crud.py              # AMENDED: create_thread() accepts metadata param,
│                        #          nickname uniqueness check
└── ...

src/vaultspec_a2a/providers/
├── acp_chat_model.py    # AMENDED: AcpChatModel gains workspace_root field,
│                        #          _start_process() uses it for CWD
├── factory.py           # AMENDED: ProviderFactory.create() accepts workspace_root
└── ...
```

## 7. References

- `src/vaultspec_a2a/api/endpoints.py:180` — `create_thread_endpoint()` (to be amended)
- `src/vaultspec_a2a/core/team_config.py` — `load_team_config()`, `load_agent_config()`
  (workspace_root param already exists, never invoked)
- `src/vaultspec_a2a/core/state.py` — `TeamState` (unchanged — metadata stays in DB)
- `src/vaultspec_a2a/core/context.py:56` — `compact_context()` (preserves leading
  SystemMessages — regression test needed)
- `src/vaultspec_a2a/core/nodes/worker.py:92` — `worker_node()` (unchanged — preamble
  arrives via `state["messages"]`)
- `src/vaultspec_a2a/core/nodes/supervisor.py:40` — `supervisor_node()` (unchanged)
- `src/vaultspec_a2a/database/models.py:37` — `ThreadModel` (agent_config → metadata)
- `src/vaultspec_a2a/database/crud.py` — `create_thread()` (gains metadata + nickname
  check)
- `src/vaultspec_a2a/providers/acp_chat_model.py` — `_start_process()` (CWD binding)
- `src/vaultspec_a2a/providers/factory.py` — `ProviderFactory.create()` (workspace_root
  forwarding)
- `src/vaultspec_a2a/core/presets/agents/supervisor.toml:23` — references
  `.vault/research/`, `.vault/plan/`, `.vault/exec/`
- `src/vaultspec_a2a/core/presets/agents/coder.toml:49` — references
  `.vault/exec/yyyy-mm-dd-<feature>/`
- `src/vaultspec_a2a/core/presets/agents/planner.toml:43` — references
  `.vault/plan/yyyy-mm-dd-<feature>-<phase>-plan.md`
- `src/vaultspec_a2a/core/presets/agents/reviewer.toml:102` — references
  `.vault/exec/yyyy-mm-dd-<feature>/yyyy-mm-dd-<feature>-review.md`
- [ADR-008](008-orchestration-topology-pipeline.md) — Orchestration
  Topology (native LangGraph execution)
- [ADR-011](011-frontend-backend-contract.md) — Wire Contract
  (CreateThreadRequest, ThreadSummary)
- [ADR-012](012-agent-definition-schema.md) — Agent Definition Schema
  (§5: no template interpolation for v1)
- [ADR-013](013-team-composition-topology.md) — Team Composition (§6:
  CreateThreadRequest.team_preset)
