# Library Validation: asyncio subprocess — 2026-03-08

## Standard Library Module

Package: `asyncio` (Python 3.13 standard library)
Key APIs: `asyncio.create_subprocess_exec`, `asyncio.subprocess.Process`

---

## 1. create_subprocess_exec

### Standard Library API

```python
asyncio.create_subprocess_exec(
    program, *args,
    stdin=None, stdout=None, stderr=None,
    limit=None, **kwds
) -> asyncio.subprocess.Process
```text

On Windows:

- Uses `ProactorEventLoop` (default since Python 3.8)
- Does NOT support `preexec_fn` (POSIX-only)
- `CREATE_NEW_PROCESS_GROUP` is available via `creationflags`

### Our Usage

**MCP gateway spawn** (`protocols/mcp/server.py:263-275`):

```python
process = await asyncio.create_subprocess_exec(
    sys.executable,
    "-m", "uvicorn",
    "vaultspec_a2a.api.app:create_app",
    "--factory",
    "--host", gw_host,
    "--port", gw_port,
    stdout=asyncio.subprocess.DEVNULL,
    stderr=asyncio.subprocess.DEVNULL,
)
```text

**Gateway worker spawn** (`api/app.py` in `_spawn_worker()`):
Similar pattern with `sys.executable -m uvicorn ...`

**ACP subprocess** (`providers/_subprocess.py`):

```python
proc = await asyncio.create_subprocess_exec(
    *cmd,
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    cwd=cwd,
    env=env,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0,
)
```text

### Validation

| Check | Status | Notes |
|-------|--------|-------|
| `sys.executable` for Python subprocesses | CORRECT | Ensures same Python interpreter |
| `DEVNULL` for stdout/stderr | CORRECT | Prevents output noise from child processes |
| `PIPE` for interactive subprocesses | CORRECT | ACP subprocess needs stdin/stdout |
| `CREATE_NEW_PROCESS_GROUP` on Windows | CORRECT | Enables `taskkill /T /F` on the process tree |
| No `preexec_fn` on Windows | CORRECT | Not used (would raise NotImplementedError) |
| No `shell=True` | CORRECT | Security best practice |

**Verdict**: CORRECT. All patterns are standard and platform-aware.

---

## 2. Process Termination

### Standard Library API

```python
process.terminate()  # SIGTERM on POSIX, TerminateProcess on Windows
process.kill()       # SIGKILL on POSIX, TerminateProcess on Windows (same as terminate!)
process.wait()       # Wait for process to exit
process.returncode   # None if still running, int after exit
```yaml

**Critical Windows behavior**: On Windows, both `terminate()` and `kill()`
call `TerminateProcess()`, which ONLY kills the immediate process, NOT child
processes. Grandchildren are orphaned.

### Our Usage

**Gateway shutdown** (`protocols/mcp/server.py:329-367`):

```python
if sys.platform == "win32":
    killer = await asyncio.create_subprocess_exec(
        "taskkill", "/T", "/F", "/PID", str(process.pid),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await asyncio.wait_for(killer.wait(), timeout=5.0)
else:
    process.terminate()
    await asyncio.wait_for(process.wait(), timeout=15.0)
```yaml

**Worker shutdown** (`api/app.py:439-474`): Same pattern.

**ACP subprocess** (`providers/_subprocess.py:70-95`): Same pattern.

### Validation

| Check | Status | Notes |
|-------|--------|-------|
| Windows: `taskkill /T /F /PID` | CORRECT | Kills entire process tree |
| POSIX: `terminate()` then `wait()` | CORRECT | SIGTERM with timeout, then SIGKILL |
| Timeout on `process.wait()` | CORRECT | Prevents hanging on zombie processes |
| Fallback to `kill()` on timeout | CORRECT | Force kill if graceful shutdown fails |
| `contextlib.suppress(Exception)` wrapper | CORRECT | Process may already be dead |

**Verdict**: CORRECT. Platform-aware process tree cleanup.

