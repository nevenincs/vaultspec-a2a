---
date: 2026-02-28
type: plan
feature: autonomous-mode-mcp
description: "Implementation plan for autonomous mode flag and MCP server tool stubs, fixing the broken permission interrupt chain and enabling headless agent orchestration."
related_adrs:
  - docs/adrs/2026-02-26-003-protocol-bridging-translation-adr.md
  - docs/adrs/2026-02-26-004-event-aggregation-replay-adr.md
  - docs/adrs/2026-02-26-008-orchestration-topology-pipeline-adr.md
  - docs/adrs/2026-02-27-013-team-composition-topology-adr.md
related_research:
  - docs/research/2026-02-25-protocols-distilled-research.md
  - docs/research/2026-02-27-backend-gaps-research.md
---

# Plan: Autonomous Mode + MCP Implementation

## Context

Three compounding problems identified through audit:

1. **Permission interrupt chain broken in supervised mode** —
   `aggregator.ingest()`never detects`interrupt()`suspension.
   When`astream_events`ends due to a LangGraph interrupt,
   no`PermissionRequestEvent`is emitted; the graph silently hangs in SQLite
   forever.

1. **No autonomy mode** — every MCP-triggered team deadlocks on the first
   permission interrupt. The`interrupt_before`mechanism (set on nodes
   with`require_approval_for`) fires before the coder even runs; since there is
   no human watching in a headless launch, the graph never resumes.

1. **MCP server entirely stubbed** — all three tools return documentation
   strings without touching the graph engine.

### Research findings (FastMCP 3.x + A2A patterns)

- FastMCP `>=3.0.2`supports`async def @mcp.tool()` — use it.
- Standard A2A autonomous patterns: Pattern A (`--yolo`auto-approve) is
  acceptable when the user explicitly opts in by launching headlessly. Our
  architecture gates this with the`autonomous`flag.
-`interrupt_before`(pre-node graph pause) universally auto-proceeds in all modes
in this architecture — it only pauses before a node but the actual approval is
tool-level. Decision: **remove`interrupt_before`entirely; make`interrupt_nodes =
[]`always.** All human approval flows through`interrupt()`inside the node only.
This eliminates the auto-resume loop complexity.

---

## Files Modified

| File | Change |
| --- | --- |
| `lib/core/config.py` | Add`api_base_url: str`setting |
| `lib/core/graph.py` | `interrupt_nodes = []`always; add`autonomous: bool = False`; thread to `_compile_*`helpers |
| `lib/core/nodes/worker.py` | Add`autonomous: bool = False`; skip `permission_callback`wiring when True |
| `lib/core/aggregator.py` | Extend`_StreamableGraph`protocol with`aget_state`; add interrupt detection in `ingest()` |
| `lib/api/schemas/rest.py` | Add`autonomous: bool = False`to`CreateThreadRequest` |
| `lib/api/endpoints.py` | Thread`body.autonomous`through`compile_team_graph` |
| `lib/protocols/mcp/server.py` | Implement all three tools with real`async def`+`httpx.AsyncClient` |
| `lib/core/tests/test_graph.py` | Tests for autonomous/supervised compile paths |
| `lib/core/tests/test_aggregator.py` | Tests for interrupt detection in`ingest()` |
| `lib/api/tests/test_endpoints.py` | Tests for`autonomous`field |
| `lib/protocols/mcp/tests/test_server.py` | New file — MCP tool tests with httpx mock |

---

## Implementation Steps

### Step 1 — Settings:`api_base_url`

`lib/core/config.py`:

```python
api_base_url: str = Field(
    default="http://localhost:8000",
    description="Base URL of this server; used by MCP tools for loopback calls.",
)
```

---

### Step 2 — `compile_team_graph`: eliminate `interrupt_before`, add `autonomous`

`lib/core/graph.py`:

