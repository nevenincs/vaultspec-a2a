---
name: 'Agent Process Lifecycle'
date: 2026-25-02
type: research
summary: 'Windows-specific process management research covering asyncio subprocess patterns, graceful shutdown, health checks, state machines, and zombie prevention.'
maturity: 30
feature: agent-process-lifecycle
---

# Phase 4 Research: Agent Process Lifecycle Management

**Date:** 2026-02-25
**Type:** Research
**Feature:** coding-teams / control-surface

---

## PART 1: Python Subprocess Management on Windows 11

### 1.1 asyncio.create_subprocess_exec on Windows 11

**ProactorEventLoop is mandatory and default.** On Windows,
`asyncio.create_subprocess_exec`
requires the ProactorEventLoop (which uses Windows I/O Completion Ports — IOCP).
Since
Python 3.8, ProactorEventLoop has been the default on Windows, so no special
configuration
is needed with Python 3.13.

### Key facts for Python 3.13 on Windows

- ProactorEventLoop is the only event loop that supports subprocesses on
  Windows.
  SelectorEventLoop has zero subprocess support.
- The `asyncio.WindowsProactorEventLoopPolicy`is deprecated as of Python 3.12
  and
  scheduled for removal in 3.16. The future-proof approach is to
  use`asyncio.Runner`
  with a `loop_factory`argument if you ever need to customize the event loop.
- For Python 3.13 on Windows, just use`asyncio.run()`— it picks
  ProactorEventLoop
  automatically.

### Known limitations

