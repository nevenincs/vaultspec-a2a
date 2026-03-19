# asyncio Process Supervision Patterns — 2026-03-08

## Context

VaultSpec A2A manages a 3-process chain (MCP Server -> Gateway -> Worker) using
asyncio subprocess management. This document consolidates research on how
production Python applications supervise child processes, detect crashes,
implement circuit breakers, and coordinate exponential backoff restarts — all
within the asyncio event loop.

**Related documents:**

- `2026-03-08-watchdog-patterns.md` — Watchdog design survey
- `2026-03-08-subprocess-coordination-patterns.md` — Port, shutdown, health patterns
- `2026-03-08-asyncio-subprocess-monitoring-research.md` — Subprocess API validation
- `2026-03-08-process-supervision-models.md` — Industry comparison (Ollama, Cursor, etc.)

---

## 1. The Three Pillars of asyncio Process Supervision

Production asyncio applications that manage child processes need three
cooperating components:

```
┌──────────────────────────────────────────────────────┐
│                   Parent Process                     │
│                                                      │
│  ┌─────────────┐  ┌───────────────┐  ┌───────────┐  │
│  │   Spawner    │  │   Watchdog    │  │  Circuit   │  │
│  │ (lifecycle)  │──│ (monitoring)  │──│  Breaker   │  │
│  └─────────────┘  └───────────────┘  └───────────┘  │
│        │                 │                  │         │
│        ▼                 ▼                  ▼         │
│  spawn/kill         detect crash      gate requests   │
│  health-check       restart            503 on failure │
│  double-check lock  exp. backoff       auto-recover   │
└──────────────────────────────────────────────────────┘
                       │
                       ▼
              ┌─────────────────┐
              │  Child Process  │
              │  (Worker)       │
              └─────────────────┘
```

### 1.1 Spawner — Lifecycle Management

Owns the child process handle. Responsible for:

- **Lazy spawn** (defer to first need)
- **Double-checked locking** (exactly-once semantics)
- **Health verification** (HTTP probe after spawn)
- **Process handle tracking** (for crash detection and cleanup)

### 1.2 Watchdog — Continuous Monitoring

Background asyncio task that polls child health and triggers restart:

- **Crash detection** via `process.returncode` (not None = exited)
- **Staleness detection** via heartbeat timestamp
- **Exponential backoff restart** (prevent crash loops)
- **State machine** for reporting (pending -> up -> restarting -> up/down)

### 1.3 Circuit Breaker — Request Gating

Protects the parent from cascading failures:

- **Failure counting** (consecutive dispatch failures)
- **State machine** (closed -> open -> half_open -> closed)
- **Time-based recovery** (auto-transition to half_open after timeout)
- **Coordination with watchdog** (force_open on crash, reset on restart)

---

## 2. Spawner Patterns

### 2.1 Lazy Spawn with Double-Checked Locking

The canonical asyncio pattern for exactly-once resource initialization:

```python
class LazyWorkerSpawner:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._spawned = False
        self._process: asyncio.subprocess.Process | None = None

    async def ensure_worker(self) -> None:
        # Fast path: already spawned (no lock contention)
        if self._spawned:
            return

        async with self._lock:
            # Re-check after acquiring lock (another task may have spawned)
            if self._spawned:
                return

            self._process = await self._spawn()
            await self._wait_for_health()
            self._spawned = True
```

**Why double-check is required:** In asyncio, multiple coroutines can be
suspended at the `async with self._lock` line simultaneously. Without the
second check inside the lock, two coroutines that both passed the first
check would both spawn workers after acquiring the lock sequentially.

**Our implementation:** `api/app.py:504-563` `LazyWorkerSpawner`. Called at
6 dispatch sites via `await spawner.ensure_worker()`.

### 2.2 Spawn Function Pattern

