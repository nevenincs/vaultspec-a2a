# Subprocess Coordination Patterns for Local Python Tools — 2026-03-08

## Context

VaultSpec A2A runs a 3-process chain: MCP Server -> Gateway -> Worker. This
document researches how production Python tools coordinate multiple subprocess
services, covering port conflicts, shutdown ordering, health-check retry,
and log aggregation.

---

## 1. Port Conflict Prevention

### Problem

When spawning multiple services on fixed ports, a stale process or concurrent
test run may hold the port, causing `OSError: [Errno 98] Address already in
use` (Linux) or `OSError: [WinError 10048]` (Windows).

### Patterns

#### 1.1 Fixed Port with Pre-Check

Check if the port is in use before spawning. If occupied, either fail fast
or attempt to connect (maybe the service is already running).

```python
async def _tcp_port_ready(host: str, port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=0.5,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, TimeoutError):
        return False
```

**Our current approach**: `_check_gateway_health()` checks if the gateway
is already running before spawning. If it is, skip the spawn. This is the
correct pattern for a singleton-service model.

#### 1.2 Dynamic Port Allocation

Bind to port 0, let the OS assign a free port, then communicate it to the
parent process.

```python
import socket

def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
```

**Use case**: Integration tests that need isolated service instances.
Not suitable for production (port must be discoverable by clients).

#### 1.3 Port File / IPC

Write the bound port to a file or pipe after startup. The parent reads it
to discover the actual port.

**Example**: JupyterLab writes connection info to `~/.jupyter/runtime/`.
The parent reads it to know which port to connect to.

**Our current approach**: Fixed ports (8000 gateway, 8001 worker) configured
via settings. This is simpler and sufficient for single-user desktop use.

### Recommendation

Our current approach (fixed ports with pre-check) is correct. For tests,
use dynamic port allocation (`find_free_port()`).

---

## 2. Graceful Shutdown Ordering

### Problem

In a dependency chain (MCP -> Gateway -> Worker), the shutdown order matters.
Killing the gateway before the worker orphans the worker. Killing the worker
before the gateway causes dispatch failures.

### Patterns

#### 2.1 Reverse-Dependency Order (Recommended)

Shut down services in reverse order of their dependency chain:

1. Stop accepting new requests (gateway stops dispatching)
2. Drain in-flight work (worker completes current tasks)
3. Kill worker first (leaf of the dependency chain)
4. Kill gateway (depends on worker being stopped)
5. Kill MCP server (root of the chain)

**Rationale**: The leaf service (worker) has no dependents. Killing it first
ensures no new work is dispatched to a dying process.

#### 2.2 Top-Down Kill (Our Current Approach)

The MCP server kills the gateway (via `taskkill /T /F /PID`), which kills
the entire process tree including the worker.

**Advantage**: Single command, atomic on Windows.
**Disadvantage**: No graceful drain period for in-flight work.

#### 2.3 Signal Cascade

Send SIGTERM to the root (MCP server). Each process catches SIGTERM and
forwards it to its children before exiting.

```
MCP receives SIGTERM
  -> sends SIGTERM to gateway
     -> gateway catches, sends SIGTERM to worker
        -> worker catches, drains work, exits
     -> gateway waits for worker, then exits
  -> MCP waits for gateway, then exits
```

**Advantage**: Each process controls its own cleanup.
**Disadvantage**: Requires signal handling at each level. On Windows,
only SIGTERM/SIGBREAK are available (no SIGINT to child processes).

#### 2.4 Event-Based Coordination

Use an event object (or file/pipe) to signal shutdown:

```python
# Parent sets the event
shutdown_event = asyncio.Event()
shutdown_event.set()

# Child checks the event in its main loop
while not shutdown_event.is_set():
    await process_work()
```

**Advantage**: Clean, non-signal-based.
**Disadvantage**: Requires shared state (event object) between processes.

### Our Current State

- MCP server: `_shutdown_gateway_process()` uses `taskkill /T /F /PID` on
  Windows, `terminate()` + timeout + `kill()` on POSIX
