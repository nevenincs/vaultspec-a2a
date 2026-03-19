# Watchdog Patterns for Process Supervision — 2026-03-08

## Context

VaultSpec A2A runs a 3-process chain (MCP -> Gateway -> Worker). If the worker
crashes, the gateway must detect it and optionally restart it. This document
surveys watchdog and process supervision patterns applicable to an asyncio-based
Python application running on Windows 11 and Linux.

---

## 1. Current State

### 1.1 Existing Health Infrastructure

The codebase already has the building blocks for crash detection:

| Component | Location | What It Does |
|-----------|----------|-------------|
| Worker heartbeat | `worker/ipc.py:211-221` | Sends HTTP POST to `/internal/heartbeat` every 10s |
| Gateway heartbeat tracking | `api/internal.py:333-345` | Records `worker_last_heartbeat_ts` on app.state |
| Staleness check | `api/app.py:693-720` | `/internal/health` reports worker stale if no heartbeat in 90s |
| Circuit breaker | `api/app.py:78-170` | Opens after 3 consecutive dispatch failures, 30s recovery |
| LazyWorkerSpawner | `api/app.py:482-538` | Spawns worker subprocess, tracks process handle |
| Process tree kill | `api/app.py:439-474` | `taskkill /T /F /PID` on Windows for clean shutdown |

### 1.2 What's Missing

No component currently **detects a crash and restarts** the worker. The
`LazyWorkerSpawner` spawns once and never monitors. If the worker crashes:

1. Heartbeats stop arriving
2. After 90s, `/internal/health` reports worker as stale
3. Circuit breaker opens after 3 failed dispatches
4. All subsequent dispatches return 503
5. **No recovery** -- worker stays dead until manual restart

