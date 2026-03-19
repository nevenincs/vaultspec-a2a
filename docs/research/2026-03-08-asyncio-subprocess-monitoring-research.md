# asyncio Subprocess Monitoring Research — 2026-03-08

## Context

VaultSpec A2A's MCP server, gateway, and worker form a 3-process chain managed
via `asyncio.create_subprocess_exec`. This document researches subprocess
monitoring patterns used in CRIT-01 (MCP auto-start gateway), CRIT-02 (worker
auto-spawn), and PROD-002 (worker watchdog).

**Related documents:**

- `2026-03-08-library-validation-asyncio-subprocess.md` — API validation
- `2026-03-08-subprocess-coordination-patterns.md` — Coordination patterns
- `2026-03-08-watchdog-patterns.md` — Watchdog and supervision patterns

**Source:** Python 3.13 stdlib, validated against installed runtime.

---

## 1. `asyncio.create_subprocess_exec` Patterns

### 1.1 Basic Service Spawn

```python
import asyncio
import sys

process = await asyncio.create_subprocess_exec(
    sys.executable, "-m", "uvicorn",
    "vaultspec_a2a.api.app:create_app",
    "--factory",
    "--host", "127.0.0.1",
    "--port", str(port),
    stdout=asyncio.subprocess.PIPE,     # Capture for crash diagnostics
    stderr=asyncio.subprocess.PIPE,     # Capture for crash diagnostics
    env={**os.environ, "CUSTOM_VAR": "value"},
)
```

**Key choices:**

- `sys.executable` ensures the same Python interpreter (same venv)
- `--factory` tells uvicorn to call `create_app()` to get the ASGI app
- `PIPE` for stdout/stderr enables crash diagnostic capture
- `DEVNULL` suppresses output (used in production, but loses crash info)
- `env` parameter replaces (not merges) the environment — must include `os.environ`

### 1.2 Windows-Specific: `CREATE_NEW_PROCESS_GROUP`

```python
import subprocess

process = await asyncio.create_subprocess_exec(
    *cmd,
    creationflags=(
        subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    ),
)
```

**Why:** On Windows, `CREATE_NEW_PROCESS_GROUP` creates a new process group
for the child. This is required for `taskkill /T /F /PID` to correctly
identify and kill the entire process tree. Without it, child processes of the
child (e.g., worker spawned by gateway) may not be included in the tree kill.

### 1.3 Premature Exit Detection

```python
# After spawn, check for immediate crash
await asyncio.sleep(1.0)  # Brief settle time
if process.returncode is not None:
    stderr_output = b""
    if process.stderr:
        stderr_output = await process.stderr.read()
    raise RuntimeError(
        f"Process exited immediately with code {process.returncode}: "
        f"{stderr_output.decode(errors='replace')}"
    )
```

**Important:** `process.stderr` is `None` when spawned with
`stderr=DEVNULL`. The guard `if process.stderr` prevents `AttributeError`.
This is a known gap (APP-N01): using `DEVNULL` loses crash diagnostics.

---

## 2. `process.returncode` Polling for Crash Detection

### 2.1 How `returncode` Works

```python
# returncode is None while the process is running
assert process.returncode is None  # Still alive

# After process exits (naturally or killed):
await process.wait()  # Blocks until exit
assert process.returncode is not None  # Exit code available

# Common exit codes:
#   0 = clean exit
#   1 = general error
#  -9 = SIGKILL (Linux)
#  -15 = SIGTERM (Linux)
#   1 = TerminateProcess (Windows, mapped to 1)
```

### 2.2 Non-Blocking Crash Check

```python
def is_alive(process: asyncio.subprocess.Process) -> bool:
    """Check if subprocess is still running without blocking."""
    return process.returncode is None
```

`returncode` is updated automatically when the process exits. No syscall
needed — asyncio's child watcher monitors the process in the background.

### 2.3 Watchdog Polling Loop