```python
def compile_team_graph(
    team_config: TeamConfig,
    agent_configs: dict[str, AgentConfig],
    checkpointer: AsyncSqliteSaver | None = None,
    supervisor_agent_config: AgentConfig | None = None,
    workspace_root: Path | None = None,
    autonomous: bool = False,          # NEW
) -> Any:
    ...
    # interrupt_before is removed: approval flows exclusively through
    # interrupt() inside the node via permission_callback.
    # Pre-node graph interrupts serve no purpose here since there is no
    # human to approve "should this node run?"; the meaningful approval is
    # always at the tool-call level (fs/write_text_file, etc.).
    interrupt_nodes: list[str] = []

    if topology.type == "star":
        _compile_star(..., autonomous=autonomous)
    elif topology.type == "pipeline":
        _compile_pipeline(..., autonomous=autonomous)
    elif topology.type == "pipeline_loop":
        _compile_pipeline_loop(..., autonomous=autonomous)

    return builder.compile(
        checkpointer=checkpointer,
        interrupt_before=interrupt_nodes,   # always []
    )
```

Each `_compile_*`helper receives`autonomous`and passes it to
every`create_worker_node`call.

---

### Step 3 —`create_worker_node`: skip callback in autonomous mode

`lib/core/nodes/worker.py`:

```python
def create_worker_node(
    model: BaseChatModel,
    system_prompt: str,
    name: str,
    autonomous: bool = False,     # NEW
) -> Callable[...]:
    async def worker_node(state: TeamState) -> dict[str, Any]:
        ...
        # In supervised mode: wire interrupt-based approval for ACP-backed models.
        # In autonomous mode: leave permission_callback unwired; AcpChatModel's
        # else-branch auto-approves with the first option.
        if not autonomous and hasattr(model, "permission_callback"):
            model.permission_callback = _interrupt_permission_callback
        response = await model.ainvoke(messages)
        ...
```

---

### Step 4 — Aggregator: extend protocol + interrupt detection

`lib/core/aggregator.py`:

### 4a. Extend `_StreamableGraph` protocol

```python
class _StreamableGraph(Protocol):
    def astream_events(
        self, graph_input, config, *, version: str,
    ) -> AsyncIterator[dict[str, Any]]: ...

    async def aget_state(self, config: dict[str, Any]) -> Any: ...
```

### 4b. Module-level ACP option kind mapper (before EventAggregator class)

```python
def _map_acp_option_kind(option_id: str) -> PermissionOptionKind:
    oid = option_id.lower()
    if "always" in oid and ("deny" in oid or "reject" in oid):
        return PermissionOptionKind.REJECT_ALWAYS
    if "always" in oid:
        return PermissionOptionKind.ALLOW_ALWAYS
    if "deny" in oid or "reject" in oid:
        return PermissionOptionKind.REJECT_ONCE
    return PermissionOptionKind.ALLOW_ONCE
```

### 4c. New private method `_emit_interrupt_events`

```python
async def _emit_interrupt_events(
    self,
    thread_id: str,
    agent_id: str,
    graph: _StreamableGraph,
    config: dict[str, Any],
) -> None:
    """Inspect graph state after astream_events ends; emit PermissionRequestEvents
    for any pending interrupt() calls (tool-level approval requests)."""
    try:
        state = await asyncio.wait_for(graph.aget_state(config), timeout=10.0)
    except Exception:
        logger.warning(
            "Could not inspect state for interrupt detection on thread %s", thread_id
        )
        return

    if not state or not getattr(state, "tasks", None):
        return  # Normal completion

    for task in state.tasks:
        if not task.interrupts:
            continue

        for interrupt_obj in task.interrupts:
            payload = getattr(interrupt_obj, "value", interrupt_obj)
            if not isinstance(payload, dict):
                continue
            if payload.get("type") != "permission_request":
                continue

            request_id = f"{thread_id}:{uuid4().hex}"
            tool_name: str = payload.get("tool_name", "unknown")
            acp_options: list[dict] = payload.get("options", [])

            options: list[dict[str, str]] = [
                {
                    "option_id": opt.get("optionId", opt.get("option_id", "allow_once")),
                    "name": opt.get("label", opt.get("name", opt.get("optionId", "Allow"))),
                    "kind": _map_acp_option_kind(
                        opt.get("optionId", opt.get("option_id", ""))
                    ),
                }
                for opt in acp_options
            ]
            if not options:
                options = [
                    {"option_id": "allow_once", "name": "Allow", "kind": PermissionOptionKind.ALLOW_ONCE},
                    {"option_id": "deny_once", "name": "Deny", "kind": PermissionOptionKind.REJECT_ONCE},
                ]

            await self.emit_permission_request(
                thread_id=thread_id,
                agent_id=task.name,
                request_id=request_id,
                description=f"Permission required: {tool_name}",
                options=options,
                tool_call=tool_name,
            )
            await self.emit_agent_status(
                thread_id=thread_id,
                agent_id=task.name,
                node_name=task.name,
                state=AgentLifecycleState.INPUT_REQUIRED,
                detail=f"Awaiting approval for {tool_name}",
            )
```