- Gateway: `_shutdown_worker_process()` uses the same pattern
- Worker: `Executor.shutdown()` cancels tasks before exit

### Recommendation

Our top-down kill via `taskkill /T /F /PID` is correct for Windows (kills
entire tree atomically). On POSIX, consider adding a graceful drain period:

1. Gateway sends shutdown signal to worker
2. Worker stops accepting new dispatches
3. Worker waits up to N seconds for in-flight work
4. Worker exits
5. Gateway exits

---

## 3. Health-Check Retry Strategies

### Problem

After spawning a subprocess, the parent must wait for it to become healthy.
Too fast = false negatives (service still starting). Too slow = wasted time.

### Patterns

#### 3.1 Fixed-Interval Polling

```python
while not healthy:
    await asyncio.sleep(1.0)
    healthy = await check_health()
```

**Problem**: 1-second resolution means up to 1s wasted after the service
starts. Sub-second polling wastes CPU.

#### 3.2 Exponential Backoff (Our Current Approach)

```python
interval = 0.1  # Start fast
while not healthy:
    healthy = await check_health()
    await asyncio.sleep(interval)
    interval = min(interval * 1.5, 2.0)  # Cap at 2s
```

**Advantage**: Fast initial detection (<200ms), reduced polling as time
passes.

**Our implementation** (`protocols/mcp/server.py:278-322`):

- `_POLL_INITIAL_INTERVAL = 0.1` (100ms)
- `_POLL_MAX_INTERVAL = 2.0` (2s cap)
- `_POLL_BACKOFF_FACTOR = 1.5` (exponential growth)
- TCP fast-path: skip HTTP check if port not open yet
- Progress logging every 5s

#### 3.3 Readiness File / Pipe

The child writes a readiness signal to a file or pipe when startup is
complete. The parent watches for this signal.

**Example**: systemd uses `sd_notify(READY=1)` for Type=notify services.

**Advantage**: Zero polling overhead, instant detection.
**Disadvantage**: Requires child process modification.

#### 3.4 Process stdout Sentinel

The child prints a sentinel line (e.g., `"Server ready"`) to stdout.
The parent reads stdout and watches for the sentinel.

**Example**: uvicorn prints `"Uvicorn running on http://..."` when ready.

**Advantage**: No protocol changes needed.
**Disadvantage**: Requires stdout capture (PIPE, not DEVNULL), fragile string
matching.

### Recommendation

Our exponential backoff + TCP fast-path is the best practical approach.
It achieves <200ms detection latency without requiring child process
modification. The TCP fast-path optimization is particularly valuable --
it avoids expensive HTTP request setup while the port isn't even open yet.

---

## 4. Log Aggregation Across Processes

### Problem

Three separate processes produce separate log streams. Without aggregation,
debugging requires checking 3 log files or terminals.

### Patterns

#### 4.1 Shared Log File

All processes write to the same log file with process-identifying prefixes.

```python
logging.basicConfig(
    filename="vaultspec.log",
    format="%(asctime)s [%(process)d] %(name)s %(levelname)s %(message)s",
)
```

**Advantage**: Single file to check.
**Disadvantage**: Concurrent file writes can interleave. On Windows, file
locking may cause issues.

#### 4.2 Structured JSON Logging

Each process emits structured JSON to stderr. A parent aggregator collects
and merges.

```python
import json
import sys

handler = logging.StreamHandler(sys.stderr)
handler.setFormatter(JsonFormatter())
```

**Advantage**: Machine-parseable, supports querying/filtering.
**Disadvantage**: Requires custom formatter setup.

#### 4.3 QueueListener (stdlib)

Python's `logging.handlers.QueueListener` aggregates log records from
multiple processes via a `multiprocessing.Queue`.

```python
from logging.handlers import QueueHandler, QueueListener

log_queue = multiprocessing.Queue()
listener = QueueListener(log_queue, console_handler)
listener.start()

# In each child process:
handler = QueueHandler(log_queue)
logging.getLogger().addHandler(handler)
```

**Advantage**: Standard library, thread-safe, process-safe.
**Disadvantage**: Requires `multiprocessing.Queue` (not available with
`asyncio.create_subprocess_exec` since children are independent processes).