```python
async def _spawn_worker(worker_url: str, worker_port: int) -> Process | None:
    """Spawn worker subprocess and wait for health.

    Returns the Process handle on success, None on failure.
    """
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "uvicorn",
        "vaultspec_a2a.worker.app:create_worker_app",
        "--factory", "--host", "127.0.0.1", "--port", str(worker_port),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, ...},
    )

    # Brief settle time to detect immediate crash
    await asyncio.sleep(0.5)
    if process.returncode is not None:
        stderr = await process.stderr.read() if process.stderr else b""
        logger.error("Worker exited immediately: %s", stderr.decode())
        return None

    # Health poll with exponential backoff
    if not await _wait_for_health(worker_url, timeout=30.0):
        await _kill_process_tree(process)
        return None

    return process
```

**Key patterns:**

- `sys.executable` ensures same Python interpreter/venv
- `PIPE` for stderr enables crash diagnostic capture
- Immediate returncode check detects startup failures
- Health poll confirms the service is actually ready
- Returns `None` on failure (not an exception) — caller decides severity

### 2.3 Process Handle Replacement (for Watchdog Restarts)

```python
class LazyWorkerSpawner:
    def replace_process(self, new_proc: Process | None) -> None:
        """Replace the worker process handle after watchdog restart."""
        self._process = new_proc
        self._spawned = True  # Mark as spawned even if proc is None
                               # (external worker detected by health check)
```

**Our implementation:** `api/app.py` `LazyWorkerSpawner.replace_process()`.
Called by `WorkerWatchdog._attempt_restart()` after successful respawn.

---

## 3. Watchdog Patterns

### 3.1 The asyncio Background Task Watchdog

The most common pattern in production asyncio apps: a `while True` loop in
a background task that polls child health.

```python
class WorkerWatchdog:
    POLL_INTERVAL = 5.0      # seconds between checks
    MAX_RETRIES = 3          # restart attempts before giving up
    BACKOFF_BASE = 2.0       # doubles each retry: 2s, 4s, 8s

    async def run(self) -> None:
        """Main watchdog loop — runs until cancelled."""
        try:
            while True:
                await asyncio.sleep(self.POLL_INTERVAL)

                if not self._spawner.spawned:
                    continue  # Don't monitor before first spawn

                crashed = self._process_crashed()
                stale = self._heartbeat_stale()

                if not crashed and not stale:
                    self._update_status("up")
                    continue

                # Crash detected — initiate restart
                self._cb.force_open()
                self._update_status("restarting")

                if await self._attempt_restart():
                    self._cb.record_success()
                    self._update_status("up")
                else:
                    self._update_status("down")

        except asyncio.CancelledError:
            pass  # Clean shutdown
```

**Our implementation:** `api/app.py:611-742` `WorkerWatchdog` class.

### 3.2 Dual Crash Detection Signals

Production watchdogs use multiple signals to detect crashes:

| Signal | Mechanism | Latency | False Positives |
|--------|-----------|---------|-----------------|
| `process.returncode` | OS process exit notification | <1s (poll interval) | None — definitive |
| Heartbeat staleness | No heartbeat within timeout | `HEARTBEAT_TIMEOUT` (90s) | Possible if worker is CPU-bound |
| HTTP health probe | Active GET /health | 2-5s (request timeout) | Possible under load |

**Recommended combination:** Use `returncode` as the primary signal (definitive,
fastest). Heartbeat staleness as secondary (catches frozen-but-alive workers).
Active health probe as tertiary (useful for external workers not spawned by us).

**Our implementation uses signals 1 and 2:**

- `_process_crashed()`: checks `process.returncode is not None`
- `_heartbeat_stale()`: checks `monotonic() - last_heartbeat > 90s`

### 3.3 Exponential Backoff Restart

The standard pattern for preventing crash loops:

