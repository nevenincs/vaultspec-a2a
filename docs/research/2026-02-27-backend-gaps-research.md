---
name: 'Backend Gaps: LangGraph Aggregator, SQLite Schema, Workspace Management'
date: 2026-02-27
type: research
summary: >
  Comprehensive research covering three open implementation areas: (1) LangGraph
  event aggregation patterns for building a central WebSocket multiplexer from
  astream_events, (2) SQLite schema design alongside langgraph-checkpoint-sqlite,
  and (3) async git worktree management patterns for multi-agent filesystem
  isolation.
maturity: 85
related:
  - docs/adrs/001-process-and-workspace-management.md
  - docs/adrs/004-event-aggregation-server-side-replay.md
  - docs/adrs/007-tech-stack-deployment.md
  - docs/adrs/008-orchestration-topology-pipeline.md
  - docs/adrs/009-approved-module-hierarchy.md
---

# Backend Gaps Research: Aggregator, SQLite, Workspace

## 1. LangGraph Event Aggregation Patterns

### 1.1 LangGraph Streaming Modes

LangGraph exposes four first-class streaming primitives via its compiled graph.
All are async and are the canonical source of data for the Event Aggregator:

| Method                                           | `stream_mode`             | Granularity                            | Best use                   |
| ------------------------------------------------ | ------------------------- | -------------------------------------- | -------------------------- |
| `astream(input, config, stream_mode="values")`   | `"values"`                | Full state snapshot per step           | Snapshot replay            |
| `astream(input, config, stream_mode="updates")`  | `"updates"`               | Per-node delta dict                    | Live agent status panels   |
| `astream(input, config, stream_mode="messages")` | `"messages"`              | Token-by-token from any LLM invocation | Streaming chat bubbles     |
| `astream(input, config, stream_mode="debug")`    | `"debug"`                 | Checkpoint + task events               | Deep debugging             |
| `astream_events(input, config, version="v2")`    | N/A (LangChain callbacks) | Granular on\_\*\_start/end events      | Tool calls, thought blocks |

**Key insight from source code** (`langgraph/types.py` line 95–109):

```python
StreamMode = Literal[
    "values", "updates", "checkpoints", "tasks", "debug", "messages", "custom"
]
```

The `"messages"` mode emits LLM token chunks together with metadata for any
LLM invocations inside nodes — this is the **primary source** for
`message_chunk`and`thought_chunk`server events.

The`"updates"` mode emits per-node deltas after each step — this drives
`agent_status` events.

### 1.2 astream_events Schema (v2)

`astream_events` (from LangChain core, not LangGraph) provides a richer callback
stream that fires for every operation in the graph. Each event has this shape:

```python
{
    "event": str,         # e.g. "on_chat_model_stream", "on_tool_start"
    "name": str,          # node or runnable name
    "run_id": str,        # UUID4 for this invocation
    "tags": list[str],
    "metadata": dict,
    "data": dict,         # event-specific payload
    "parent_ids": list[str],
}
```

### High-value events for our wire protocol

| LangChain event              | Maps to server event     | Notes                               |
| ---------------------------- | ------------------------ | ----------------------------------- |
| `on_chat_model_stream`       | `message_chunk`          | `data["chunk"].content`= token text |
| `on_chat_model_end`          | (no event needed)        | Marks completion of a turn          |
| `on_tool_start`              | `tool_call_start`        | `data["input"]`= tool args          |
| `on_tool_end`                | `tool_call_update`       | `data["output"]`= tool result       |
| `on_chain_start`(node entry) | `agent_status`→`working` | `name`= node name                   |
| `on_chain_end`(node exit)    | `agent_status`→`idle`    | After final node                    |
| `on_custom_event`            | `thought_chunk`          | Via`StreamWriter`in nodes           |

### Noise to filter