-`asyncio.create_subprocess_exec`historically only works from the **main
thread** on
Windows (see [cpython#79816](https://github.com/python/cpython/issues/79816)).
This
is a long-standing limitation. If you need to spawn subprocesses from worker
threads,
you must delegate back to the main thread's event loop.

- 2025 benchmarks show ProactorEventLoop achieves 1.2M msgs/sec throughput and
  18ms p99
  latency, scaling near-linearly up to 128 cores.

**Recommendation:** Use`asyncio.create_subprocess_exec` directly from the main
asyncio
event loop. Do not attempt subprocess creation from background threads. Use
`subprocess.CREATE_NEW_PROCESS_GROUP` flag to enable proper signal handling to
child
processes.

### 1.2 Stdout/Stderr Capture and Real-Time WebSocket Streaming

**The pattern:** Pipe stdout/stderr from async subprocess, read line-by-line in
an asyncio
task, and forward each line to connected WebSocket clients.

```text
Agent subprocess
  stdout=PIPE ──> asyncio readline task ──> broadcast to WebSocket clients
  stderr=PIPE ──> asyncio readline task ──> broadcast to WebSocket clients
```

### How the Claude Agent SDK does it (reference implementation)

The `SubprocessCLITransport` in
`knowledge/repositories/claude-agent-sdk/src/claude_agent_sdk/_internal/transport/subprocess_cli.py`
uses `anyio`(which wraps asyncio) to manage subprocess I/O:

- Opens process with`anyio.open_process(cmd, stdin=PIPE, stdout=PIPE,
stderr=PIPE)`
- Wraps stdout/stderr in `TextReceiveStream` for async iteration
- Spawns a dedicated task (`_handle_stderr`) in a `TaskGroup`to read stderr
  concurrently
- Reads stdout in a streaming JSON parser loop with buffer accumulation
- Uses`anyio.Lock`for write serialization to stdin

### Key considerations for our WebSocket relay

1. **Line buffering vs block buffering:** When a subprocess's stdout is
   connected to a
   pipe (not a terminal), Python and most C runtimes switch to block buffering.
   This means
   output may not appear in real-time. Mitigation strategies:
   - For Python subprocesses: use`-u`flag or`PYTHONUNBUFFERED=1`env var
   - For Uvicorn specifically: set`PYTHONUNBUFFERED=1`in the subprocess
     environment
   - Alternatively, use`process.stdout.readline()`in a loop rather than`read()`

1. **Avoid `communicate()`** — it waits for the process to finish. Instead, use
   the
   `process.stdout`and`process.stderr` `StreamReader`objects directly for
   real-time
   streaming.

1. **Concurrent reading pattern:**

```python
 # Pseudocode — do NOT implement yet
 async def stream_output(process, websocket_broadcast):
     async def read_stream(stream, stream_name):
         while True:
             line = await stream.readline()
             if not line:
                 break
             await websocket_broadcast(stream_name, line.decode())

     async with asyncio.TaskGroup() as tg:
         tg.create_task(read_stream(process.stdout, "stdout"))
         tg.create_task(read_stream(process.stderr, "stderr"))
```

1. **Backpressure:** If WebSocket clients are slow, the relay buffer can grow
   unbounded.
   Consider a bounded queue per WebSocket client, dropping oldest messages if
   the queue
   fills. A ring buffer of recent N lines also helps late-joining clients see
   context.

### 1.3 Graceful Shutdown Patterns for Uvicorn Subprocesses on Windows

**The core problem:** Windows does not have POSIX signals (SIGTERM, SIGINT,
SIGKILL).
Python's `process.terminate()`on Windows calls`TerminateProcess()`, which is the
equivalent of SIGKILL — there is no graceful shutdown opportunity.

### What Uvicorn supports

- Uvicorn handles SIGINT for graceful shutdown: stops accepting new connections,
  finishes
  in-progress requests, then exits.
- On receiving SIGTERM, Uvicorn also initiates graceful shutdown (though
  Docker/container
  environments historically had issues with this).
- Sending two SIGINT/SIGTERM signals forces immediate shutdown.

### Windows-specific shutdown approaches (ranked by preference)

1. **CTRL_BREAK_EVENT (recommended):** Create the subprocess with
   `creationflags=subprocess.CREATE_NEW_PROCESS_GROUP`, then send
   `os.kill(pid, signal.CTRL_BREAK_EVENT)`. This is the closest Windows analog
   to SIGINT
   and Uvicorn will handle it gracefully.

1. **CTRL_C_EVENT:** Use `os.kill(pid, signal.CTRL_C_EVENT)`. However, this
   sends to
   the entire process group and may affect the parent process unless the child
   is in its
   own group (hence `CREATE_NEW_PROCESS_GROUP`).

1. **process.terminate():** Calls `TerminateProcess()` which is immediate and
   ungraceful.
   Use only as a last resort after the graceful approaches time out.

1. **taskkill /T /F /PID {pid}:** The nuclear option. Kills the process AND its
   entire
   process tree. Useful for cleanup when process.terminate() leaves orphaned
   children.

### Recommended shutdown sequence

```text
1. Send CTRL_BREAK_EVENT → wait up to N seconds for graceful exit
2. If still alive: process.terminate() → wait 2 seconds
3. If still alive: taskkill /T /F /PID {pid} (kills entire tree)
4. Always call process.wait() / communicate() afterward to clean up
```

### 1.4 Windows Process Termination: What Actually Works

| Method                                    | What it does                   | Graceful? | Kills children? |
| ----------------------------------------- | ------------------------------ | --------- | --------------- |
| `process.terminate()`                     | Calls`TerminateProcess()`      | No        | No              |
| `process.kill()`                          | Same as`terminate()`on Windows | No        | No              |
| `os.kill(pid, signal.CTRL_BREAK_EVENT)`   | Sends console control event    | Yes       | No              |
| `os.kill(pid, signal.CTRL_C_EVENT)`       | Sends Ctrl+C to process group  | Yes       | Yes (group)     |
| `taskkill /PID {pid}`                     | Sends WM_CLOSE message         | Sometimes | No              |
| `taskkill /F /PID {pid}`                  | Force terminates               | No        | No              |
| `taskkill /T /PID {pid}`                  | Terminates process tree        | Sometimes | Yes             |
| `taskkill /T /F /PID {pid}`               | Force terminates process tree  | No        | Yes             |
| `psutil.Process(pid).children()`+`kill()` | Programmatic tree kill         | No        | Yes (manual)    |

**Recommendation:** Use`psutil` for reliable process tree management. It
provides
`Process.children(recursive=True)`to find all descendants
and`Process.wait()`with
timeout. Fall back to`taskkill /T /F`for cleanup.

### 1.5 Zombie Process Prevention on Windows

Windows does not have Unix-style zombie processes (a zombie is a terminated
process whose
parent hasn't called`wait()`). However, Windows has analogous problems:

- **Orphan processes:** If the parent dies without terminating children,
  children continue
  running indefinitely. This is the primary concern.
- **Handle leaks:** If you don't call `process.wait()`after termination, process
  handles
  accumulate.
- **Event loop finalizer bug:**`BaseSubprocessTransport.__del__`can fail if the
  event
  loop is already closed, leaking orphan processes (see
  [cpython#114177](https://github.com/python/cpython/issues/114177)).

### Prevention strategies

1. **Job Objects:** Create a Windows Job Object and assign all child processes
   to it. When
   the job is closed (or the parent exits), all children are automatically
   terminated.
   This is the most robust approach.

```python
 # Available via pywin32 or ctypes
 import win32job
 job = win32job.CreateJobObject(None, "")
 info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
 info['BasicLimitInformation']['LimitFlags'] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
 win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
 # Assign child processes to this job
```

1. **atexit handler:** Register cleanup that iterates all managed processes and
   terminates
   them.

1. **Structured concurrency:** Use `asyncio.TaskGroup`to ensure all subprocess
   management
   tasks are cancelled if the parent scope exits.

1. **Always`await process.wait()`** after termination to release the process
   handle.

### 1.6 Port Ready Detection

**Problem:** After starting a Uvicorn subprocess, how do you know when it's
actually
listening and ready to accept HTTP requests?

### Approaches

1. **Parse stdout for Uvicorn's startup message:** Uvicorn prints
   `"Uvicorn running on http://..."`when ready. Simple but fragile — message
   format
   could change.

1. **TCP connect probe:** Repeatedly attempt to connect to the target port.

```python
 # Pseudocode
 async def wait_for_port(host, port, timeout=10.0):
     deadline = time.monotonic() + timeout
     while time.monotonic() < deadline:
         try:
             reader, writer = await asyncio.open_connection(host, port)
             writer.close()
             await writer.wait_closed()
             return True
         except (ConnectionRefusedError, OSError):
             await asyncio.sleep(0.1)
     return False
```

1. **HTTP health endpoint probe:** Better than TCP because it confirms the ASGI
   app is
   loaded, not just the socket. Send GET to a
   `/health`or`/.well-known/agent.json`
   endpoint.

1. **Uvicorn startup callback (programmatic only):** When using Uvicorn
   programmatically,
   `server.started`attribute becomes`True` after startup completes. Not usable
   when
   running as a subprocess.

**Recommendation:** Combine stdout parsing (for fast detection) with HTTP health
probe
(for confirmation). The A2A agent card endpoint (`/.well-known/agent.json`)
serves as
a natural health check — if it responds, the agent is fully operational.

### 1.7 Dynamic Port Allocation

### Option A: Find free port, then pass to Uvicorn

```python
import socket
def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]
```

**Risk:** Race condition — between finding the port and Uvicorn binding to it,
another
process could claim it. In practice this is rare but possible.

**Option B: Uvicorn `--port 0`:**
Uvicorn supports `port=0`which lets the OS pick a free port. However,
discovering which
port was assigned requires parsing Uvicorn's stdout output (e.g.,`"Uvicorn
running on 0.0.0.0:{port}"`).

**Option C: Pre-bind socket, pass file descriptor:**
Bind a socket to port 0, extract the assigned port, then pass the socket FD to
Uvicorn.
This is atomic and race-free, but more complex. Uvicorn supports `--fd`flag for
this.

**Recommendation:** Use Option A (find-free-port) for simplicity. The race
condition
window is tiny (microseconds) and for a local development tool this is
acceptable. Keep
a registry of allocated ports to avoid double-allocation within our own process
manager.

---

## PART 2: Agent Hot-Swap and Team Composition

### 2.1 Replacing an Agent While Tasks Are In Flight

**Can you replace an A2A agent at a URL while tasks are in flight?** Technically
you
can point a URL at a new process, but the consequences depend on the A2A task
state:

From the A2A protocol's perspective (per the A2A spec
and`knowledge/repositories/A2A/`):

- **Tasks have state:** `submitted`, `working`, `input-required`, `completed`,
  `failed`,
  `canceled`. Tasks in `working`or`input-required`states have active processing.
- **Task IDs are opaque:** The new agent process has no knowledge of task IDs
  from the
  old process (unless they share a persistent task store).
- **SSE streams break:** If clients are connected via SSE for task updates,
  replacing the
  agent kills those connections. Clients must reconnect.

### What happens to pending tasks

- Tasks in`working`state: **Lost** unless the agent uses persistent task
  storage.
- Tasks in`submitted`but not started: Can be re-submitted to the new agent.
- Tasks in`input-required`: Client loses the dialogue context.

**Conclusion:** Hot-swap is only safe if (a) no tasks are in-flight, or (b) a
shared
persistent task store is used. For our use case (development tool), option (a)
with a
drain period is more practical.

### 2.2 Draining Pattern

The draining pattern lets an agent finish current work before shutting down:

1. **Stop accepting new tasks:** Remove the agent from the router/registry so no
   new
   tasks are sent to it.
2. **Wait for in-flight tasks to complete or timeout:** Monitor the agent's
   active task
   count. Set a maximum drain timeout.
3. **Shut down gracefully:** After drain completes, send shutdown signal.

### Implementation sketch for our system

```text
State: DRAINING
  - Agent is still running and processing current tasks
  - New task requests are routed to the replacement agent (or queued)
  - Control surface polls agent's task list or waits for task completion events
  - After all tasks complete (or drain timeout expires):
    → transition to STOPPING
```

**Drain timeout is essential:** A misbehaving agent could hold tasks
indefinitely. The
control surface must enforce a maximum drain time, after which it force-stops
the agent
and marks remaining tasks as `failed`.

### 2.3 Blue-Green Deployment at the Agent Level

Adapted from infrastructure-level blue-green to agent-level:

1. **Blue (current):** Running agent A v1 on port 8001
2. **Start Green:** Launch agent A v2 on port 8002
3. **Verify Green:** Health check the new agent (agent card, health endpoint)
4. **Switch routing:** Update the agent registry to point A's logical URL to
   port 8002
5. **Drain Blue:** Let in-flight tasks on port 8001 complete
6. **Kill Blue:** Terminate the old process after drain

### For our control surface this translates to

```sql
Current agent "coder" at port 8001 (RUNNING)
  ↓ User requests agent update/replace
Launch new "coder" at port 8002 (STARTING → RUNNING)
  ↓ Health check passes
Update registry: "coder" → port 8002
  ↓ Mark old as DRAINING
Old "coder" at port 8001 (DRAINING → STOPPING → STOPPED)
```

**Key insight for development tool context:** Blue-green is overkill for
single-developer
use but becomes valuable when agents are long-running or have expensive startup
(e.g.,
loading LLM context). The pattern should be _available_ but not _required_ — a
simple
stop-then-start is fine for most cases.

### 2.4 Kubernetes Rolling Update Analogy

Kubernetes rolling updates provide useful conceptual patterns:

| K8s Concept                   | Agent Manager Analog                              |
| ----------------------------- | ------------------------------------------------- |
| Pod                           | Agent subprocess                                  |
| Deployment                    | Agent definition (name, config, model)            |
| ReplicaSet                    | Active instances of an agent definition           |
| readinessProbe                | Health check (HTTP to agent card endpoint)        |
| livenessProbe                 | Process alive check + periodic health HTTP check  |
| terminationGracePeriodSeconds | Drain timeout                                     |
| maxUnavailable                | Minimum agents that must be running during update |
| maxSurge                      | Maximum extra agents allowed during update        |
| preStop hook                  | Drain initiation signal                           |

### Relevant patterns to adopt

- Readiness vs Liveness distinction: An agent can be alive (process running) but
  not
  ready (still loading, or in error state).
- Rolling update with maxSurge=1: Start new before killing old.
- Configurable grace periods per agent type.

### 2.5 Circuit Breaker for Agent Health

Three states: **CLOSED** (normal), **OPEN** (failing, stop routing),
**HALF-OPEN** (testing recovery).

### For agent routing

```text
CLOSED (healthy):
  - Route requests normally
  - Track failures (HTTP errors, timeouts, task failures)
  - If failure count > threshold in time window → trip to OPEN

OPEN (unhealthy):
  - Stop routing new tasks to this agent
  - Return error or queue tasks for other agents
  - After cooldown period → transition to HALF-OPEN

HALF-OPEN (testing):
  - Route ONE request to the agent
  - If success → CLOSED
  - If failure → OPEN (reset cooldown)
```

### Configuration recommendations

- `fail_max`: 3 consecutive failures (not cumulative)
- `reset_timeout`: 15 seconds for development tool (short since we want fast
  recovery)
- Track: HTTP 5xx responses, connection refused, response timeouts > 30s
- Do NOT trip on: LLM-level errors (those are task failures, not agent health
  failures)

**Python libraries:** `pybreaker`(decorator-based, simple) or`circuitbreaker`
(similar).
Both are lightweight and asyncio-compatible.

---

## PART 3: MCP Permission Management at Runtime

### 3.1 Can MCP Tool Permissions Be Changed at Runtime?

**Yes — MCP supports dynamic tool changes at runtime.** The MCP specification
includes
a notification mechanism (`notifications/tools/list_changed`) that servers send
to clients
when available tools change. Clients then re-fetch the tool list. This means:

- Tools can be added or removed at runtime without server restart
- Clients detect changes and update their available tool lists
- The server controls what tools are available; the client discovers them

**However**, the MCP spec itself does not define a permission/authorization
layer for
tools. Permissions are implemented at the application level — in our case, by
the Claude
Agent SDK's permission model or the ACP SDK's permission broker.

### 3.2 Claude Agent SDK Permission Model

From `knowledge/repositories/claude-agent-sdk/src/claude_agent_sdk/types.py`:

**PermissionMode** (set at agent startup, governs the overall stance):

```python
PermissionMode = Literal["default", "acceptEdits", "plan", "bypassPermissions"]
```

| Mode                  | Behavior                                           |
| --------------------- | -------------------------------------------------- |
| `"default"`           | Ask for permission on dangerous operations         |
| `"acceptEdits"`       | Auto-allow file edits, ask for other dangerous ops |
| `"plan"`              | Agent plans but does not execute (read-only)       |
| `"bypassPermissions"` | Allow everything without asking                    |

**CanUseTool callback** (invoked at runtime per tool call):

```python
CanUseTool = Callable[
    [str, dict[str, Any], ToolPermissionContext],
    Awaitable[PermissionResult]
]
```

This callback receives:

- `tool_name`: The tool being invoked (e.g., "Bash", "Edit", "Write")
- `input_data`: The tool's input parameters (e.g., file path, command)
- `context`: Contains `suggestions`(list of`PermissionUpdate`objects)

And returns either:

-`PermissionResultAllow(updated_input=...)`— allow, optionally modify input -`PermissionResultDeny(message=...)` — deny with reason

**PermissionUpdate** (runtime permission changes):

```python
@dataclass
class PermissionUpdate:
    type: Literal["addRules", "replaceRules", "removeRules",
                   "setMode", "addDirectories", "removeDirectories"]
    rules: list[PermissionRuleValue] | None = None
    behavior: PermissionBehavior | None = None  # "allow" | "deny" | "ask"
    mode: PermissionMode | None = None
    directories: list[str] | None = None
    destination: PermissionUpdateDestination | None = None
```

**Key insight:** The `CanUseTool` callback is invoked **per tool call at
runtime**.
This means a web UI can dynamically change what's allowed by updating the
callback's
decision logic. The callback does not need to be static — it can consult a
database,
in-memory config, or API to make decisions.

**The SDK also supports runtime permission mode changes** via the
`SDKControlSetPermissionModeRequest` control message:

```python
class SDKControlSetPermissionModeRequest(TypedDict):
    subtype: Literal["set_permission_mode"]
    mode: str
```

### 3.3 ACP SDK Permission Model

From
`knowledge/repositories/acp-python-sdk/src/acp/contrib/permissions.py`and`schema.py`:

**PermissionOption** (what the user sees):

```python
PermissionOptionKind = Literal["allow_once", "allow_always", "reject_once", "reject_always"]

class PermissionOption(BaseModel):
    kind: PermissionOptionKind
    name: str        # Human-readable label
    option_id: str   # Unique identifier
```

### Default permission options

```python
("Approve", "allow_once"),
("Approve for session", "allow_always"),
("Reject", "reject_once")
```

**PermissionBroker** — the runtime permission handler:

- Constructed with a `session_id`and an async`requester`callback
- The`request_for()` method issues a permission request for a specific tool call
- Presents options to the user and returns their decision
- Supports custom options per request (override defaults)

### RequestPermissionResponse

```python
class RequestPermissionResponse(BaseModel):
    outcome: DeniedOutcome | AllowedOutcome
```

The ACP model is inherently runtime-dynamic — each tool call triggers a
permission
request that goes through the broker to the user (or an automated policy).

### 3.4 Web UI Permission Design

### How a web UI should expose per-agent tool permissions

**Tier 1: Agent-Level Permission Mode** (simple toggle per agent)

```text
Agent: "coder"
  Permission Mode: [default ▼]  (default | acceptEdits | plan | bypassPermissions)
```

**Tier 2: Tool-Level Allow/Deny Rules** (per agent)

```text
Agent: "coder"
  Tools:
    ☑ Bash       [allow ▼]  Rule: "only in project directory"
    ☑ Edit       [allow ▼]  Rule: "*.py, *.ts files only"
    ☑ Write      [ask   ▼]  Rule: —
    ☐ WebFetch   [deny  ▼]  Rule: —
    ☑ Read       [allow ▼]  Rule: —
```

**Tier 3: Directory Scope** (per agent)

```text
Agent: "coder"
  Allowed Directories:
    + Y:/code/vaultspec-worktrees/main
    + Y:/code/vaultspec-a2a-worktrees/main
    - Y:/code/secret-project  (blocked)
```

### Recommended granularity for our use case

| Level                       | Description              | Complexity | Recommendation |
| --------------------------- | ------------------------ | ---------- | -------------- |
| Per-agent permission mode   | 4 modes                  | Low        | Must have      |
| Per-tool allow/deny         | Toggle per tool name     | Medium     | Must have      |
| Per-tool with content rules | Regex/glob on tool input | High       | Nice to have   |
| Per-directory scope         | Allowed working dirs     | Medium     | Must have      |
| Per-file-operation          | Read vs write vs delete  | High       | Defer          |

**Implementation approach:** The `CanUseTool` callback in the Claude Agent SDK
is the
natural integration point. The web UI updates an in-memory permission
configuration. The
callback consults this configuration on every tool call. Changes take effect
immediately
— no agent restart required.

---

## PART 4: Process State Machine

### 4.1 Supervisord Process State Machine (Reference)

Supervisord defines the most well-established process lifecycle model:

```text
            ┌──────────────────────────────────────────────────────┐
            │                                                      │
            v                                                      │
  STOPPED ──→ STARTING ──→ RUNNING ──→ EXITED                     │
     ^          │   ^         │          │                         │
     │          │   │         │          └─── (autorestart) ───────┘
     │          v   │         v
     │       BACKOFF │     STOPPING ──→ STOPPED
     │          │    │
     │          │    └──── (retry)
     │          v
     │       FATAL
     │          │
     └──── (manual restart)
```

### States

| State    | Code | Description                                                     |
| -------- | ---- | --------------------------------------------------------------- |
| STOPPED  | 0    | Never started, or stopped by admin                              |
| STARTING | 10   | Start requested, process launched but not yet confirmed running |
| RUNNING  | 20   | Process confirmed running (survived `startsecs`threshold)       |
| BACKOFF  | 30   | Start attempt failed, waiting to retry                          |
| STOPPING | 40   | Stop requested, waiting for process to exit                     |
| EXITED   | 100  | Exited from RUNNING state (expected or unexpected)              |
| FATAL    | 200  | Could not start after all retries exhausted                     |
| UNKNOWN  | 1000 | Supervisor lost track of process                                |

### Key configuration parameters

-`startsecs`: How long process must run after start to be considered RUNNING
(default: 1)

- `startretries`: Max retries before FATAL (default: 3)
- `stopwaitsecs`: Timeout for graceful stop before SIGKILL (default: 10)
  | - `autorestart`: `true` | `false` | `"unexpected"`(restart on unexpected exit
  codes) | -`exitcodes`: List of "expected" exit codes (default: [0])

**Retry backoff:** Linear: 1s, 2s, 3s, ... up to `startretries`.

### 4.2 PM2 Process Model (Reference)

PM2 process states (simplified from its internal model):

| State             | Description                        |
| ----------------- | ---------------------------------- |
| online            | Process is running normally        |
| stopping          | Graceful stop in progress          |
| stopped           | Process stopped (manual or exit 0) |
| launching         | Process starting up                |
| errored           | Process exited with error          |
| one-launch-status | One-shot process (no restart)      |

### PM2 restart strategies

| Strategy            | Trigger          | Configuration                    |
| ------------------- | ---------------- | -------------------------------- |
| Auto-restart        | On crash/exit    | Default behavior                 |
| Cron restart        | Time-based       | `cron_restart: "0 0 * * *"`      |
| Memory limit        | Memory threshold | `max_memory_restart: "200M"`     |
| File watch          | File changes     | `watch: true`                    |
| Exponential backoff | Repeated crashes | `exp_backoff_restart_delay: 100` |
| No restart          | One-shot script  | `autorestart: false`             |

### PM2 Exponential backoff details

- Base delay configurable (e.g., 100ms)
- Increases exponentially up to max 15,000ms (15s)
- Resets to 0ms after 30 seconds of stable uptime
- Process shows "waiting restart" status during backoff

### PM2 Graceful shutdown

1. Sends SIGINT first
2. If process doesn't exit within 1.6 seconds, sends SIGKILL
3. Customizable via`kill_timeout` parameter

### 4.3 Recommended State Machine for Agent Process Manager

Combining insights from supervisord and PM2, adapted for A2A agent processes on
Windows:

```text
                    ┌────────────── (user restart) ──────────────┐
                    │                                             │
                    v                                             │
  CREATED ──→ STARTING ──→ READY ──→ RUNNING                    │
                 │   ^                   │                        │
                 │   │                   ├──→ DRAINING ──→ STOPPING ──→ STOPPED
                 │   │                   │                    ^
                 v   │                   v                    │
              BACKOFF │               EXITED ─── (auto) ─────┘
                 │    │                  │
                 │    └── (retry) ──────┘
                 v
              FATAL
```

### States for our agent process manager

| State    | Description                                  | Exit conditions                                                                  |
| -------- | -------------------------------------------- | -------------------------------------------------------------------------------- |
| CREATED  | Agent definition loaded, not yet started     | → STARTING (on start command)                                                    |
| STARTING | Process launched, waiting for port ready     | → READY (health check passes), → BACKOFF (process exits or health check timeout) |
| READY    | Port is listening, agent card accessible     | → RUNNING (first successful A2A interaction or after readiness delay)            |
| RUNNING  | Fully operational, accepting tasks           | → DRAINING (on replace/update), → STOPPING (on stop), → EXITED (unexpected exit) |
| DRAINING | Finishing in-flight tasks, not accepting new | → STOPPING (drain complete or timeout)                                           |
| STOPPING | Shutdown signal sent, waiting for exit       | → STOPPED (process exited), → STOPPED (force kill after timeout)                 |
| STOPPED  | Process not running, clean exit              | → STARTING (on restart)                                                          |
| EXITED   | Unexpected process exit                      | → BACKOFF (if autorestart), → STOPPED (if no autorestart)                        |
| BACKOFF  | Waiting before retry                         | → STARTING (after delay), → FATAL (retries exhausted)                            |
| FATAL    | Cannot start, manual intervention required   | → STARTING (manual restart only)                                                 |

### 4.4 Restart Policies

```python
# Conceptual — do NOT implement yet
@dataclass
class RestartPolicy:
    mode: Literal["always", "on_failure", "never"] = "on_failure"
    max_retries: int = 3
    backoff_base_ms: int = 1000       # Starting delay
    backoff_max_ms: int = 30000       # Maximum delay
    backoff_multiplier: float = 2.0   # Exponential factor
    stable_threshold_s: float = 30.0  # Uptime before resetting retry count
```

### Backoff calculation

```text
delay = min(backoff_base_ms * (backoff_multiplier ^ retry_count), backoff_max_ms)
```

With defaults: 1s, 2s, 4s (then FATAL if max_retries=3).

**Stability reset:** If a process runs for longer than `stable_threshold_s`after
a
restart, reset the retry counter to 0. This matches PM2's behavior and prevents
a
process that occasionally crashes after hours of uptime from accumulating
retries.

### 4.5 Health Check Patterns

### Layer 1: Process Alive

- Check`process.returncode is None`
- Frequency: Every 1 second
- Failure: Process has exited → transition to EXITED

### Layer 2: Port Listening (TCP)

- Attempt TCP connection to agent's port
- Frequency: Every 5 seconds (or on startup, every 100ms)
- Failure: Port not reachable after N checks → mark unhealthy

### Layer 3: HTTP Health (Application)

- GET `http://localhost:{port}/.well-known/agent.json`
- Frequency: Every 10 seconds
- Failure: Non-200 response or timeout → mark unhealthy
- This confirms the ASGI app is loaded and the A2A stack is functional

### Layer 4: Task Health (Operational)

- Track task success/failure ratio over a sliding window
- If >50% of tasks fail in last 5 minutes → trip circuit breaker
- This catches "running but broken" agents (e.g., LLM API key expired)

---

## Summary of Recommendations for Windows 11 / Python 3.13

### Subprocess Management

1. Use `asyncio.create_subprocess_exec`with`CREATE_NEW_PROCESS_GROUP`flag
2. Use`PYTHONUNBUFFERED=1`for Uvicorn subprocesses
3. Read stdout/stderr with dedicated asyncio tasks, relay to WebSocket via
   bounded queues
4. Graceful shutdown:`CTRL_BREAK_EVENT`→`terminate()`→`taskkill /T /F`
5. Use Windows Job Objects for automatic orphan cleanup (via `pywin32`)

### Agent Hot-Swap

1. Implement drain pattern with configurable timeout per agent type
2. Blue-green available but not required — simple stop/start is default
3. Circuit breaker on agent health (3 failures, 15s cooldown)

### Permission Management

1. Use Claude Agent SDK's `CanUseTool`callback for runtime permission control
2. Web UI exposes: permission mode per agent, tool-level allow/deny, directory
   scope
3. Changes take effect immediately — no agent restart needed
4. ACP SDK's`PermissionBroker`provides an alternative pattern with user-facing
   options

### Process State Machine

1. 10-state model: CREATED → STARTING → READY → RUNNING → DRAINING → STOPPING →
   STOPPED
   (plus EXITED, BACKOFF, FATAL)
2. Restart policies: always, on_failure, never — with exponential backoff
3. Four-layer health checks: process alive, TCP port, HTTP health, task success
   rate
4. Stability threshold resets retry count after 30s of uptime

---

## Sources

### Part 1: Subprocess Management

- [Platform Support — Python 3.14
  docs](https://docs.python.org/3/library/asyncio-platforms.html)
- [Subprocesses — Python 3.14
  docs](https://docs.python.org/3/library/asyncio-subprocess.html)
- [Asyncio Windows: Python Proactor Loop
  2025](https://www.johal.in/asyncio-windows-python-proactor-loop-2025/)
- [asyncio.create_subprocess_exec main thread issue —
  cpython#79816](https://github.com/python/cpython/issues/79816)
- [BaseSubprocessTransport.**del** orphan leak —
  cpython#114177](https://github.com/python/cpython/issues/114177)
- [Python Subprocess Termination
  Strategies](https://sqlpey.com/python/python-subprocess-termination-strategies/)
- [How to kill child processes on
  Windows](https://gist.github.com/jizhilong/6687481)
- [Subprocess management — Python 3.14
  docs](https://docs.python.org/3/library/subprocess.html)
- [TerminateProcess via os.kill on Windows —
  discuss.python.org](https://discuss.python.org/t/terminateprocess-via-os-kill-on-windows/30882)

### Part 1: Uvicorn Shutdown and Port Allocation

- [Uvicorn graceful shutdown PR#853](https://github.com/encode/uvicorn/pull/853)
- [Uvicorn Process Management —
  DeepWiki](https://deepwiki.com/encode/uvicorn/4.2-process-management)
- [Uvicorn Settings](https://www.uvicorn.org/settings/)
- [Starting and Stopping uvicorn in the
  Background](https://bugfactory.io/articles/starting-and-stopping-uvicorn-in-the-background/)
- [How to Avoid Port Conflicts —
  BugFactory](https://bugfactory.io/articles/how-to-avoid-conflicts-and-let-your-os-select-a-random-port/)
- [Stream subprocess output with
  asyncio](https://gist.github.com/gh640/50953484edfa846fda9a95374df57900)

### Part 2: Deployment Patterns

- [Rolling vs Blue-Green Deployments —
  Harness](https://www.harness.io/blog/difference-between-rolling-and-blue-green-deployments)
- [What is Blue-Green Deployment — Red
  Hat](https://www.redhat.com/en/topics/devops/what-is-blue-green-deployment)
- [Circuit Breaker Pattern in Microservices —
  GeeksforGeeks](https://www.geeksforgeeks.org/system-design/what-is-circuit-breaker-pattern-in-microservices/)
- [Implementing Circuit Breaker in
  FastAPI](https://blog.stackademic.com/system-design-1-implementing-the-circuit-breaker-pattern-in-fastapi-e96e8864f342)
- [pybreaker — GitHub](https://github.com/danielfm/pybreaker)
- [circuitbreaker — PyPI](https://pypi.org/project/circuitbreaker/)

### Part 3: MCP Permissions

- [Dynamic Tool Updates in Spring AI
  MCP](https://spring.io/blog/2025/05/04/spring-ai-dynamic-tool-updates-with-mcp/)
- [MCP Permissions —
  Cerbos](https://www.cerbos.dev/blog/mcp-permissions-securing-ai-agent-access-to-tools)
- [MCP Authorization — Cerbos](https://www.cerbos.dev/blog/mcp-authorization)
- [Dynamic MCP Server —
  GitHub](https://github.com/scitara-cto/dynamic-mcp-server)
- [MCP Architecture
  Overview](https://modelcontextprotocol.io/docs/learn/architecture)

### Part 4: Process Lifecycle

- [Supervisord Subprocess States](https://supervisord.org/subprocess.html)
- [Supervisord Configuration](https://supervisord.org/configuration.html)
- [Supervisord Events](https://supervisord.org/events.html)
- [PM2 Process
  Management](https://pm2.keymetrics.io/docs/usage/process-management/)
- [PM2 Restart
  Strategies](https://pm2.keymetrics.io/docs/usage/restart-strategies/)
- [PM2 Graceful
  Shutdown](https://pm2.keymetrics.io/docs/usage/signals-clean-restart/)
- [Complete Guide to PM2 —
  AppSignal](https://blog.appsignal.com/2022/03/09/a-complete-guide-to-nodejs-process-management-with-pm2.html)

### Repository References (Local Knowledge)

-`knowledge/repositories/claude-agent-sdk/src/claude_agent_sdk/types.py`—
PermissionMode, CanUseTool, PermissionUpdate -`knowledge/repositories/claude-agent-sdk/src/claude_agent_sdk/_internal/transport/subprocess_cli.py`—
Subprocess management reference -`knowledge/repositories/claude-agent-sdk/examples/tool_permission_callback.py`—
Permission callback example -`knowledge/repositories/acp-python-sdk/src/acp/contrib/permissions.py`—
PermissionBroker, PermissionOption -`knowledge/repositories/acp-python-sdk/src/acp/schema.py`—
PermissionOptionKind, RequestPermissionRequest/Response -`knowledge/repositories/acp-python-sdk/src/acp/task/state.py` —
MessageStateStore pattern
