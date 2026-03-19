---
name: 'Process Domain - Distilled'
date: 2026-25-02
type: distilled
summary: 'Consolidated process lifecycle management: Windows subprocess patterns, graceful shutdown sequences, state machine design, health checks, restart policies, permission management, and monitoring architecture.'
maturity: 40
sources:
  - docs/process/2026-25-02-agent-process-lifecycle-research.md
  - docs/process/2026-25-02-coding-teams-monitoring-research.md
feature: process-distilled
---

# Process Domain — Distilled

> [!WARNING]
> **PARTIAL DEPRECATION NOTICE: LANGGRAPH MIGRATION (2026-02-26)**
> The _orchestration-level_ process management strategies (spawning independent
> agent processes, pywin32 Job Objects for the orchestrator, CTRL_BREAK_EVENT
> signalling) have been superseded by native LangGraph coroutines running within
> the Uvicorn event loop.
>
> **Section 1 (Subprocess Management) remains binding** for `AcpChatModel`,
> which still spawns real CLI subprocesses (node.exe / gemini) as stdio pipes.
> The Windows orphan problem, process-tree teardown patterns, and handle-leak
> prevention described here directly apply to that layer.
>
> Sections 2–5 (State Machine, Hot-Swap, etc.) are historical context only.
> See ADR-001 for the current architecture.

**Date**: 2026-02-25
**Status**: Distilled from process lifecycle + monitoring research
**Scope**: Agent subprocess management on Windows 11 with Python 3.13

---

## 1. Subprocess Management on Windows

### 1.1 Event Loop

ProactorEventLoop is mandatory and default for subprocesses on Windows. Python
3.13 uses it automatically via `asyncio.run()`. No special configuration needed.

**Critical constraint**: `asyncio.create_subprocess_exec` only works from the
**main thread** on Windows (long-standing cpython limitation). Subprocess
creation from worker threads must delegate back to the main event loop.

### 1.2 Stdout/Stderr Relay

```text
Agent subprocess
  stdout=PIPE ──→ asyncio readline task ──→ broadcast to WebSocket clients
  stderr=PIPE ──→ asyncio readline task ──→ broadcast to WebSocket clients
```text

### Key considerations

- Set `PYTHONUNBUFFERED=1`on Uvicorn subprocesses (pipe-connected stdout
  switches to block buffering otherwise)
- Use`process.stdout.readline()`in a loop, never`communicate()`(which waits
  for process exit)
- Spawn dedicated asyncio tasks per stream (stdout, stderr) via`TaskGroup`
- Implement bounded queue per WebSocket client with oldest-message-drop for
  backpressure
- Keep a ring buffer of recent N lines for late-joining clients

**Reference**: Claude Agent SDK's `SubprocessCLITransport`uses`anyio` with
`TextReceiveStream`and`TaskGroup`for concurrent stdout/stderr reading.

### 1.3 Graceful Shutdown Sequence

Windows lacks POSIX signals.`process.terminate()`calls`TerminateProcess()`
(equivalent to SIGKILL — no graceful shutdown).

### Recommended shutdown sequence

```text
1. Send CTRL_BREAK_EVENT      → wait up to N seconds for graceful exit
2. If still alive: terminate() → wait 2 seconds
3. If still alive: taskkill /T /F /PID {pid}  (kills entire tree)
4. Always: await process.wait()  to release handle
```yaml

**Prerequisite**: Create subprocess with
`creationflags=CREATE_NEW_PROCESS_GROUP`
to enable `CTRL_BREAK_EVENT`delivery.

### 1.4 Windows Process Termination Methods

| Method                                    | Graceful? | Kills children?                  |
| ----------------------------------------- | --------- | -------------------------------- |
| `os.kill(pid, signal.CTRL_BREAK_EVENT)`   | Yes       | No                               |
| `os.kill(pid, signal.CTRL_C_EVENT)`       | Yes       | Yes (group) — but affects parent |
| `process.terminate()`                     | No        | No                               |
| `taskkill /T /F /PID {pid}`               | No        | Yes                              |
| `psutil.Process(pid).children() + kill()` | No        | Yes (manual)                     |

Use`psutil` for reliable process tree management (`children(recursive=True)`).

### 1.5 Orphan Prevention

Windows doesn't have Unix zombies but has **orphan processes**: if the parent
dies or calls `process.terminate()`without killing the full tree, children
survive indefinitely. For`AcpChatModel` the tree is:

```text
python.exe (uvicorn)
  └─ cmd.exe               ← process.pid points here
       └─ node.exe         ← actual claude-agent-acp worker
            └─ ...         ← any grandchildren
```text

`process.terminate()`and`process.kill()`both call`TerminateProcess()`on
**cmd.exe only**. node.exe and its descendants become orphans.

### Primary defense:`taskkill /T /F /PID {pid}`

```python
# Kills the entire process tree rooted at pid — cmd.exe + node.exe + children
killer = await asyncio.create_subprocess_exec(
    "taskkill", "/T", "/F", "/PID", str(process.pid),
    stdout=asyncio.subprocess.DEVNULL,
    stderr=asyncio.subprocess.DEVNULL,
)
await asyncio.wait_for(killer.wait(), timeout=5.0)
```text