```python
async def _attempt_restart(self) -> bool:
    for attempt in range(self.MAX_RETRIES):
        delay = self.BACKOFF_BASE * (2 ** attempt)  # 2s, 4s, 8s
        await asyncio.sleep(delay)

        # Clean up old process
        if old_proc and old_proc.returncode is None:
            await _kill_process_tree(old_proc)

        # Spawn new worker
        new_proc = await _spawn_worker(url, port)
        if new_proc is not None:
            self._spawner.replace_process(new_proc)
            return True

    return False  # All retries exhausted
```

**Our backoff sequence:**

| Attempt | Delay | Cumulative | Total with poll |
|---------|-------|------------|-----------------|
| 1 | 2s | 2s | 7s (5s poll + 2s) |
| 2 | 4s | 6s | 11s |
| 3 | 8s | 14s | 19s |
| (give up) | — | — | ~19s max recovery time |

**Design decision:** 3 retries (not 5) with 2s base (not 1s). Rationale:
desktop tool users expect fast recovery. 19s total is acceptable; 31s+ is not.

### 3.4 Worker Status State Machine

```
                       ┌───────────┐
                       │  pending  │  (initial, before first spawn)
                       └─────┬─────┘
                             │ first healthy check
                             ▼
                       ┌───────────┐
              ┌───────▶│    up     │◀───────┐
              │        └─────┬─────┘        │
              │              │ crash         │ restart success
              │              ▼              │
              │        ┌───────────┐        │
              │        │restarting │────────┘
              │        └─────┬─────┘
              │              │ all retries failed
              │              ▼
              │        ┌───────────┐
              └────────│   down    │  (manual intervention required)
                       └───────────┘
```

Exposed on `/health` endpoint as `worker_status` field. The "down" state is
terminal until the gateway is restarted (which re-initializes the watchdog).

---

## 4. Circuit Breaker Patterns

### 4.1 The Three-State Circuit Breaker

The classic pattern adapted for asyncio with `time.monotonic()`:

```python
class WorkerCircuitBreaker:
    def __init__(self, failure_threshold=3, recovery_timeout=30.0):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._consecutive_failures = 0
        self._state = "closed"
        self._opened_at = 0.0

    @property
    def state(self) -> str:
        """Auto-promote open -> half_open after recovery timeout."""
        if (
            self._state == "open"
            and (time.monotonic() - self._opened_at) >= self._recovery_timeout
        ):
            self._state = "half_open"
        return self._state

    def pre_dispatch(self) -> None:
        if self.state == "open":
            raise HTTPException(503, "Circuit breaker OPEN")
        # half_open: allow one probe through

    def record_success(self) -> None:
        self._consecutive_failures = 0
        self._state = "closed"

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold:
            self._state = "open"
            self._opened_at = time.monotonic()
```

**Our implementation:** `api/app.py:89-164` `WorkerCircuitBreaker`.

### 4.2 Circuit Breaker State Transitions

```
                        ┌──────────┐
            success ───▶│  CLOSED  │◀─── success (from half_open)
                        └────┬─────┘
                             │ 3 consecutive failures
                             ▼
                        ┌──────────┐
                        │   OPEN   │──── all dispatches → 503
                        └────┬─────┘
                             │ 30s timeout
                             ▼
                        ┌──────────┐
            failure ───▶│HALF_OPEN │──── 1 probe dispatch allowed
                        └──────────┘
```

### 4.3 Watchdog-Circuit Breaker Coordination

The watchdog and circuit breaker work together but have distinct roles:

| Event | Watchdog Action | Circuit Breaker Action |
|-------|----------------|----------------------|
| Worker crash detected | Start restart sequence | `force_open()` → 503 |
| Restart successful | Update status to "up" | `record_success()` → CLOSED |
| Restart failed | Update status to "down" | Remains OPEN |
| Dispatch succeeds | (not involved) | `record_success()` → CLOSED |
| Dispatch fails | (not involved) | `record_failure()` → may OPEN |

**Key insight:** `force_open()` is called by the watchdog, not by dispatch
failure counting. This provides immediate protection without waiting for 3
failed dispatches. The normal `record_failure()` path handles transient
failures that aren't process crashes.