### 4d. Call from `ingest()`in the`finally` block

```python
finally:
    self._clear_cancel_event(thread_id)
    await self._flush_chunk_buffer(thread_id)
    await self._emit_interrupt_events(thread_id, agent_id, graph, config)  # NEW
    _ingest_duration_histogram.record(
        time.monotonic() - start,
        {"thread_id": thread_id},
    )
```

`_emit_interrupt_events`is safe to call on normal completion —`state.tasks`will
be empty and it returns immediately.

---

### Step 5 — REST:`autonomous` field

`lib/api/schemas/rest.py`:

```python
class CreateThreadRequest(BaseModel):
    title: str | None = None
    initial_message: str
    team_preset: str | None = None
    metadata: ThreadMetadata | None = None
    autonomous: bool = False       # NEW — skip interrupts for headless runs
    provider: Provider | None = None
    model: Model | None = None
```

`lib/api/endpoints.py`— thread into`compile_team_graph`:

```python
graph = compile_team_graph(
    team_config=team_config,
    agent_configs=agent_configs,
    checkpointer=checkpointer,
    supervisor_agent_config=supervisor_config,
    workspace_root=body.metadata.workspace_root if body.metadata else None,
    autonomous=body.autonomous,    # NEW
)
```

---

### Step 6 — MCP server: async real implementation

`lib/protocols/mcp/server.py` — replace all three stubs with async tools:

```python
import httpx
from ...core.config import settings

@mcp.tool()
async def start_thread(initial_message: str, team_preset: str | None = None) -> str:
    """Start a new Vaultspec agent team workflow. Returns immediately with thread_id."""
    preset = team_preset or "coding-star"
    if preset not in _KNOWN_PRESETS:
        return f"Error: Unknown preset {preset!r}. Valid: {', '.join(_KNOWN_PRESETS)}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{settings.api_base_url}/api/threads",
                json={
                    "title": initial_message[:80],
                    "initial_message": initial_message,
                    "team_preset": preset,
                    "autonomous": True,   # MCP launches are always headless
                },
            )
            resp.raise_for_status()
            data = resp.json()
        thread_id = data["thread_id"]
        return (
            f"Thread started: {thread_id}\n"
            f"Preset: {preset}\n"
            f"Monitor: {settings.api_base_url}/\n"
            f"Status: GET {settings.api_base_url}/api/threads/{thread_id}/state"
        )
    except httpx.HTTPStatusError as exc:
        return f"Error {exc.response.status_code}: {exc.response.text[:200]}"
    except httpx.RequestError as exc:
        return f"Connection error (is the server running at {settings.api_base_url}?): {exc}"


@mcp.tool()
async def get_thread_status(thread_id: str) -> str:
    """Query the current status and message count of a thread."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{settings.api_base_url}/api/threads/{thread_id}/state"
            )
            resp.raise_for_status()
            data = resp.json()
        status = data.get("status", "unknown")
        msg_count = len(data.get("messages", []))
        checkpoint = data.get("checkpoint_id") or "none"
        return (
            f"Thread: {thread_id}\n"
            f"Status: {status}\n"
            f"Messages: {msg_count}\n"
            f"Checkpoint: {checkpoint}\n"
            f"Live: ws://{settings.api_base_url.split('://', 1)[-1]}/ws"
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return f"Thread {thread_id!r} not found."
        return f"Error {exc.response.status_code}: {exc.response.text[:200]}"
    except httpx.RequestError as exc:
        return f"Connection error: {exc}"


@mcp.tool()
async def send_message(thread_id: str, message: str) -> str:
    """Send a follow-up message into an existing thread (202 Accepted, async)."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{settings.api_base_url}/api/threads/{thread_id}/messages",
                json={"content": message},
            )
            resp.raise_for_status()
        return f"Message delivered to thread {thread_id}."
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return f"Thread {thread_id!r} not found."
        return f"Error {exc.response.status_code}: {exc.response.text[:200]}"
    except httpx.RequestError as exc:
        return f"Connection error: {exc}"
```