This is implemented in `src/vaultspec_a2a/providers/acp_chat_model._kill_process_tree`and
mirrored in`src/vaultspec_a2a/providers/probes/_protocol._kill_process_tree`.

### Spawn-time isolation: `CREATE_NEW_PROCESS_GROUP`

```python
process = await asyncio.create_subprocess_shell(
    subprocess.list2cmdline(command),
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
    ...
)
```text

Prevents Ctrl+C in the parent terminal from propagating into the subprocess
group, avoiding unintended partial teardown.

### Always close the asyncio transport after process exit

```python
transport = getattr(process, "_transport", None)
if transport is not None:
    transport.close()
```text

Prevents OS handle leaks when the event loop finalizer runs on an already-closed
loop (cpython#114177).

**Windows Job Objects** (pywin32): evaluated but not used. `taskkill /T /F`
achieves the same outcome with no additional dependencies. pywin32 compatibility
with Python 3.13 is unverified. Job Objects remain a viable escalation path.

### 1.6 Port Allocation

Use find-free-port for simplicity:

```python
def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]
```text

Race condition window is microseconds — acceptable for local dev tool. Keep a
registry of allocated ports to avoid double-allocation.

### 1.7 Port Ready Detection

Combine fast detection with reliable confirmation:

1. **Parse Uvicorn stdout** for `"Uvicorn running on http://..."`(fast)
2. **HTTP health probe** to`/.well-known/agent.json` (confirms A2A stack
   is fully operational)

---

## 2. Process State Machine

10-state model combining supervisord and PM2 patterns, adapted for Windows:

```sql
                ┌────────────── (user restart) ──────────────┐
                │                                             │
                v                                             │
CREATED ──→ STARTING ──→ READY ──→ RUNNING                    │
               │   ^                   │                      │
               │   │                   ├──→ DRAINING ──→ STOPPING ──→ STOPPED
               │   │                   │                    ^
               v   │                   v                    │
            BACKOFF │               EXITED ─── (auto) ─────┘
               │    │                  │
               │    └── (retry) ──────┘
               v
            FATAL
```text

### 2.1 State Definitions

| State    | Description                              | Transitions                      |
| -------- | ---------------------------------------- | -------------------------------- |
| CREATED  | Definition loaded, not started           | → STARTING                       |
| STARTING | Process launched, awaiting port ready    | → READY, → BACKOFF               |
| READY    | Port listening, agent card accessible    | → RUNNING                        |
| RUNNING  | Fully operational, accepting tasks       | → DRAINING, → STOPPING, → EXITED |
| DRAINING | Finishing in-flight tasks, rejecting new | → STOPPING                       |
| STOPPING | Shutdown signal sent, awaiting exit      | → STOPPED                        |
| STOPPED  | Clean exit, not running                  | → STARTING                       |
| EXITED   | Unexpected process exit                  | → BACKOFF, → STOPPED             |
| BACKOFF  | Waiting before retry                     | → STARTING, → FATAL              |
| FATAL    | Cannot start, manual intervention needed | → STARTING (manual only)         |

### 2.2 Restart Policies

```yaml
mode: "always" | "on_failure" | "never"
max_retries: 3
backoff: 1s → 2s → 4s (exponential, capped at 30s)
stable_threshold: 30s uptime resets retry counter
```text

### 2.3 Health Check Layers

| Layer | Check                                       | Frequency             | Detects              |
| ----- | ------------------------------------------- | --------------------- | -------------------- |
| 1     | `process.returncode is None`                | 1s                    | Process crash        |
| 2     | TCP connect to agent port                   | 5s (100ms at startup) | Port unreachable     |
| 3     | HTTP GET`/.well-known/agent.json`           | 10s                   | App not loaded       |
| 4     | Task success/failure ratio (sliding window) | Continuous            | "Running but broken" |

Layer 4 feeds the circuit breaker (3 failures → OPEN → 15s cooldown →
HALF-OPEN → test one request).

---

## 3. Agent Hot-Swap

### 3.1 Drain Pattern

1. Remove agent from router (no new tasks)
2. Wait for in-flight tasks to complete or drain timeout
3. Send shutdown signal
4. Force-kill after grace period

Drain timeout is essential — misbehaving agents could hold tasks indefinitely.

### 3.2 Blue-Green Swap

Available but not required for v1. Pattern:

```text
Current "coder" at port 8001 (RUNNING)
  → Launch new "coder" at port 8002 (STARTING → READY)
  → Health check passes
  → Update registry: "coder" → port 8002
  → Old at port 8001: DRAINING → STOPPING → STOPPED
```yaml

Default for v1: simple stop-then-start. Blue-green for agents with expensive
startup (LLM context loading).

### 3.3 Hot-Swap Constraints

- Tasks in `WORKING`state are **lost** unless persistent task store is used
- SSE streams break on agent replacement (clients must reconnect) -`INPUT_REQUIRED`tasks lose dialogue context
- Safe swap only when no tasks are in-flight (drain first)

---

## 4. Permission Management

### 4.1 Runtime Permission Control

MCP supports dynamic tool changes via`notifications/tools/list_changed`.
Tools can be added/removed at runtime without restart.

The Claude Agent SDK's `CanUseTool` callback is invoked **per tool call**:

```python
CanUseTool = Callable[
    [str, dict[str, Any], ToolPermissionContext],
    Awaitable[PermissionResult]  # Allow (optionally modify input) or Deny
]
```text

The callback can consult a database, in-memory config, or API. Changes take
effect immediately — no agent restart needed.

### 4.2 Permission Granularity

| Level                     | Description                                   | v1 Priority  |
| ------------------------- | --------------------------------------------- | ------------ |
| Per-agent permission mode | default, acceptEdits, plan, bypassPermissions | Must have    |
| Per-tool allow/deny       | Toggle per tool name                          | Must have    |
| Per-directory scope       | Allowed/blocked working directories           | Must have    |
| Per-tool content rules    | Regex/glob on tool input                      | Nice to have |
| Per-file-operation        | Read vs write vs delete                       | Defer        |

### 4.3 ACP Permission Pattern (Reference)

ACP's `PermissionBroker`provides user-facing options:

- "Approve" (allow_once)
- "Approve for session" (allow_always)
- "Reject" (reject_once)

Blocking RPC: agent`await`s, UI shows modal, user responds, agent resumes.
This is the pattern adopted for our WebSocket permission flow.

---

## 5. Monitoring Architecture

### 5.1 Hierarchical Telemetry Model

Map A2A primitives to observability spans:

| Level | A2A Primitive                                      | Observability Concept             |
| ----- | -------------------------------------------------- | --------------------------------- |
| Trace | `contextId`                                        | The entire multi-agent session    |
| Span  | `taskId`                                           | Individual agent's task lifecycle |
| Event | `TaskStatusUpdateEvent`, `TaskArtifactUpdateEvent` | Granular actions, tool calls      |

### 5.2 Real-Time vs Historical

**Settled position**: Restrict the bespoke UI to **real-time control**
(streaming,
permissions, agent lifecycle). Use standard **OpenTelemetry exports** for
historical debugging and cost analysis. This avoids reinventing observability
infrastructure.

### 5.3 Dashboard UX Requirements (from ecosystem survey)

| Requirement                                            | Source               | v1 Priority |
| ------------------------------------------------------ | -------------------- | ----------- |
| Parallel stream view (agent grid, concurrent updates)  | AgentOps, CrewAI     | Must have   |
| Interactive permission gate (global actionable queue)  | ACP PermissionBroker | Must have   |
| Cost & latency matrix (per-agent token usage)          | Langfuse, CrewAI     | Defer to v2 |
| Time-travel inspector (scrub backward through context) | AgentOps             | Defer to v2 |
| Dependency graph (which agent blocks which)            | CrewAI               | Defer to v2 |

---

## 6. Open Contradictions

### C1: Monitoring Features — Required vs Deferred

The monitoring research lists "time-travel inspector" and "cost & latency
matrix" as dashboard requirements derived from ecosystem analysis. The
architecture v1 scope defers both cost/token tracking and session replay to v2.

**Status**: ✅ Confirmed by ADR-010. The bespoke UI provides real-time control
(streaming, permissions), while historical debugging and cost analysis are fully
delegated to OpenTelemetry backends.

---

## 7. Knowledge Gaps

### G1: pywin32 Reliability on Python 3.13

Windows Job Objects require`pywin32`or raw`ctypes`. The `pywin32` package's
compatibility with Python 3.13 has not been verified.

**Status**: ✅ Resolved — not by elimination, but by a better alternative.
`AcpChatModel`still spawns real CLI subprocesses (node.exe, gemini), so the
Windows orphan problem is live. However,`taskkill /T /F /PID`achieves full
process-tree termination using only Windows builtins — no`pywin32`required.
Job Objects remain a valid escalation path but are not needed for the current
implementation. See §1.5 for the implemented approach.

### G2: Startup Stability Threshold Undefined

The state machine defines STARTING → READY → RUNNING but the threshold for
confirming RUNNING (supervisord's`startsecs`) is not specified. How long must
an agent survive after health check passes to be considered stable? This
affects restart policy behavior.

**Status**: ✅ Obsolete per ADR-001. Process state machines are no longer
applicable. Agent health is implicitly tied to the main Uvicorn process health.
LangGraph natively handles node execution state.

### G3: OpenTelemetry Integration Timing

**Gap**: When do we integrate OpenTelemetry for tracing agent activity?

**Impact**: Tracing complex LLM flows across a distributed architecture is
highly
complex. A blind deployment without tracing is a severe risk.

**Status**: ✅ Resolved by ADR-010. OpenTelemetry is strictly mandated from day
one for tracing all LangGraph node executions and external tool calls.