- Internal LangGraph pregel events tagged with`TAG_HIDDEN`
- Duplicate `on_chain_start`/`on_chain_end`from sub-runnables
  (check`metadata["langgraph_node"]`to scope to the graph's own nodes) -`on_retriever_*`events (not relevant unless we add RAG) -`on_prompt_*` events (template expansion, low value)

Filter pattern:

```python
PASSTHROUGH_EVENTS = frozenset({
    "on_chat_model_stream",
    "on_tool_start",
    "on_tool_end",
    "on_custom_event",
})
NODE_BOUNDARY_EVENTS = frozenset({
    "on_chain_start",
    "on_chain_end",
})
```

Only emit `agent_status`for`on_chain_start`/`on_chain_end` when
`event["metadata"].get("langgraph_node")`is set and not in an internal pregel
namespace (i.e.,`event["name"]` matches a known graph node name like
`"supervisor"`, `"coder"`, etc.).

### 1.3 Recommended Aggregator Architecture

The central `EventAggregator`in`src/vaultspec_a2a/core/aggregator.py`should:

1. **Own one`asyncio.Queue`per`thread_id`**: Incoming LangGraph events are
   enqueued by a task running `astream_events`. The queue is the backpressure
   boundary — bounded at ~512 events.

1. **Run a single fan-out coroutine**: A background task drains each queue and
   broadcasts to all active WebSocket connections subscribed to that
   `thread_id`.

1. **Debounce high-frequency events**: Token streaming events
   (`on_chat_model_stream`)
   must be batched before WebSocket send:
   - Collect chunks into a buffer
   - Flush every **50ms** or when buffer reaches **4KB** (whichever first)
   - Use `asyncio.create_task`+`asyncio.sleep(0.05)`timer pattern

1. **Thread-ID envelope**: Every outbound WebSocket frame MUST carry
   `thread_id`as the top-level discriminator (per ADR-011`EventEnvelope`).

### Skeleton pattern

```python
import asyncio
from collections import defaultdict
from typing import Any

class EventAggregator:
    """Central event bus: ingests LangGraph streams, fans out to WebSockets."""

    def __init__(self) -> None:
        # thread_id -> asyncio.Queue[dict | None]
        self._queues: dict[str, asyncio.Queue[dict | None]] = {}
        # thread_id -> set of WebSocket send callables
        self._subscribers: dict[str, set] = defaultdict(set)
        self._debounce_tasks: dict[str, asyncio.Task] = {}

    async def ingest(self, thread_id: str, graph, input: Any, config: dict) -> None:
        """Start consuming astream_events for a thread, enqueue transformed events."""
        q = asyncio.Queue(maxsize=512)
        self._queues[thread_id] = q
        try:
            async for raw_event in graph.astream_events(input, config, version="v2"):
                wire_event = self._transform(thread_id, raw_event)
                if wire_event is not None:
                    await q.put(wire_event)
        finally:
            await q.put(None)  # sentinel: stream finished

    def _transform(self, thread_id: str, event: dict) -> dict | None:
        """Map LangChain callback events to wire protocol server events."""
        ev_type = event["event"]
        node = event["metadata"].get("langgraph_node")

        if ev_type == "on_chat_model_stream":
            chunk = event["data"]["chunk"].content
            if not chunk:
                return None
            return {
                "type": "message_chunk",
                "thread_id": thread_id,
                "content": chunk,
                "run_id": event["run_id"],
            }
        elif ev_type == "on_tool_start" and node:
            return {
                "type": "tool_call_start",
                "thread_id": thread_id,
                "tool_name": event["name"],
                "tool_input": event["data"].get("input"),
                "run_id": event["run_id"],
            }
        elif ev_type == "on_tool_end" and node:
            return {
                "type": "tool_call_update",
                "thread_id": thread_id,
                "tool_name": event["name"],
                "tool_output": str(event["data"].get("output", "")),
                "run_id": event["run_id"],
            }
        elif ev_type == "on_chain_start" and node:
            return {
                "type": "agent_status",
                "thread_id": thread_id,
                "status": "working",
                "node": node,
            }
        elif ev_type == "on_chain_end" and node:
            return {
                "type": "agent_status",
                "thread_id": thread_id,
                "status": "idle",
                "node": node,
            }
        return None

    async def subscribe(self, thread_id: str, send_fn) -> None:
        """Register a WebSocket send callable for a thread."""
        self._subscribers[thread_id].add(send_fn)

    async def unsubscribe(self, thread_id: str, send_fn) -> None:
        """Remove a WebSocket send callable."""
        self._subscribers[thread_id].discard(send_fn)

    async def _fan_out(self, thread_id: str) -> None:
        """Drain queue and broadcast events to all subscribers."""
        q = self._queues[thread_id]
        chunk_buffer: list[str] = []
        last_flush = asyncio.get_event_loop().time()

        async def flush_chunks():
            if chunk_buffer:
                combined = {
                    "type": "message_chunk",
                    "thread_id": thread_id,
                    "content": "".join(chunk_buffer),
                }
                chunk_buffer.clear()
                await self._broadcast(thread_id, combined)

        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=0.05)
            except asyncio.TimeoutError:
                await flush_chunks()
                continue

            if event is None:  # sentinel
                await flush_chunks()
                break

            if event.get("type") == "message_chunk":
                chunk_buffer.append(event["content"])
                now = asyncio.get_event_loop().time()
                if now - last_flush >= 0.05 or len("".join(chunk_buffer)) >= 4096:
                    await flush_chunks()
                    last_flush = now
            else:
                await flush_chunks()
                await self._broadcast(thread_id, event)

    async def _broadcast(self, thread_id: str, event: dict) -> None:
        """Send event to all WebSocket subscribers for this thread."""
        dead = set()
        for send_fn in self._subscribers.get(thread_id, set()):
            try:
                await send_fn(event)
            except Exception:
                dead.add(send_fn)
        for fn in dead:
            self._subscribers[thread_id].discard(fn)
```

### 1.4 WebSocket Multiplexing Pattern

The `src/vaultspec_a2a/api/websocket.py`handler should:

1. Accept one WebSocket per browser tab.
2. Parse`ClientCommand`frames (discriminated on`type`).
3. On `subscribe`: call `aggregator.subscribe(thread_id, ws.send_json)`.
4. On `unsubscribe`: call `aggregator.unsubscribe(thread_id, ws.send_json)`.
5. On disconnect: unsubscribe from all `thread_id`s this socket subscribed to.
6. On `send_message`: enqueue a new graph invocation via `aggregator.ingest()`.
7. On `permission_response`: update the LangGraph `Command(resume=...)`via
   the core graph layer. **Never** route permission responses back through the
   WebSocket aggregator — they MUST go through REST per ADR-011.

**Lifespan binding** (per ADR-007): The`EventAggregator`instance is a
singleton started in FastAPI's`@asynccontextmanager`lifespan. It is injected
into WebSocket handlers via FastAPI Dependency Injection.

### 1.5 Backpressure Strategy

| Source                           | Bounded by             | Drop policy                                                      |
| -------------------------------- | ---------------------- | ---------------------------------------------------------------- |
| LangGraph`astream_events`→ Queue | `maxsize=512`          | `await q.put()`blocks generator coroutine (natural backpressure) |
| Queue → WebSocket broadcast      | WebSocket send timeout | Remove dead sockets from subscriber set                          |
| Token chunk debounce buffer      | 4KB max or 50ms flush  | Always flush before sending non-chunk events                     |

**Critical**: Never use`q.put_nowait()`. Always `await q.put()`to propagate
backpressure to the LangGraph generator, preventing memory blowup if a browser
client is slow.

---

## 2. SQLite Schema Design

### 2.1 What langgraph-checkpoint-sqlite Owns

Reading`knowledge/repositories/langgraph/libs/checkpoint-sqlite/langgraph/checkpoint/sqlite/aio.py`,
the `AsyncSqliteSaver.setup()` method creates exactly two tables:

```sql
-- Table 1: Checkpoint state blobs per thread+namespace
CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id          TEXT NOT NULL,
    checkpoint_ns      TEXT NOT NULL DEFAULT '',
    checkpoint_id      TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type               TEXT,
    checkpoint         BLOB,   -- serialized state dict (JsonPlus)
    metadata           BLOB,   -- JSON metadata blob
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

-- Table 2: Pending writes (incomplete node outputs)
CREATE TABLE IF NOT EXISTS writes (
    thread_id      TEXT NOT NULL,
    checkpoint_ns  TEXT NOT NULL DEFAULT '',
    checkpoint_id  TEXT NOT NULL,
    task_id        TEXT NOT NULL,
    idx            INTEGER NOT NULL,
    channel        TEXT NOT NULL,
    type           TEXT,
    value          BLOB,   -- serialized channel value
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);
```

Additionally, `langgraph-checkpoint-sqlite`'s `AsyncSqliteStore` creates a
`store` table for long-term key-value memory:

```sql
CREATE TABLE IF NOT EXISTS store (
    prefix     text NOT NULL,   -- namespace (dot-separated)
    key        text NOT NULL,
    value      text NOT NULL,   -- JSON blob
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP,       -- for TTL
    ttl_minutes REAL,
    PRIMARY KEY (prefix, key)
);
CREATE INDEX IF NOT EXISTS store_prefix_idx ON store (prefix);
CREATE INDEX IF NOT EXISTS idx_store_expires_at ON store (expires_at)
    WHERE expires_at IS NOT NULL;
```

**Key finding**: LangGraph automatically sets `PRAGMA journal_mode=WAL` during
`AsyncSqliteSaver.setup()`. Our application code does NOT need to set it
manually.

### 2.2 Recommended Application Schema (Our Tables)

We should share the **same SQLite database file** as the checkpointer. This
avoids the overhead of a second `aiosqlite` connection and ensures all data
(graph state + our metadata) can be read in a single SQL JOIN if ever needed.

Our custom tables alongside LangGraph's:

```sql
-- Threads: top-level unit of work (corresponds to LangGraph thread_id)
CREATE TABLE IF NOT EXISTS threads (
    id           TEXT PRIMARY KEY,          -- UUID4 = thread_id used in LangGraph
    created_at   TEXT NOT NULL,             -- ISO8601 UTC
    updated_at   TEXT NOT NULL,             -- ISO8601 UTC
    status       TEXT NOT NULL              -- 'active'|'completed'|'failed'|'cancelled'
        CHECK(status IN ('active','completed','failed','cancelled')),
    title        TEXT,                      -- human-readable task description
    metadata     TEXT                       -- JSON blob for arbitrary extensions
);
CREATE INDEX IF NOT EXISTS idx_threads_status ON threads (status);
CREATE INDEX IF NOT EXISTS idx_threads_created_at ON threads (created_at DESC);

-- Artifacts: code files, diff outputs, plan documents produced by agents
CREATE TABLE IF NOT EXISTS artifacts (
    id           TEXT PRIMARY KEY,          -- UUID4
    thread_id    TEXT NOT NULL
        REFERENCES threads(id) ON DELETE CASCADE,
    created_at   TEXT NOT NULL,
    agent_name   TEXT NOT NULL,             -- e.g. 'coder', 'reviewer'
    artifact_type TEXT NOT NULL             -- 'file'|'diff'|'plan'|'text'
        CHECK(artifact_type IN ('file','diff','plan','text')),
    path         TEXT,                      -- relative path in worktree (nullable for non-file types)
    content      TEXT NOT NULL,             -- full artifact content
    mime_type    TEXT                       -- e.g. 'text/x-python'
);
CREATE INDEX IF NOT EXISTS idx_artifacts_thread_id ON artifacts (thread_id);

-- Permission log: record of every interrupt + human decision
CREATE TABLE IF NOT EXISTS permission_log (
    id              TEXT PRIMARY KEY,        -- UUID4
    thread_id       TEXT NOT NULL
        REFERENCES threads(id) ON DELETE CASCADE,
    checkpoint_id   TEXT,                    -- LangGraph checkpoint that issued the interrupt
    created_at      TEXT NOT NULL,           -- when the interrupt was issued
    resolved_at     TEXT,                    -- when the human responded (null = pending)
    tool_name       TEXT NOT NULL,
    tool_input      TEXT NOT NULL,           -- JSON blob
    options         TEXT NOT NULL,           -- JSON array of {optionId, label}
    decision        TEXT,                    -- chosen optionId (null = pending/unresolved)
    decision_source TEXT                     -- 'user'|'timeout'|'policy'
);
CREATE INDEX IF NOT EXISTS idx_permission_log_thread_id ON permission_log (thread_id);
CREATE INDEX IF NOT EXISTS idx_permission_log_pending
    ON permission_log (thread_id) WHERE resolved_at IS NULL;

-- Cost tracking: token usage per thread+agent turn
CREATE TABLE IF NOT EXISTS token_usage (
    id           TEXT PRIMARY KEY,           -- UUID4
    thread_id    TEXT NOT NULL
        REFERENCES threads(id) ON DELETE CASCADE,
    recorded_at  TEXT NOT NULL,
    agent_name   TEXT NOT NULL,
    model_name   TEXT NOT NULL,              -- e.g. 'claude-opus-4-6'
    prompt_tokens    INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_token_usage_thread_id ON token_usage (thread_id);
```

### 2.3 Sharing the Database File: Safety Considerations

`AsyncSqliteSaver`uses a single`aiosqlite.Connection` protected by an
`asyncio.Lock`. Our custom CRUD operations must use a **separate connection**
to avoid deadlocking LangGraph's internal lock.

### Recommended pattern

```python
# src/vaultspec_a2a/database/session.py

import aiosqlite
from contextlib import asynccontextmanager
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

DB_PATH = "vaultspec.db"

@asynccontextmanager
async def get_checkpointer():
    """Yields an AsyncSqliteSaver for LangGraph graph compilation."""
    async with AsyncSqliteSaver.from_conn_string(DB_PATH) as saver:
        yield saver

@asynccontextmanager
async def get_db():
    """Yields a raw aiosqlite connection for our custom CRUD."""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        yield conn

async def setup_app_tables(conn: aiosqlite.Connection) -> None:
    """Create application-level tables (idempotent)."""
    await conn.executescript("""
        CREATE TABLE IF NOT EXISTS threads ( ... );
        CREATE TABLE IF NOT EXISTS artifacts ( ... );
        CREATE TABLE IF NOT EXISTS permission_log ( ... );
        CREATE TABLE IF NOT EXISTS token_usage ( ... );
    """)
    await conn.commit()
```

**SQLite WAL mode is set by LangGraph's `AsyncSqliteSaver.setup()`** on first
connection. Our second connection on the same file inherits WAL mode
automatically (it is a file-level pragma). However, to be safe, our
`setup_app_tables`function should also issue`PRAGMA journal_mode=WAL;`.

### 2.4 Connection Pool Constraint

Per ADR-007: "Writes must be batched or funneled through a single async
worker."

For our CRUD layer:

- Use one dedicated `aiosqlite.Connection`per FastAPI lifespan (singleton)
- Protect it with an`asyncio.Lock()`(same pattern as`AsyncSqliteSaver`)
- For read-heavy endpoints (snapshots, artifact listing), open short-lived
  read connections — SQLite WAL allows concurrent readers

### 2.5 Migration Strategy

Use a simple version table + sequential numbered migrations (no external
migration tool needed for a dev tool):

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version  INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
```

Migration runner checks `MAX(version)` and applies numbered scripts from
`src/vaultspec_a2a/database/migrations/` in order. This gives us forward-only migration
without the overhead of Alembic.

---

## 3. Git Worktree Management

### 3.1 ADR-001 Requirements Recap

- Dual-mode support: flat hierarchy (dev) + worktree mode (agents)
- Manual cleanup only (no automatic teardown)
- Global Git Mutex (`asyncio.Lock`) for destructive repo-wide operations
- All operations must be `async def`(no blocking calls in Uvicorn event loop)

### 3.2 Async Git Operation Pattern

Python has no official async git library. Options:

| Approach                                       | Pros                            | Cons                                              |
| ---------------------------------------------- | ------------------------------- | ------------------------------------------------- |
| `asyncio.create_subprocess_exec(["git", ...])` | Zero dependencies, native async | Must parse stdout, no object model                |
| `gitpython`via`asyncio.to_thread`              | Rich object model               | gitpython is sync-only; blocks thread pool        |
| `pygit2`via`asyncio.to_thread`                 | Fast C bindings, libgit2        | Same blocking issue; libgit2 not great on Windows |

**Recommendation**: Use`asyncio.create_subprocess_exec`for all git
operations. This is the safest approach on Windows, avoids blocking the
event loop, and matches how the existing`AcpChatModel` handles subprocesses.

```python
import asyncio
import shlex
from pathlib import Path

_git_mutex = asyncio.Lock()  # Global Git Mutex (ADR-001)

async def _run_git(
    *args: str,
    cwd: Path,
    use_mutex: bool = False,
) -> tuple[int, str, str]:
    """Run a git command async. Returns (returncode, stdout, stderr)."""
    async with (_git_mutex if use_mutex else asyncio.nullcontext()):
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
    return (
        proc.returncode,
        stdout.decode("utf-8", errors="replace").strip(),
        stderr.decode("utf-8", errors="replace").strip(),
    )
```

### 3.3 Worktree Lifecycle

#### Creation

```python
async def create_worktree(
    repo_root: Path,
    worktree_path: Path,
    branch_name: str,
    base_branch: str = "main",
) -> None:
    """Create a new git worktree at worktree_path on a new branch."""
    # Fetch latest (mutex: destructive repo-wide operation)
    rc, _, err = await _run_git(
        "fetch", "origin", base_branch,
        cwd=repo_root,
        use_mutex=True,
    )
    if rc != 0:
        raise WorktreeError(f"git fetch failed: {err}")

    # Create worktree + new branch from base (mutex: modifies .git/worktrees/)
    rc, _, err = await _run_git(
        "worktree", "add", "-b", branch_name,
        str(worktree_path), f"origin/{base_branch}",
        cwd=repo_root,
        use_mutex=True,
    )
    if rc != 0:
        raise WorktreeError(f"git worktree add failed: {err}")
```

#### Branch Naming Convention (ADR-001)

```markdown
agent/{role}/{thread_id_short}

# Examples:

agent/coder/a1b2c3d4
agent/reviewer/a1b2c3d4
```

`thread_id_short`= first 8 characters of the`thread_id` UUID.

#### Merge Strategy

Per ADR-001 (G10: Merge Conflict Strategy), the Global Git Mutex must be held
during merge/rebase:

```python
async def merge_worktree_branch(
    repo_root: Path,
    branch_name: str,
    target_branch: str = "main",
) -> tuple[bool, str]:
    """
    Attempt fast-forward merge. Returns (success, message).
    If FF not possible, returns (False, conflict_details).
    """
    async with _git_mutex:
        # Checkout target
        rc, _, err = await _run_git(
            "checkout", target_branch, cwd=repo_root
        )
        if rc != 0:
            return False, f"checkout failed: {err}"

        # Attempt FF merge only
        rc, stdout, err = await _run_git(
            "merge", "--ff-only", branch_name, cwd=repo_root
        )
        if rc == 0:
            return True, stdout

        # FF not possible: report conflict, DO NOT force
        return False, f"Fast-forward not possible: {err}"
```

**Why fast-forward only**: Rebasing and three-way merges under the mutex could
hold it for seconds while git runs recursive merge strategies. An FF check is
instantaneous: either the branch is a linear extension of main, or it isn't.
If FF fails, the human (via permission flow) decides whether to rebase or
squash.

#### Conflict Detection

```python
async def check_merge_conflicts(
    repo_root: Path,
    branch_name: str,
    target_branch: str = "main",
) -> list[str]:
    """
    Returns list of files that would conflict (empty = clean merge).
    Uses --no-commit --no-ff dry-run approach.
    """
    async with _git_mutex:
        # Save current HEAD
        rc, original_head, _ = await _run_git(
            "rev-parse", "HEAD", cwd=repo_root
        )

        # Try merge without committing
        rc, _, _ = await _run_git(
            "merge", "--no-commit", "--no-ff", branch_name,
            cwd=repo_root
        )
        if rc == 0:
            # Clean — abort to restore state
            await _run_git("merge", "--abort", cwd=repo_root)
            return []

        # Get conflicted files
        rc, stdout, _ = await _run_git(
            "diff", "--name-only", "--diff-filter=U",
            cwd=repo_root
        )
        conflicted = [f for f in stdout.splitlines() if f]

        # Abort merge to restore clean state
        await _run_git("merge", "--abort", cwd=repo_root)
        return conflicted
```

### 3.4 Worktree Path Resolution (Dual-Mode)

Per ADR-001, the `WorkspaceManager`must resolve`.venv` and utility paths
differently depending on mode:

```python
from enum import Enum
from pathlib import Path
from dataclasses import dataclass

class WorkspaceMode(Enum):
    FLAT = "flat"         # agent operates in repo root
    WORKTREE = "worktree" # agent operates in a worktree subdirectory

@dataclass
class WorkspaceConfig:
    mode: WorkspaceMode
    agent_cwd: Path          # where the agent runs (worktree path or repo root)
    repo_root: Path          # canonical .git root
    venv_path: Path          # resolved .venv (may differ from agent_cwd)

    @classmethod
    def from_worktree(cls, repo_root: Path, worktree_path: Path) -> "WorkspaceConfig":
        # .venv lives in repo_root for worktree mode (per ADR-001)
        return cls(
            mode=WorkspaceMode.WORKTREE,
            agent_cwd=worktree_path,
            repo_root=repo_root,
            venv_path=repo_root / ".venv",
        )

    @classmethod
    def from_flat(cls, repo_root: Path) -> "WorkspaceConfig":
        return cls(
            mode=WorkspaceMode.FLAT,
            agent_cwd=repo_root,
            repo_root=repo_root,
            venv_path=repo_root / ".venv",
        )

    def env_overrides(self) -> dict[str, str]:
        """Env vars to inject into subprocess (for AcpChatModel)."""
        return {
            "VIRTUAL_ENV": str(self.venv_path),
            "PATH": f"{self.venv_path / 'Scripts'};{__import__('os').environ['PATH']}",
        }
```

### 3.5 Worktree Cleanup (Manual Only)

Per ADR-001: "Worktree deletion functionality will be implemented but will not
be automatic."

```python
async def remove_worktree(
    repo_root: Path,
    worktree_path: Path,
    force: bool = False,
) -> None:
    """Remove a git worktree. Requires explicit human trigger."""
    rc, _, err = await _run_git(
        "worktree", "remove", *(["--force"] if force else []),
        str(worktree_path),
        cwd=repo_root,
        use_mutex=True,
    )
    if rc != 0:
        raise WorktreeError(f"git worktree remove failed: {err}")
```

### 3.6 Listing Active Worktrees

```python
async def list_worktrees(repo_root: Path) -> list[dict]:
    """Return list of worktrees with path, branch, HEAD commit."""
    rc, stdout, _ = await _run_git(
        "worktree", "list", "--porcelain",
        cwd=repo_root
    )
    worktrees = []
    current: dict = {}
    for line in stdout.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line[len("worktree "):].strip()}
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD "):].strip()
        elif line.startswith("branch "):
            current["branch"] = line[len("branch "):].strip()
    if current:
        worktrees.append(current)
    return worktrees