### 4.4 Thread Safety in asyncio

`WorkerCircuitBreaker` is NOT thread-safe — all methods must be called from
the same event loop. This is correct because:

1. All dispatch endpoints run on the same uvicorn event loop
2. The watchdog task runs on the same event loop
3. `time.monotonic()` is thread-safe but our state mutations are not
4. No `asyncio.Lock` is needed because asyncio is cooperative — property
   access and simple attribute mutations are atomic within a single `await`

**Exception:** If we ever move to multi-worker uvicorn (`--workers N`), each
worker process gets its own circuit breaker instance. No shared state needed.

---

## 5. FastAPI Lifespan Integration

### 5.1 Wiring Spawner, Watchdog, and Circuit Breaker

```python
@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    # Create components
    cb = WorkerCircuitBreaker()
    spawner = LazyWorkerSpawner(worker_url, worker_port, auto_spawn=True)
    watchdog = WorkerWatchdog(spawner, cb, app.state)

    # Store on app.state for endpoint access
    app.state.circuit_breaker = cb
    app.state.worker_spawner = spawner

    # Start watchdog as background task
    watchdog_task = asyncio.create_task(watchdog.run())

    try:
        yield
    finally:
        # Shutdown order: stop monitoring, then kill process
        watchdog_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watchdog_task

        # Kill worker subprocess tree
        if spawner.process and spawner.process.returncode is None:
            await _kill_process_tree(spawner.process)
```

### 5.2 Shutdown Ordering

Critical: components must be shut down in reverse dependency order:

```
Shutdown sequence:
1. Cancel watchdog task      (stop monitoring — no more restarts)
2. Cancel heartbeat task     (stop receiving heartbeats)
3. Close WS connections      (notify clients)
4. Kill worker subprocess    (tree kill — process + children)
5. Close httpx clients       (IPC bridge, health probe)
6. Close database            (SQLAlchemy engine disposal)
```

**Why watchdog first:** If we kill the worker before cancelling the watchdog,
the watchdog detects the crash and tries to restart — racing with shutdown.

### 5.3 Background Task Best Practices

1. **Always `create_task()` in lifespan startup** — not in endpoint handlers
2. **Always cancel in lifespan `finally`** — prevent task leaks
3. **Catch `CancelledError` in the task** — log graceful stop
4. **Never use `asyncio.gather(..., return_exceptions=True)` for cleanup** —
   it swallows real errors
5. **Suppress `CancelledError` when awaiting cancelled task** — it's expected

---

## 6. Production Patterns from Real-World Python Applications

### 6.1 Celery Worker Monitoring

Celery (the most widely deployed Python process supervisor) uses:

- **Heartbeat protocol**: Workers send heartbeats to the broker every 2s
- **Event system**: Worker events (started, succeeded, failed) relayed to monitors
- **Process pool management**: prefork/eventlet/gevent pool with child monitoring
- **`--autoscale`**: Dynamic worker count based on queue depth

**Applicable to us:** Celery's heartbeat model (worker -> monitor) matches our
worker -> gateway heartbeat. Our 10s interval is reasonable (Celery default is
2s, but Celery handles much higher throughput).

### 6.2 Gunicorn Arbiter Pattern

Gunicorn's `Arbiter` class (arbiter.py) is the canonical Python process
supervisor:

- **Master process** spawns N worker processes
- **Signal-based control**: SIGHUP (reload), SIGTERM (graceful stop), SIGQUIT (quick stop)
- **Worker monitoring**: `os.waitpid(WNOHANG)` in a polling loop
- **Automatic restart**: Dead workers are replaced immediately
- **Graceful timeout**: Workers get `--graceful-timeout` seconds to finish requests

**Key insight:** Gunicorn uses `os.waitpid()` (synchronous) in a `while True`
loop with `time.sleep()`. Our asyncio approach using `process.returncode`
polling is the equivalent async pattern.