```python
async def _worker_watchdog(
    spawner: LazyWorkerSpawner,
    circuit_breaker: WorkerCircuitBreaker,
    interval: float = 15.0,
) -> None:
    """Background task: monitor worker, restart on crash."""
    consecutive_failures = 0
    MAX_RESTARTS = 5

    while True:
        await asyncio.sleep(interval)

        if not spawner.spawned:
            continue  # Worker not yet needed (lazy spawn)

        proc = spawner.process
        if proc is not None and proc.returncode is not None:
            # Worker crashed! Attempt restart
            logger.warning(
                "Worker exited with code %d (attempt %d/%d)",
                proc.returncode, consecutive_failures + 1, MAX_RESTARTS,
            )

            if consecutive_failures >= MAX_RESTARTS:
                logger.error("Worker restart limit exhausted")
                break

            delay = min(1.0 * (2 ** consecutive_failures), 60.0)
            await asyncio.sleep(delay)

            try:
                await spawner.respawn()
                circuit_breaker.reset()
                consecutive_failures = 0
            except Exception:
                consecutive_failures += 1
                logger.error("Restart failed", exc_info=True)
        else:
            consecutive_failures = 0  # Reset on healthy check
```

**Implementation:** `api/app.py` `_worker_watchdog()` background task,
started in gateway lifespan via `asyncio.create_task()`.

---

## 3. Windows Process Tree Kill

### 3.1 The Problem

On Windows, `process.terminate()` and `process.kill()` both call
`TerminateProcess()` via Win32 API. This kills ONLY the immediate process,
NOT its children. Grandchildren become orphans.

Example: Gateway spawns Worker. If we `terminate()` the gateway, the worker
process is orphaned and continues running with no parent.

### 3.2 Solution: `taskkill /T /F /PID`

```python
async def _kill_process_tree(process: asyncio.subprocess.Process) -> None:
    """Kill a process and all its children (Windows tree kill)."""
    if process.returncode is not None:
        return  # Already dead

    if sys.platform == "win32":
        killer = await asyncio.create_subprocess_exec(
            "taskkill", "/T", "/F", "/PID", str(process.pid),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(killer.wait(), timeout=5.0)
        except TimeoutError:
            logger.warning("taskkill timed out for PID %d", process.pid)
    else:
        # POSIX: terminate with timeout, then SIGKILL
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=15.0)
        except TimeoutError:
            process.kill()
            await asyncio.wait_for(process.wait(), timeout=5.0)
```

**Flags:**

- `/T` — terminate the process tree (the target and all children)
- `/F` — force termination (no graceful shutdown prompt)
- `/PID` — target by process ID

**Implementation:** Used in 3 places:

1. `protocols/mcp/server.py:329-367` — MCP kills gateway
2. `api/app.py:439-474` — Gateway kills worker
3. Integration test `conftest.py` — Test cleanup

### 3.3 POSIX Alternative: `os.killpg()`

```python
import os
import signal

# On POSIX, kill the entire process group
os.killpg(os.getpgid(process.pid), signal.SIGTERM)
```

Requires the child to be in its own process group (`preexec_fn=os.setpgrp`
or `start_new_session=True`). Not available on Windows.

### 3.4 Future: psutil Cross-Platform Tree Kill

```python
import psutil

def kill_tree(pid: int) -> None:
    parent = psutil.Process(pid)
    children = parent.children(recursive=True)
    for child in children:
        child.kill()
    parent.kill()
    psutil.wait_procs(children + [parent], timeout=10)
```

**Status:** psutil not yet installed. Would replace platform-specific branching
with a single cross-platform API. Add `psutil>=6.0.0` to dev deps when needed.

---

## 4. Double-Checked Locking with `asyncio.Lock`

### 4.1 The Problem

`LazyWorkerSpawner.ensure_worker()` is called from every dispatch endpoint
(6 call sites). Multiple concurrent requests could race to spawn the worker.
We need exactly-once spawn semantics.

### 4.2 Pattern: Double-Checked Locking

```python
class LazyWorkerSpawner:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._spawned = False
        self._process: asyncio.subprocess.Process | None = None

    async def ensure_worker(self) -> None:
        """Spawn worker if not already running. Thread-safe via asyncio.Lock."""
        if self._spawned:
            return  # Fast path: already spawned (no lock needed)

        async with self._lock:
            if self._spawned:
                return  # Re-check after acquiring lock (another task may have spawned)

            self._process = await self._spawn_worker()
            await self._wait_for_health()
            self._spawned = True
```