This is PROD-002 (Task #31).

---

## 2. Watchdog Patterns

### 2.1 asyncio Background Task Watchdog

**Pattern**: A long-running asyncio task in the gateway process that
periodically checks the worker's health and restarts it if needed.

```python
async def _worker_watchdog(
    spawner: LazyWorkerSpawner,
    circuit_breaker: WorkerCircuitBreaker,
    interval: float = 15.0,
    max_restart_attempts: int = 5,
    backoff_base: float = 2.0,
) -> None:
    """Monitor worker health and restart on crash."""
    consecutive_failures = 0

    while True:
        await asyncio.sleep(interval)

        if not spawner.spawned:
            continue  # Worker not yet needed

        # Check if worker process is still alive
        proc = spawner.process
        if proc is not None and proc.returncode is not None:
            # Process exited -- attempt restart
            logger.warning(
                "Worker process exited with code %d, attempting restart (%d/%d)",
                proc.returncode,
                consecutive_failures + 1,
                max_restart_attempts,
            )

            if consecutive_failures >= max_restart_attempts:
                logger.error(
                    "Worker restart limit reached (%d attempts), giving up",
                    max_restart_attempts,
                )
                break

            # Exponential backoff
            delay = backoff_base ** consecutive_failures
            await asyncio.sleep(delay)

            try:
                await spawner.respawn()
                circuit_breaker.reset()
                consecutive_failures = 0
                logger.info("Worker restarted successfully")
            except Exception:
                consecutive_failures += 1
                logger.error("Worker restart failed", exc_info=True)
        else:
            # Process alive -- reset failure counter
            consecutive_failures = 0
```text

**Pros**:

- Zero external dependencies
- Runs inside the existing asyncio event loop
- Direct access to `LazyWorkerSpawner` and `WorkerCircuitBreaker`
- Works on Windows (no signals needed)

**Cons**:

- If the gateway crashes, the watchdog dies too
- No protection against gateway hangs (event loop blocked)

**Verdict**: RECOMMENDED for Phase 2. Solves the immediate need with minimal
complexity.

### 2.2 Health-Check Driven Circuit Breaker Recovery

**Pattern**: Instead of a separate watchdog task, extend the circuit breaker's
HALF_OPEN state to include a worker restart attempt.

```python
# In WorkerCircuitBreaker.pre_dispatch():
if self.state == "HALF_OPEN":
    # Before the probe dispatch, check if worker is alive
    if not await _check_worker_health(worker_url):
        await spawner.respawn()
        await asyncio.sleep(2.0)  # Wait for startup
```text

**Pros**:

- No separate background task
- Restart only triggered when there's actual demand (a dispatch)
- Natural integration with existing circuit breaker flow

**Cons**:

- Restart happens on the request path (adds latency to the probe dispatch)
- Does not detect crash between dispatches
- More complex circuit breaker state machine

**Verdict**: COMPLEMENT to the watchdog, not a replacement. Good for
demand-driven recovery, but the background watchdog handles idle-time crashes.

### 2.3 Dual Heartbeat (Worker -> Gateway + Gateway -> Worker)

**Pattern**: In addition to the worker sending heartbeats to the gateway,
the gateway periodically pings the worker's `/health` endpoint.

```python
async def _gateway_health_probe(
    worker_url: str,
    spawner: LazyWorkerSpawner,
    interval: float = 30.0,
) -> None:
    """Periodically probe worker health from the gateway side."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        while True:
            await asyncio.sleep(interval)
            if not spawner.spawned:
                continue
            try:
                resp = await client.get(f"{worker_url}/health")
                if resp.status_code != 200:
                    logger.warning("Worker health check failed: %d", resp.status_code)
            except httpx.ConnectError:
                logger.warning("Worker unreachable at %s", worker_url)
                # Trigger restart if process exited
                if spawner.process and spawner.process.returncode is not None:
                    await spawner.respawn()
```text

**Pros**:

- Detects worker crashes faster than waiting for heartbeat timeout (90s)
- Bidirectional health verification
- Simple implementation

**Cons**:

- Redundant with worker heartbeats
- Additional HTTP traffic (minor)

**Verdict**: RECOMMENDED as part of the watchdog implementation.

---

## 3. External Supervisor Comparison

### 3.1 supervisord

**What**: Process control system for UNIX. Starts, stops, restarts processes.
Configurable via INI files. Auto-restart on crash with backoff.

**Pros**:

- Battle-tested, mature
- Handles stdout/stderr logging
- Process groups (start/stop related processes together)
- Configurable restart policies (always, on-failure, unexpected)

**Cons**:

- UNIX only -- does not work on Windows
- Separate daemon process to manage
- Configuration complexity for our 2-process setup
- Doesn't understand our circuit breaker or health semantics

**Verdict**: NOT SUITABLE. Windows is our primary platform.

### 3.2 systemd (Linux)

**What**: System and service manager for Linux. Unit files define services
with restart policies, dependencies, and resource limits.

```ini
[Unit]
Description=VaultSpec A2A Gateway
After=network.target

[Service]
Type=exec
ExecStart=/path/to/venv/bin/uvicorn vaultspec_a2a.api.app:create_app --factory
Restart=on-failure
RestartSec=5
Environment=VAULTSPEC_AUTO_SPAWN_WORKER=true

[Install]
WantedBy=multi-user.target
```text

**Pros**:

- Production-grade process management
- Socket activation (start on first connection)
- Resource limits (cgroups)
- Journal logging
- Dependencies between units

**Cons**:

- Linux only
- Requires root or user lingering
- Only manages the gateway; worker auto-spawn handled internally
- Overkill for development

**Verdict**: RECOMMENDED for Linux production deployment (Phase 4). Not for
local development.

### 3.3 NSSM (Non-Sucking Service Manager)

**What**: Windows service wrapper. Wraps any executable as a Windows service
with restart policies.

**Pros**:

- Works on Windows
- Auto-restart with configurable delay
- stdout/stderr logging to file

**Cons**:

- Requires admin privileges for service installation
- Not suitable for development workflow
- External dependency

**Verdict**: OPTION for Windows production. Not for development.

### 3.4 PM2

**What**: Node.js process manager, but works with any executable.

**Pros**:

- Cross-platform (Windows + Linux + macOS)
- Auto-restart with exponential backoff
- Cluster mode (multiple instances)
- Log management
- Watch mode (restart on file change)

**Cons**:

- Requires Node.js runtime
- Designed for Node.js ecosystem
- Another runtime dependency

**Verdict**: NOT RECOMMENDED. Adds Node.js dependency for a Python project.

### 3.5 Custom asyncio Watchdog (our approach)

**What**: Background asyncio task inside the gateway process.

**Pros**:

- Zero dependencies
- Full access to application state (circuit breaker, spawner)
- Works on all platforms
- No separate daemon to manage
- Development and production compatible

**Cons**:

- Dies if gateway crashes
- No protection against event loop hangs
- Must be carefully written to not block the event loop

**Verdict**: RECOMMENDED for Phase 2. Supplement with systemd/NSSM for
production deployments.

---

## 4. Comparison Matrix

| Feature | asyncio Watchdog | supervisord | systemd | NSSM | PM2 |
|---------|-----------------|-------------|---------|------|-----|
| Windows support | YES | NO | NO | YES | YES |
| Linux support | YES | YES | YES | NO | YES |
| Zero dependencies | YES | NO | builtin | NO | NO |
| App state access | YES | NO | NO | NO | NO |
| Circuit breaker integration | YES | NO | NO | NO | NO |
| Auto-restart | YES | YES | YES | YES | YES |
| Exponential backoff | YES (custom) | YES | YES (RestartSec) | YES | YES |
| Process groups | NO | YES | YES | NO | YES |
| Gateway crash recovery | NO | YES | YES | YES | YES |
| Development friendly | YES | NO | NO | NO | NO |

---

## 5. Exponential Backoff Restart Strategy

### 5.1 Algorithm

```python
@dataclasses.dataclass
class RestartPolicy:
    max_attempts: int = 5
    base_delay: float = 1.0
    max_delay: float = 60.0
    reset_after: float = 300.0  # Reset counter after 5 min of healthy operation

    def delay_for(self, attempt: int) -> float:
        """Calculate backoff delay: min(base * 2^attempt, max_delay)."""
        return min(self.base_delay * (2 ** attempt), self.max_delay)
```text

### 5.2 Sequence Example

| Attempt | Delay | Cumulative Wait |
|---------|-------|-----------------|
| 0 | 1s | 1s |
| 1 | 2s | 3s |
| 2 | 4s | 7s |
| 3 | 8s | 15s |
| 4 | 16s | 31s |
| 5 (max) | Give up | -- |

After 5 minutes of healthy operation, the attempt counter resets to 0.

### 5.3 Crash Loop Prevention

Key property: the backoff prevents a crash loop from consuming resources.
If the worker crashes immediately on startup 5 times in a row, the watchdog
gives up and logs an error. The circuit breaker remains open, returning 503
to all dispatch requests.

Recovery requires manual intervention: fix the underlying issue and restart
the gateway (which re-initializes the watchdog).

---

## 6. Implementation Plan

### Phase 2: asyncio Watchdog

1. Add `respawn()` method to `LazyWorkerSpawner`:
   - Kill existing process (if alive)
   - Spawn new worker subprocess
   - Wait for health check
   - Update process handle

2. Add `_worker_watchdog()` background task to gateway lifespan:
   - Check worker process status every 15s
   - Restart on crash with exponential backoff (5 attempts max)
   - Reset circuit breaker on successful restart
   - Log all state transitions

3. Add dual health probe (gateway -> worker `/health`):
   - Run every 30s when worker is spawned
   - Faster crash detection than heartbeat timeout

### Phase 4: External Supervisors

4. Provide systemd unit files for Linux production:
   - `vaultspec-gateway.service` with `Restart=on-failure`
   - Worker managed internally via auto-spawn

5. Provide NSSM configuration for Windows production:
   - Wrap gateway as Windows service
   - Auto-start on boot, auto-restart on failure

6. Document daemon mode setup for both platforms

---

## 7. Recommendations

| Priority | Recommendation | Rationale |
|----------|---------------|-----------|
| P0 | asyncio watchdog with 15s poll interval | Immediate crash recovery, zero dependencies |
| P0 | Exponential backoff (1s base, 5 attempts) | Crash loop prevention |
| P0 | Circuit breaker reset on successful restart | Restore dispatch flow automatically |
| P1 | Dual health probe (gateway -> worker) | Faster crash detection than heartbeat timeout |
| P1 | `RestartPolicy` dataclass for configurable backoff | Clean separation of policy and mechanism |
| P2 | systemd unit files for Linux production | Production-grade supervision |
| P2 | NSSM setup guide for Windows production | Windows service management |
| P3 | Watchdog metrics (restart count, crash count) | Observability into worker stability |