**Not directly applicable:** Gunicorn uses POSIX signals extensively (SIGHUP,
SIGUSR1, SIGUSR2, SIGTTOU, SIGTTIN). These don't work on Windows. Our approach
of using HTTP health checks + `taskkill` is the correct Windows adaptation.

### 6.3 Uvicorn Server Pattern

Uvicorn's `Server` class (server.py) demonstrates FastAPI-compatible process
management:

- **`should_exit` flag**: Checked in main loop, set by signal handlers
- **Graceful shutdown**: `timeout_graceful_shutdown` config for connection drain
- **Child reap**: When using `--workers`, the multiprocess supervisor monitors
  children via `os.waitpid()`
- **`signal.raise_signal()`**: The only cross-platform self-signaling method
  (verified on Windows — `os.kill(os.getpid(), SIGTERM)` calls
  `TerminateProcess` and bypasses handlers)

**Applicable to us:** We use uvicorn as our ASGI server. Understanding its
shutdown sequence is critical for our `/shutdown` endpoint (CLI-I03).

### 6.4 JupyterHub Spawner Pattern

JupyterHub manages per-user server processes:

- **Spawner abstraction**: `LocalProcessSpawner`, `DockerSpawner`, `KubeSpawner`
- **Polling**: `spawner.poll()` returns exit code or None (alive)
- **Configurable restart**: `c.Spawner.start_timeout`, `c.Spawner.http_timeout`
- **Proxy integration**: Configurable proxy routes traffic to spawned servers

**Key insight:** JupyterHub's `poll()` method is equivalent to our
`process.returncode` check. They also use HTTP health probes as the definitive
readiness signal (not just process existence).

### 6.5 Airflow Scheduler Pattern

Apache Airflow's scheduler supervises DAG processors:

- **`DagFileProcessorManager`**: Spawns subprocess per DAG file
- **Heartbeat table**: Writes heartbeat to database, not HTTP
- **Timeout detection**: `last_heartbeat + timeout < now` in SQL query
- **Clean restart**: Kill process group, respawn from scratch

**Applicable to us:** Database-backed heartbeat is an alternative to HTTP
heartbeat. For single-machine deployment, HTTP is simpler and avoids database
write contention.

---

## 7. Comparison: Our Implementation vs Industry

| Aspect | VaultSpec A2A | Gunicorn | Celery | JupyterHub |
|--------|-------------|----------|--------|------------|
| Crash detection | `returncode` + heartbeat | `waitpid` | Heartbeat to broker | `poll()` |
| Health check | HTTP GET /health | N/A (internal) | Heartbeat event | HTTP probe |
| Restart strategy | Exp. backoff (3 retries) | Immediate | Configurable | Configurable |
| Circuit breaker | Yes (3-state) | No | No | No |
| Process tree kill | `taskkill /T /F` (Win) | `os.killpg` (POSIX) | `os.kill` | Spawner-specific |
| Graceful shutdown | SIGTERM + timeout | SIGTERM + graceful_timeout | SIGTERM + warm shutdown | Spawner.stop() |
| Windows support | Full | No | Partial | Partial |
| Lazy spawn | Yes (first dispatch) | No (all at startup) | No (all at startup) | Yes (on demand) |

### 7.1 Where We Excel

1. **Windows-first**: Only production Python process supervisor that fully
   supports Windows process tree management
2. **Circuit breaker integration**: None of the major frameworks integrate a
   circuit breaker with their process supervisor
3. **Lazy spawn**: JupyterHub does this (spawn on user login), but Gunicorn
   and Celery don't — all workers start at boot

### 7.2 Gaps vs Industry

1. **No graceful drain**: Gunicorn's `graceful_timeout` lets workers finish
   in-flight requests before dying. Our `taskkill /T /F` is immediate.
   **Impact:** LOW — desktop tool, not a high-traffic server.