---

### Step 7 — Tests

**`lib/core/tests/test_graph.py`**:

- `test_compile_supervised_no_interrupt_before`: verify
  `interrupt_before=[]`even with coder in supervised mode (nodes run, permission
  via callback only)
-`test_compile_autonomous_no_permission_callback`: compile with
`autonomous=True`, confirm worker model has no `permission_callback`wired
after`worker_node(...)` is invoked once

**`lib/core/tests/test_aggregator.py`**:

- `test_ingest_emits_permission_on_tool_interrupt`: real graph —
  `astream_events`yields nothing,`aget_state`returns a task with
  one`Interrupt(value={type: "permission_request", tool_name:
  "fs/write_text_file", options: [{optionId: "allow_once", label: "Allow"}]})`.
  Assert `PermissionRequestEvent`emitted +`INPUT_REQUIRED`status.
-`test_ingest_no_permission_on_normal_completion`: `aget_state`returns empty
tasks. Assert no`PermissionRequestEvent`.
- `test_ingest_no_permission_on_empty_interrupt_tasks`: `aget_state`returns task
  with`interrupts=()`. Assert no event (guard case).

**`lib/api/tests/test_endpoints.py`**:

- `test_create_thread_autonomous_defaults_to_false`: no `autonomous`field →
  behaves as supervised
-`test_create_thread_autonomous_true_accepted`: `autonomous=True` → 201
response, graph compiled

**`lib/protocols/mcp/tests/test_server.py`** (new):

- `test_start_thread_calls_api`: real httpx call with respx/responder, verify
  URL + body (including `autonomous=True`)
- `test_start_thread_unknown_preset_returns_error`: no HTTP call, returns error
  string
- `test_start_thread_http_error`: simulate 422, returns error string
- `test_start_thread_connection_error`: simulate `RequestError`
- `test_get_thread_status_returns_summary`: real GET intercept, verify fields
  extracted
- `test_get_thread_status_404`: returns "not found" string
- `test_send_message_returns_confirmation`: real POST intercept, 202
- `test_send_message_404`: returns "not found" string

---

## Key Invariants

- `interrupt_before=[]`always — approval is exclusively via`interrupt()`inside
  nodes
-`autonomous=True`→`permission_callback`not wired → AcpChatModel auto-approves
(first option)
-`autonomous=False`→`permission_callback = _interrupt_permission_callback`→
interrupt fires → PermissionRequestEvent emitted to WebSocket
- MCP-launched threads are always`autonomous=True`
- `_emit_interrupt_events`is always in`finally`and is a no-op on normal
  completion
-`respond_to_permission_endpoint`requires no changes
—`Command(resume=option_id)`already handles both cases

## Verification

1.`.venv/Scripts/python -m pytest lib/ -x`— full suite must pass
2. Start server → use MCP Inspector to call`start_thread`→ confirm real
   thread_id returned, graph runs
3. Interactive UI: create thread with`autonomous=False`, confirm permission
   popup appears in control surface when coder writes a file
4. Autonomous thread: no popup, completes without interruption