**Why double-check:**

1. **First check (no lock):** Fast path for the common case. After the worker
   is spawned, this returns immediately without lock contention.
2. **Second check (under lock):** Prevents the race where two tasks both pass
   the first check, both acquire the lock sequentially, and the second one
   spawns a duplicate worker.

**asyncio.Lock specifics:**

- `asyncio.Lock` is NOT thread-safe — only safe within a single event loop
- This is correct for our use case: all dispatch endpoints run on the same loop
- `async with self._lock:` yields to other tasks while waiting (non-blocking)
- The lock is reentrant-safe by design (asyncio.Lock is NOT reentrant, but our
  code path doesn't re-enter)

### 4.3 Implementation

`api/app.py:482-538` `LazyWorkerSpawner` class. The `ensure_worker()` method
is called at all 6 dispatch sites in `endpoints.py` and `internal.py`.

---

## 5. Background Task Lifecycle in FastAPI Lifespan

### 5.1 Pattern: Start Task in Lifespan, Cancel on Shutdown

```python
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup: create background tasks
    watchdog_task = asyncio.create_task(_worker_watchdog(spawner, cb))
    heartbeat_task = asyncio.create_task(_heartbeat_receiver())

    try:
        yield  # Application runs here
    finally:
        # Shutdown: cancel all background tasks
        watchdog_task.cancel()
        heartbeat_task.cancel()

        # Wait for cancellation to propagate
        with contextlib.suppress(asyncio.CancelledError):
            await watchdog_task
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task

        # Kill subprocess last
        await _kill_process_tree(worker_process)
```

**Key principles:**

1. **Create tasks in lifespan startup** — they share the app's event loop
2. **Cancel tasks in lifespan finally** — ensures cleanup on shutdown
3. **Suppress CancelledError** — cancellation is expected, not an error
4. **Kill subprocesses after task cancellation** — tasks may hold references
   to subprocess handles
5. **Never use `asyncio.gather(..., return_exceptions=True)` for cleanup** —
   swallows real errors

### 5.2 Task Group Alternative (anyio)

```python
from anyio import create_task_group

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with create_task_group() as tg:
        tg.start_soon(_worker_watchdog, spawner, cb)
        tg.start_soon(_heartbeat_receiver)
        yield
        tg.cancel_scope.cancel()
```

**Our approach:** We use `asyncio.create_task()` directly. The anyio task
group is cleaner but adds a dependency on anyio's semantics (already available
via FastAPI -> Starlette -> anyio chain, but not explicitly used).

### 5.3 Shutdown Ordering

The gateway lifespan shutdown order:

```
1. Cancel watchdog task (stop monitoring)
2. Cancel heartbeat task (stop receiving worker heartbeats)
3. Flush aggregator state (send final events to WS clients)
4. Close WS connections (notify clients of shutdown)
5. Kill worker subprocess (process tree kill)
6. Close httpx clients (IPC bridge, health probe)
```

**Implementation:** `api/app.py` `_lifespan()` function.

---

## 6. Exponential Backoff Retry for Subprocess Restart

### 6.1 Algorithm

```python
import dataclasses

@dataclasses.dataclass
class RestartPolicy:
    """Exponential backoff policy for subprocess restarts."""
    max_attempts: int = 5
    base_delay: float = 1.0       # Initial delay (seconds)
    max_delay: float = 60.0       # Cap on delay
    reset_after: float = 300.0    # Reset counter after 5 min of healthy operation

    def delay_for(self, attempt: int) -> float:
        """Calculate delay: min(base * 2^attempt, max_delay)."""
        return min(self.base_delay * (2 ** attempt), self.max_delay)
```

### 6.2 Backoff Sequence

| Attempt | Delay | Cumulative | Action |
|---------|-------|------------|--------|
| 0 | 1s | 1s | First restart |
| 1 | 2s | 3s | Second restart |
| 2 | 4s | 7s | Third restart |
| 3 | 8s | 15s | Fourth restart |
| 4 | 16s | 31s | Fifth restart |
| 5 | — | — | Give up, log error |