2. **No process group isolation**: Gunicorn uses `os.setpgrp()` to isolate
   worker process groups. We rely on `taskkill /T` (Windows) which covers
   this, but POSIX path uses `process.terminate()` (single process).
   **Impact:** LOW — our worker doesn't spawn grandchildren.

3. **No configurable restart policy**: Celery and systemd support configurable
   restart strategies (always, on-failure, unless-stopped). Our policy is
   hardcoded (3 retries, 2s base backoff).
   **Impact:** LOW — can be made configurable if needed.

---

## 8. Anti-Patterns to Avoid

### 8.1 Blocking the Event Loop with waitpid

```python
# WRONG: blocks the event loop
os.waitpid(pid, 0)  # Synchronous wait

# CORRECT: use process.returncode (updated by asyncio child watcher)
if process.returncode is not None:
    # Process has exited
```

### 8.2 Spawning in Endpoint Handlers

```python
# WRONG: spawn on every request
@app.post("/dispatch")
async def dispatch():
    process = await asyncio.create_subprocess_exec(...)  # Race condition!

# CORRECT: lazy spawn with double-checked locking
@app.post("/dispatch")
async def dispatch():
    await spawner.ensure_worker()  # Thread-safe, exactly once
```

### 8.3 Restarting Without Backoff

```python
# WRONG: immediate restart loop (crash loop)
while True:
    process = await spawn()
    await process.wait()
    # Immediately restart — consumes 100% CPU if child crashes instantly

# CORRECT: exponential backoff
for attempt in range(MAX_RETRIES):
    delay = BASE * (2 ** attempt)
    await asyncio.sleep(delay)
    process = await spawn()
    if process_healthy():
        break
```

### 8.4 Ignoring Process Tree on Windows

```python
# WRONG: only kills parent, orphans children
process.terminate()  # Windows: TerminateProcess() on parent only

# CORRECT: kill entire process tree
await asyncio.create_subprocess_exec(
    "taskkill", "/T", "/F", "/PID", str(process.pid)
)
```

---

## 9. Recommendations

| Priority | Recommendation | Status |
|----------|---------------|--------|
| P0 | asyncio background task watchdog with poll interval | IMPLEMENTED (5s) |
| P0 | Dual crash detection (returncode + heartbeat) | IMPLEMENTED |
| P0 | Exponential backoff restart (3 retries, 2s base) | IMPLEMENTED |
| P0 | Circuit breaker with 3-state machine | IMPLEMENTED |
| P0 | Watchdog-circuit breaker coordination (force_open) | IMPLEMENTED |
| P0 | Double-checked locking for lazy spawn | IMPLEMENTED |
| P0 | Process tree kill on Windows (taskkill /T /F) | IMPLEMENTED |
| P1 | PIPE stderr for crash diagnostics | PARTIAL (APP-N01) |
| P1 | Worker status state machine on /health | IMPLEMENTED |
| P2 | Configurable restart policy (via env vars) | DEFERRED |
| P2 | Graceful drain period before kill | DEFERRED |
| P2 | psutil for cross-platform tree kill | DEFERRED |

---

## 10. Sources

- Python 3.13 asyncio subprocess: stdlib (validated against installed runtime)
- FastAPI lifespan: `.venv/Lib/site-packages/starlette/routing.py`
- Gunicorn arbiter: `gunicorn/arbiter.py` (GitHub)
- Celery worker: `celery/worker/worker.py` (GitHub)
- Uvicorn server: `.venv/Lib/site-packages/uvicorn/server.py` (installed)
- JupyterHub spawner: `jupyterhub/spawner.py` (GitHub)
- Airflow scheduler: `airflow/dag_processing/manager.py` (GitHub)
- Our implementation: `src/vaultspec_a2a/api/app.py` (lines 78-742)
- Circuit breaker pattern: Martin Fowler, "CircuitBreaker" (2014)