---

## 3. DEVNULL Pattern

### Standard Library API

```python
asyncio.subprocess.DEVNULL  # == subprocess.DEVNULL == -3
```text

Redirects stdout/stderr to the platform's null device (`/dev/null` on POSIX,
`NUL` on Windows).

### Our Usage

All subprocess spawns for gateway and worker use `DEVNULL`:

```python
stdout=asyncio.subprocess.DEVNULL,
stderr=asyncio.subprocess.DEVNULL,
```text

### Validation

| Check | Status | Notes |
|-------|--------|-------|
| DEVNULL for background services | CORRECT | Prevents output noise |
| PIPE for interactive subprocesses | CORRECT | ACP needs stdin/stdout |
| No stdout capture for services | OK | Logs go to child process's own logging |

**Observation**: Using `DEVNULL` for stderr means we cannot capture error
output from crashed subprocesses. The one exception is in `_spawn_gateway()`
(line 309-318) which reads `process.stderr` on premature exit -- but this
only works if stderr was set to `PIPE`, not `DEVNULL`. With `DEVNULL`,
`process.stderr` is `None`.

**Finding: LIB-VAL-04** (LOW): The premature exit handler in
`_spawn_gateway()` (line 309-312) tries to read `process.stderr`, but stderr
is `DEVNULL` so `process.stderr` is always `None`. The guard `if
process.stderr` handles this correctly (reads empty bytes), but the error
message will never contain useful stderr output.

**Verdict**: CORRECT usage, minor dead-code observation.

---

## 4. process.wait() and Timeouts

### Standard Library API

```python
await process.wait()  # Blocks until process exits
await asyncio.wait_for(process.wait(), timeout=10.0)  # With timeout
```text

### Our Usage

All `wait()` calls use `asyncio.wait_for()` with appropriate timeouts:

- Gateway shutdown: 5s for taskkill, 15s for POSIX terminate
- Worker shutdown: 5s for taskkill, 10s for POSIX terminate
- Final cleanup: 5s for confirmation wait

### Validation

| Check | Status | Notes |
|-------|--------|-------|
| Always use timeout | CORRECT | Never blocks indefinitely |
| TimeoutError handling | CORRECT | Escalates to kill on timeout |
| returncode check before terminate | CORRECT | `if process.returncode is not None: return` |

**Verdict**: CORRECT. No divergence.

---

## 5. Event Loop Considerations

### Standard Library Note (Python 3.13)

On Windows, `ProactorEventLoop` is the default. Subprocess support requires
`ProactorEventLoop` (not `SelectorEventLoop`).

### Our Usage

We use the default event loop (ProactorEventLoop on Windows). No explicit
loop selection.

### Validation

| Check | Status | Notes |
|-------|--------|-------|
| Default event loop | CORRECT | ProactorEventLoop on Windows |
| No `SelectorEventLoop` | CORRECT | Would break subprocess support |
| No `asyncio.get_event_loop()` deprecation | OK | We use `asyncio.get_event_loop()` in health polling, which is acceptable in running async context |

**Verdict**: CORRECT. No divergence.

---

## 6. Summary

| Area | Status | Action Needed |
|------|--------|---------------|
| `create_subprocess_exec` usage | CORRECT | None |
| Process termination (Windows) | CORRECT | `taskkill /T /F /PID` |
| Process termination (POSIX) | CORRECT | SIGTERM + timeout + SIGKILL |
| DEVNULL redirect | CORRECT | None |
| Timeout on wait() | CORRECT | None |
| Event loop | CORRECT | None |

**Findings**:

- **LIB-VAL-04** (LOW): Stderr read in `_spawn_gateway()` is dead code
  because stderr is `DEVNULL`

**Overall**: asyncio subprocess usage is fully correct and platform-aware.
All Windows-specific concerns (process tree kill, ProactorEventLoop,
CREATE_NEW_PROCESS_GROUP) are handled properly.