After 5 minutes of healthy operation (no crashes), the attempt counter resets
to 0. This handles transient failures that resolve themselves.

### 6.3 Crash Loop Prevention

The backoff prevents a crash loop from consuming resources. If the worker
crashes immediately on startup 5 times, the watchdog gives up and logs an
error. The circuit breaker remains open (503 to all dispatches).

Recovery requires manual intervention: fix the underlying issue and restart
the gateway, which re-initializes the watchdog with a fresh attempt counter.

### 6.4 Health Check After Restart

```python
async def respawn(self) -> None:
    """Kill existing worker and spawn a new one."""
    if self._process and self._process.returncode is None:
        await _kill_process_tree(self._process)

    self._process = await self._spawn_worker()

    # Wait for health with tenacity
    @retry(
        retry=retry_if_exception_type(_HealthCheckError),
        wait=wait_exponential(multiplier=0.1, min=0.1, max=2.0),
        stop=stop_after_delay(30.0),
        reraise=True,  # Propagates → hard failure if health never comes up
    )
    async def _wait():
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{worker_url}/health", timeout=2.0)
            if resp.status_code != 200:
                raise _HealthCheckError(f"Worker health check failed: {resp.status_code}")

    await _wait()
    self._spawned = True
```

**tenacity `reraise=True`:** Critical for hard-fail semantics. Without it,
tenacity wraps the final exception in `RetryError`. With it, the actual
`_HealthCheckError` propagates, which the caller can handle appropriately.

---

## 7. Cross-Platform Signal Behavior

### 7.1 Self-Signaling (Shutdown from Within)

| Method | Windows | Linux/macOS | Verdict |
|--------|---------|-------------|---------|
| `signal.raise_signal(SIGTERM)` | Handler invoked (verified) | Handler invoked | **USE THIS** |
| `os.kill(os.getpid(), SIGTERM)` | `TerminateProcess()` — instant death, no handler | Handler invoked | **NEVER USE** |

**`signal.raise_signal()` is the ONLY cross-platform way to trigger graceful
in-process shutdown.** Verified by live test on Windows 11 Python 3.13.

### 7.2 External Process Kill

| Method | Windows | Linux/macOS |
|--------|---------|-------------|
| `taskkill /T /F /PID` | Kills process tree | N/A |
| `os.killpg(pgid, SIGTERM)` | N/A | Kills process group |
| `process.terminate()` | `TerminateProcess()` (single process only) | SIGTERM |
| `process.kill()` | `TerminateProcess()` (same as terminate!) | SIGKILL |

**No single cross-platform API for tree kill.** Use `sys.platform` branching.
Future: psutil `Process.children(recursive=True)` is cross-platform.

---

## 8. Recommendations

| Priority | Recommendation | Rationale |
|----------|---------------|-----------|
| P0 | Use `asyncio.create_subprocess_exec` with `sys.executable` | Same interpreter, same venv |
| P0 | `taskkill /T /F /PID` on Windows for tree kill | Only reliable Windows tree kill |
| P0 | Double-checked locking via `asyncio.Lock` for spawn | Exactly-once semantics |
| P0 | Exponential backoff for restart (5 attempts, 1s base) | Crash loop prevention |
| P0 | `signal.raise_signal(SIGTERM)` for self-shutdown | Only cross-platform option |
| P1 | `PIPE` for stderr (not `DEVNULL`) | Crash diagnostics |
| P1 | `tenacity` with `reraise=True` for health polling | Hard-fail semantics |
| P2 | Add `psutil>=6.0.0` for cross-platform tree kill | Eliminates platform branching |

---

## 9. Sources

- Python 3.13 asyncio subprocess: `asyncio.create_subprocess_exec`
- Python 3.13 signal: `signal.raise_signal()` (available since 3.8)
- uvicorn shutdown: `.venv/Lib/site-packages/uvicorn/server.py` (verified)
- Windows `taskkill` docs: `taskkill /?` (built-in)
- tenacity: `tenacity>=9.0.0` (installed)
- Our implementation: `src/vaultspec_a2a/api/app.py` (LazyWorkerSpawner, watchdog)
- Our implementation: `src/vaultspec_a2a/protocols/mcp/server.py` (gateway spawn)