```

### 3.7 Mutex Deadlock Prevention

The Global Git Mutex must ALWAYS be released via `try/finally`. The pattern:

```python
async with _git_mutex:
    try:
        rc, stdout, err = await _run_git(...)
        # process result
    except Exception:
        raise  # let caller handle; mutex releases via context manager exit
```

Since `asyncio.Lock()`is used as an async context manager, Python guarantees
release on`__aexit__` regardless of exception. The risk is a coroutine being
cancelled while holding the lock. To mitigate:

```python
async def safe_git_op(coro):
    """Shield a mutex-holding git operation from external cancellation."""
    return await asyncio.shield(coro)
```

Use `asyncio.shield()`only for the critical section inside the mutex (e.g.,
the`git merge`call) — not for the entire`_run_git` wrapper.

---

## 4. Implementation Recommendations for Downstream Tasks

### 4.1 For Task #4: Event Aggregator (`src/vaultspec_a2a/core/aggregator.py`)

- Implement the `EventAggregator`class per section 1.3
- Use`stream_mode=["updates", "messages"]`via`astream`for structured
  status/message events; use`astream_events(version="v2")`for granular
  tool call events
- Prefer`astream`with`stream_mode="messages"`for token streaming —
  it avoids the overhead of full`astream_events`callback processing
- Singleton lifecycle bound to FastAPI lifespan via`anyio.create_task_group`
- Expose `subscribe(thread_id, send_fn)`/`unsubscribe`/`ingest` public API

### 4.2 For Task #3: Database Layer (`src/vaultspec_a2a/database/`)

- Module structure: `session.py`(connection + setup),`models.py`(dataclasses
  for our tables),`crud.py`(async CRUD functions)
- Use`aiosqlite.Row`row factory for named column access
- Do NOT use SQLAlchemy — it adds complexity without benefit for a simple CRUD
  layer over a local SQLite file
- The`threads`table`id`column MUST match LangGraph's`thread_id`exactly
  (both are`TEXT`, both are UUIDs)
- Expose `get_db()` as an async context manager FastAPI dependency

### 4.3 For Task #7: Workspace Manager (`src/vaultspec_a2a/workspace/git_manager.py`)

- Implement `_run_git`, `_git_mutex`, `WorkspaceConfig`per section 3
- Expose`WorkspaceManager`class with methods:`create_worktree`,
  `remove_worktree`, `list_worktrees`, `check_merge_conflicts`,
  `merge_worktree_branch`
- All public methods are `async def`
- Singleton `_git_mutex`lives at module level (not class level) to be
  truly global across instances
- On Windows 11:`git`must be on`PATH`. Use `shutil.which("git")`to
  verify at startup and raise a clear error if not found

---

## 5. References

-`knowledge/repositories/langgraph/libs/checkpoint-sqlite/langgraph/checkpoint/sqlite/aio.py`
— Source of `AsyncSqliteSaver.setup()`schema -`knowledge/repositories/langgraph/libs/checkpoint-sqlite/langgraph/store/sqlite/base.py`
— Source of `store`table MIGRATIONS list -`knowledge/repositories/langgraph/libs/langgraph/langgraph/types.py`
— `StreamMode`literal definition -`knowledge/repositories/langgraph/libs/langgraph/langgraph/pregel/debug.py`
— `TaskPayload`, `CheckpointPayload`, `map_debug_checkpoint`

- `docs/adrs/001-process-and-workspace-management.md`— Global Git Mutex,
  dual-mode workspaces -`docs/adrs/004-event-aggregation-server-side-replay.md`— Aggregator
  requirements -`docs/adrs/007-tech-stack-deployment.md`— SQLite WAL, aiosqlite, lifespan
  management -`docs/adrs/009-approved-module-hierarchy.md`—`src/vaultspec_a2a/database/`, `src/vaultspec_a2a/workspace/`,
  `src/vaultspec_a2a/core/aggregator.py`