#### 4.4 Subprocess stdout/stderr Capture

Capture child stdout/stderr via PIPE and relay to parent's logger.

```python
process = await asyncio.create_subprocess_exec(
    ..., stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
)
async for line in process.stderr:
    logger.info("[worker] %s", line.decode().strip())
```

**Advantage**: No child modification needed.
**Disadvantage**: Requires PIPE (not DEVNULL), adds relay overhead.

### Our Current State

All subprocess spawns use `DEVNULL` for stdout/stderr. Each process
has its own logging configuration. No log aggregation.

### Recommendation

For development, switch subprocess stderr from `DEVNULL` to `PIPE` and
relay to the parent's logger with a process prefix. For production, use
structured JSON logging to a shared file or stdout (for Docker log
collection).

---

## 5. State Management Across Processes

### Patterns

#### 5.1 Shared Database (Our Approach)

SQLite WAL mode allows concurrent reads from multiple processes with
serialized writes. Our gateway and worker share the same SQLite file.

**Status**: Correct for single-user desktop use.

#### 5.2 Shared Memory / Memory-Mapped Files

`multiprocessing.shared_memory` or `mmap` for fast inter-process
communication.

**Not applicable**: Our processes communicate via HTTP IPC, which is
more flexible and debuggable.

#### 5.3 File-Based Locks

Use `fcntl.flock()` (POSIX) or `msvcrt.locking()` (Windows) for
cross-process synchronization.

**Not applicable**: SQLite handles locking internally.

---

## 6. Comparison: Our Approach vs Industry

| Concern | Our Approach | Industry Best Practice | Gap |
|---------|-------------|----------------------|-----|
| Port conflicts | Pre-check via health endpoint | Pre-check or dynamic allocation | None |
| Shutdown order | `taskkill /T /F` (atomic tree kill) | Reverse-dependency with drain | LOW: no drain period |
| Health retry | Exponential backoff + TCP fast-path | Exponential backoff or readiness file | None |
| Log aggregation | DEVNULL (no aggregation) | QueueListener or stdout relay | MED: no cross-process logs |
| State sharing | SQLite WAL | Database or shared memory | None |
| Process identity | PID tracking in spawner | PID + worker_id in heartbeat | None |

### Gaps to Address

1. **MED**: Add log aggregation -- relay subprocess stderr to parent logger
   or use structured JSON logging to a shared file
2. **LOW**: Add graceful drain period on POSIX shutdown (worker completes
   in-flight work before exit)

---

## 7. Recommendations

| Priority | Recommendation | Rationale |
|----------|---------------|-----------|
| P0 | Keep current exponential backoff + TCP fast-path | Best practical approach for health polling |
| P0 | Keep `taskkill /T /F` on Windows | Atomic process tree kill, no orphans |
| P1 | Add subprocess stderr relay for development | Enables cross-process debugging |
| P1 | Dynamic port allocation for integration tests | Prevents port conflicts in parallel CI |
| P2 | Graceful drain period on POSIX shutdown | Worker completes in-flight work |
| P2 | Structured JSON logging for Docker production | Enables log collection by Docker/k8s |
| P3 | Readiness pipe for instant startup detection | Eliminates polling entirely |

Sources:

- [Python Multiprocessing Graceful Shutdown](https://www.peterspython.com/en/blog/python-multiprocessing-graceful-shutdown-in-the-proper-order)
- [Python subprocess documentation](https://docs.python.org/3/library/subprocess.html)
- [asyncio subprocess documentation](https://docs.python.org/3/library/asyncio-subprocess.html)
- [subprocess-monitor PyPI](https://pypi.org/project/subprocess-monitor/)

---

## 8. FastAPI Graceful Shutdown from Within an Endpoint

### Problem (CLI-I03)

The CLI's `service stop` command needs to shut down the worker. Currently it
tries to POST to `/api/admin/shutdown` on the worker, but the worker has no
such endpoint. We need a way to trigger uvicorn's graceful shutdown sequence
from inside a FastAPI endpoint handler.

### 8.1 How Uvicorn Shutdown Works (Validated from Installed Source)

Verified against `.venv/Lib/site-packages/uvicorn/server.py`.

Uvicorn's `Server` class maintains a boolean flag `should_exit` (line 62).
The main loop at `Server.main_loop()` (lines 234-239) polls `on_tick()` which
checks `self.should_exit` (line 261). When `True`, the server:

1. **Stops accepting new connections** -- closes all server sockets (line 275-278)
2. **Requests shutdown on existing connections** -- calls `connection.shutdown()`
   on each active connection (line 281-282)
3. **Waits for in-flight tasks** -- respects `timeout_graceful_shutdown` config
   (line 287-297)
4. **Sends lifespan shutdown event** -- triggers the ASGI lifespan `shutdown`
   event, which invokes the `finally`/teardown of `@asynccontextmanager`
   lifespan functions (line 300-301)

Signal handling (line 329-346): `handle_exit()` sets `should_exit = True` on
first signal (SIGTERM/SIGINT), sets `force_exit = True` on second SIGINT.

On Windows (line 38-39): SIGTERM, SIGINT, and SIGBREAK are all handled.

### 8.2 Option A: `os.kill(os.getpid(), signal.SIGTERM)` -- BROKEN ON WINDOWS

Send SIGTERM to the current process from within the endpoint handler.

```python
import os
import signal
from fastapi import FastAPI

app = FastAPI()

@app.post("/shutdown")
async def shutdown_endpoint():
    os.kill(os.getpid(), signal.SIGTERM)
    return {"status": "shutting_down"}
```

**How it works on POSIX (Linux/macOS):**

1. Endpoint handler calls `os.kill(os.getpid(), signal.SIGTERM)`
2. Python's signal handler dispatches to `Server.handle_exit()` (line 341)
3. `handle_exit()` sets `self.should_exit = True` (line 346)
4. Endpoint handler returns the 200 response to the caller
5. Server enters graceful shutdown sequence

**BROKEN ON WINDOWS -- VERIFIED BY LIVE TEST:**

```
>>> os.kill(os.getpid(), signal.SIGTERM)
# Process exits immediately with code 15. No handler invoked.
# The registered signal.signal(SIGTERM, handler) is NEVER called.
```

On Windows, `os.kill(pid, SIGTERM)` calls `TerminateProcess()` via the Win32
API. This bypasses all Python signal handlers and kills the process instantly
-- no lifespan shutdown, no connection drain, no cleanup. The 200 response
is never sent.

**Verdict: DO NOT USE.** Not cross-platform. Use Option B instead.

### 8.3 Option B: `signal.raise_signal(signal.SIGTERM)` -- RECOMMENDED (cross-platform)

Available since Python 3.8. We require Python 3.13.

```python
import signal

@app.post("/shutdown")
async def shutdown_endpoint():
    signal.raise_signal(signal.SIGTERM)
    return {"status": "shutting_down"}
```

`signal.raise_signal()` calls the C runtime's `raise()`, which dispatches to
Python's registered signal handler on ALL platforms.

**VERIFIED BY LIVE TEST on Windows 11 (Python 3.13):**

```
>>> import signal
>>> handler_called = False
>>> def handler(signum, frame):
...     global handler_called
...     handler_called = True
>>> signal.signal(signal.SIGTERM, handler)
>>> signal.raise_signal(signal.SIGTERM)
>>> print(handler_called)
True   # Handler invoked, process survives
```

Compare with `os.kill(os.getpid(), SIGTERM)` which exits with code 15 --
no handler invoked, process killed immediately.

**Cross-platform behavior:**

- **Windows:** C `raise()` -> Python signal handler -> uvicorn `handle_exit()`
  -> `should_exit = True` -> graceful shutdown
- **Linux:** C `raise()` -> kernel signal delivery -> Python signal handler ->
  same uvicorn graceful shutdown path
- **macOS:** Same as Linux (POSIX signals)

**Verdict:** This is the only correct cross-platform approach. Use
`signal.raise_signal()` exclusively. Never use `os.kill()` for self-signaling.

### 8.4 Option C: Direct `server.should_exit = True`

Access the uvicorn `Server` instance and set the flag directly.

```python
# Problem: no clean way to access the Server instance from FastAPI
# The Server is created by uvicorn.run(), not by FastAPI
```

**Problem:** FastAPI does not expose the underlying uvicorn `Server` instance.
There is no public API to reach `server.should_exit` from an endpoint.

**Hacky approach:** Store a reference in `app.state` during lifespan:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # No access to uvicorn's Server object here either
    yield
```

The lifespan function receives `app` but not `Server`. The `Server` is created
outside the ASGI app boundary by `uvicorn.run()`. No clean way to bridge.

**Verdict:** Not viable without monkey-patching uvicorn internals.

### 8.5 Option D: asyncio Event Loop Stop

```python
import asyncio

@app.post("/shutdown")
async def shutdown_endpoint():
    loop = asyncio.get_running_loop()
    loop.call_soon(loop.stop)
    return {"status": "shutting_down"}
```

**Problem:** `loop.stop()` immediately stops the event loop, which prevents
uvicorn from running its graceful shutdown sequence (connection drain, lifespan
shutdown, task cleanup). The process exits ungracefully.

**Verdict:** Never use this. It bypasses the entire graceful shutdown chain.

### 8.6 Option E: Background Task with Delayed Signal

Respond first, then send the signal from a background task with a small delay
to ensure the response is sent:

```python
import asyncio
import signal
from fastapi import BackgroundTasks

@app.post("/shutdown")
async def shutdown_endpoint(background_tasks: BackgroundTasks):
    async def _delayed_shutdown():
        await asyncio.sleep(0.5)  # Let response send
        signal.raise_signal(signal.SIGTERM)

    background_tasks.add_task(_delayed_shutdown)
    return {"status": "shutting_down"}
```

**Advantage:** Guarantees the 200 response reaches the client before shutdown
begins.

**Disadvantage:** 500ms delay before shutdown starts. Also, FastAPI
BackgroundTasks run after the response is sent but within the same request
scope -- uvicorn may not poll `should_exit` until the background task completes,
depending on the event loop tick timing.

**Better approach:** Use a fire-and-forget `asyncio.Task`:

```python
@app.post("/shutdown")
async def shutdown_endpoint():
    async def _signal_after_response():
        await asyncio.sleep(0.1)
        signal.raise_signal(signal.SIGTERM)

    asyncio.create_task(_signal_after_response())
    return {"status": "shutting_down"}
```

### 8.7 Recommendation for VaultSpec Worker

**Use Option B (`signal.raise_signal`) with delayed fire-and-forget task.**

This is the ONLY approach that works correctly on all three platforms (Windows,
Linux, macOS). Verified by live test on Windows 11.

```python
import asyncio
import signal

@app.post("/shutdown")
async def shutdown_endpoint():
    """Trigger graceful shutdown of the worker process.

    Cross-platform: uses signal.raise_signal() which correctly invokes
    Python's registered signal handler on Windows, Linux, and macOS.
    DO NOT use os.kill(os.getpid(), SIGTERM) -- it calls TerminateProcess()
    on Windows, killing the process instantly with no cleanup.

    The 0.1s delay ensures the 200 response is sent before shutdown begins.

    Uvicorn handles the signal by:
    1. Stopping new connection acceptance
    2. Draining in-flight requests
    3. Running lifespan shutdown (executor cleanup, bridge close)
    4. Exiting cleanly
    """
    async def _deferred_signal():
        await asyncio.sleep(0.1)
        signal.raise_signal(signal.SIGTERM)

    asyncio.create_task(_deferred_signal())
    return {"status": "shutting_down"}
```

**Why `signal.raise_signal` over `os.kill` -- CRITICAL for Windows:**

- `os.kill(os.getpid(), SIGTERM)` on Windows: calls `TerminateProcess()`,
  process exits code 15 instantly. **No handler. No cleanup. No response sent.**
  Verified by live test.
- `signal.raise_signal(SIGTERM)` on Windows: calls C `raise()`, which invokes
  Python's registered handler. **Handler runs. Graceful shutdown proceeds.**
  Verified by live test.
- On Linux/macOS both work, but `signal.raise_signal` is preferred for
  consistency.

**Why delayed:** Without the 0.1s delay, the signal handler fires during the
endpoint handler's return path, which may prevent the response from being sent
to the client. The delay ensures the response frame is written to the socket
before shutdown begins. This applies equally to all platforms.

**Lifespan shutdown order (all platforms):** When `should_exit` is set:

1. Uvicorn stops accepting connections
2. Drains in-flight requests (respects `timeout_graceful_shutdown`)
3. Calls `lifespan.shutdown()` which triggers the worker lifespan teardown:
   - `executor.shutdown()` -- cancels debounce/fanout tasks, clears state
   - `bridge.close()` -- closes the IPC httpx client
   - `tg.cancel_scope.cancel()` -- cancels heartbeat and background tasks

### 8.8 CLI-I03 Integration

The `service stop` CLI command should:

1. POST to `{worker_url}/shutdown` (new endpoint)
2. POST to `{gateway_url}/api/admin/shutdown` (existing endpoint)
3. Both endpoints use `signal.raise_signal(SIGTERM)` internally
4. CLI waits for both processes to exit (poll health endpoints until connection refused)

**Alternative for gateway-initiated worker shutdown:** Since the gateway
spawned the worker (via `LazyWorkerSpawner`), it can simply call
`_kill_process_tree(worker_pid)` on its own shutdown path. The `/shutdown`
endpoint is needed only when the CLI communicates directly with the worker.

### 8.9 Cross-Platform Signal Behavior Summary

#### Self-signaling (shutdown from within the same process)

| Method | Windows | Linux | macOS | Use? |
|--------|---------|-------|-------|------|
| `signal.raise_signal(SIGTERM)` | Handler invoked (verified) | Handler invoked | Handler invoked | **YES** |
| `os.kill(os.getpid(), SIGTERM)` | `TerminateProcess()` -- instant death, no handler (verified) | Handler invoked | Handler invoked | **NO** |
| `os.kill(os.getpid(), SIGINT)` | `GenerateConsoleCtrlEvent` | Handler invoked | Handler invoked | Avoid (SIGINT has keyboard interrupt semantics) |
| `asyncio.get_event_loop().stop()` | Stops loop, no cleanup | Same | Same | **NEVER** |

#### External process shutdown (killing a child process)

| Method | Windows | Linux | macOS | Use? |
|--------|---------|-------|-------|------|
| `taskkill /T /F /PID` | Kills tree immediately | N/A | N/A | Yes (Windows only) |
| `os.killpg(pgid, SIGTERM)` | N/A | Graceful group signal | Graceful group signal | Yes (POSIX only) |
| `process.terminate()` | `TerminateProcess()` | SIGTERM | SIGTERM | Yes (cross-platform, no tree kill) |
| `process.kill()` | `TerminateProcess()` | SIGKILL | SIGKILL | Last resort |
| `psutil.Process(pid).terminate()` | `TerminateProcess()` | SIGTERM | SIGTERM | Yes (with `children(recursive=True)`) |

#### Decision Matrix

| Scenario | Windows | POSIX (Linux/macOS) |
|----------|---------|-------------------|
| Worker self-shutdown endpoint | `signal.raise_signal(SIGTERM)` | `signal.raise_signal(SIGTERM)` |
| Gateway kills worker (normal) | `taskkill /T /F /PID` | `os.killpg(pgid, SIGTERM)` + wait |
| Gateway kills worker (timeout) | `taskkill /T /F /PID` (same) | `os.killpg(pgid, SIGKILL)` |
| Integration test cleanup | `taskkill /T /F /PID` | `os.killpg(pgid, SIGTERM)` |
| Future with psutil | `psutil.Process.children(recursive=True)` + `kill()` | Same (cross-platform) |

**Key takeaway:** `signal.raise_signal()` is the ONLY cross-platform way to
trigger graceful in-process shutdown. For external process shutdown, there is
no single cross-platform graceful solution -- use `sys.platform` branching
(which is what we already do in `_kill_process_tree()`).
