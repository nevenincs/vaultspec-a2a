# Python Supervisor Libraries Survey — 2026-03-08

## Context

VaultSpec A2A manages a 3-process chain (MCP Server -> Gateway -> Worker) with
a custom asyncio-based supervision stack: `LazyWorkerSpawner` (lifecycle),
`WorkerWatchdog` (crash detection + restart), `WorkerCircuitBreaker` (request
gating). This document surveys the Python ecosystem for supervisor libraries
that could replace or augment our custom implementation, with a focus on
asyncio-native options and Windows compatibility.

**Related documents:**

- `2026-03-08-asyncio-process-supervision-patterns.md` — our implementation patterns
- `2026-03-08-process-supervision-models.md` — industry architecture comparison
- `2026-02-25-agent-process-lifecycle-research.md` — supervisord/PM2 state machines

---

## 1. Traditional Unix Supervisors (Python-Based)

### 1.1 supervisord

**Repository**: supervisord.org
**Language**: Python 2/3 (rewritten for Python 3 support)
**Architecture**: Daemon process that manages child processes via INI config.

```ini
[program:gateway]
command=uv run uvicorn vaultspec_a2a.api.app:app --port 8000
autostart=true
autorestart=true
startsecs=5
startretries=3
stopwaitsecs=10
```text

**How it works**:

- Runs as a daemon on a Unix socket or TCP port
- Reads a `.conf` file with `[program:name]` sections
- Manages process lifecycle: start, stop, restart, status
- Supports event listeners (process state changes)
- XML-RPC API for programmatic control
- `supervisorctl` CLI for interactive management

**State machine**: STOPPED -> STARTING -> RUNNING -> STOPPING -> STOPPED
(+ BACKOFF, FATAL, EXITED, UNKNOWN)

**Windows compatibility**: NONE. Supervisord explicitly does not support
Windows. It relies on Unix signals (SIGCHLD, SIGTERM, SIGHUP), Unix domain
sockets, and `os.fork()`.

**Assessment for our use case**:

- Mature and battle-tested (15+ years in production)
- Cannot run on Windows (dealbreaker)
- Designed for server deployments, not desktop developer tools
- Would add a 4th process (supervisord itself) to our chain
- No asyncio integration — synchronous event loop internally

**Verdict**: REJECTED. Windows incompatibility is a hard blocker.

### 1.2 Circus (Mozilla)

**Repository**: github.com/circus-tent/circus
**Language**: Python 3
**Architecture**: ZeroMQ-based process and socket manager.

**How it works**:

- Uses ZeroMQ for inter-process communication
- Manages processes as "watchers" with configurable restart policies
- Supports socket activation (bind socket, fork workers to inherit)
- Plugin system for custom behavior
- `circusctl` CLI + web dashboard
- Flapping detection (too many restarts = stop trying)

```ini
[watcher:gateway]
cmd = uv run uvicorn vaultspec_a2a.api.app:app --port 8000
numprocesses = 1
warmup_delay = 3
graceful_timeout = 10
max_retry = 5
```text

**Key feature — flapping detection**:

```python
# If a process restarts more than `max_retry` times within
# `retry_in` seconds, circus marks it as "flapping" and stops it.
# Similar to our circuit breaker but at the supervisor level.
```yaml

**Windows compatibility**: LIMITED. Circus relies on ZeroMQ which supports
Windows, but the core process management uses `os.waitpid()` and Unix signals.
Circus has never officially supported Windows and issues report failures on
process group management.

**Assessment for our use case**:

- More sophisticated than supervisord (ZeroMQ, plugins, sockets)
- ZeroMQ is a heavy dependency for a dev tool
- Windows support is unofficial and unreliable
- Project activity has slowed significantly (last meaningful release 2023)
- Flapping detection is a good pattern we already implement via circuit breaker

**Verdict**: REJECTED. Stale maintenance + Windows unreliability.

### 1.3 honcho (Foreman for Python)

**Repository**: github.com/nickstenning/honcho
**Language**: Python 3
**Architecture**: Procfile-based multi-process runner (not a daemon).

```text
# Procfile
gateway: uv run uvicorn vaultspec_a2a.api.app:app --port 8000
worker: uv run uvicorn vaultspec_a2a.worker.app:app --port 8001
```text

```bash
honcho start
```text

**How it works**:

- Reads a `Procfile` with `name: command` entries
- Starts all processes, multiplexes stdout/stderr with color-coded prefixes
- When one process exits, sends SIGTERM to all others (crash-together)
- No restart logic — it's a development runner, not a supervisor
- Environment variable management via `.env` files

**Windows compatibility**: PARTIAL. Basic process spawning works on Windows.
Signal handling is limited (no SIGTERM — uses `TerminateProcess`). Process
group management is unreliable.

**Assessment for our use case**:

- Too simple — no restart policies, no health checks, no crash recovery
- Useful for development (see all logs in one terminal) but not for production
- "Crash-together" semantics are wrong for our use case (we want the gateway
  to survive worker crashes)
- No programmatic API — CLI only

**Verdict**: REJECTED. Development runner, not a supervisor.

---

## 2. asyncio-Native Process Supervisors

### 2.1 No Established Library Exists

After extensive search, there is **no widely-adopted asyncio-native process
supervisor library** on PyPI. The asyncio ecosystem has:

- `asyncio.create_subprocess_exec()` — raw process spawning
- `asyncio.subprocess.Process` — process handle with `wait()`, `communicate()`
- Various small packages (`aioprocessing`, `asyncio-subprocess`) that wrap
  the stdlib API but add no supervision logic

The absence of an asyncio supervisor library is not surprising: asyncio's
primary use case is I/O multiplexing within a single process. Multi-process
supervision is traditionally handled by:

1. The operating system (systemd, launchd, Windows SCM)
2. Container orchestrators (Docker, Kubernetes)
3. Application servers (Gunicorn, uvicorn with `--workers`)

### 2.2 uvicorn Multi-Worker as a Micro-Supervisor

**What it does**: When run with `--workers N`, uvicorn spawns a parent process
that monitors N worker subprocesses.

```python
# uvicorn/supervisors/multiprocess.py (simplified)
class Multiprocess:
    def run(self, sockets):
        for _ in range(self.config.workers):
            process = self._spawn_process(sockets)
            self.processes.append(process)

        while self.processes:
            # Wait for any child to exit
            pid, status = os.waitpid(-1, 0)
            # Respawn if signaled
            if self.should_restart:
                self._spawn_process(sockets)
```yaml

**Windows behavior**: On Windows, uvicorn uses `subprocess.Popen` instead of
`os.fork()`. The parent polls child processes via `process.poll()` instead of
`os.waitpid()`. This works but is less efficient.

**Relevance**: Our `WorkerWatchdog` follows the same pattern (poll via
`process.returncode`). Uvicorn's implementation validates our approach.

### 2.3 Gunicorn's Arbiter Pattern

**What it does**: Gunicorn's `Arbiter` class is a process supervisor that:

- Spawns N workers via `os.fork()`
- Monitors via `SIGCHLD` + `os.waitpid()`
- Implements graceful reload (spawn new workers, drain old ones)
- Uses a "heartbeat" file that workers touch periodically
- Kills workers that stop heartbeating (stale detection)

**Key insight — file-based heartbeat**:

```python
# Worker side: touch a temp file every second
self.tmp.notify()  # Writes current time to a temp file

# Arbiter side: stat the temp file
age = time.time() - os.fstat(self.tmp.fileno()).st_ctime
if age > self.timeout:
    self.kill_worker(pid)  # Worker is stuck
```yaml

**Windows compatibility**: NONE. Gunicorn is Unix-only (`os.fork()`,
`SIGCHLD`, `os.getppid()`).

**Relevance**: The file-based heartbeat is interesting as a cross-platform
alternative to HTTP heartbeats. Our HTTP heartbeat approach is more reliable
(it proves the event loop is responsive, not just that a file was touched)
but has higher overhead.

### 2.4 Celery's Process Pool

Celery uses a process pool with a supervisor (`billiard` library, fork of
`multiprocessing`). The supervisor:

- Pre-forks worker processes
- Monitors via `os.waitpid()` and signals
- Implements "max tasks per child" (restart after N tasks = memory leak protection)
- Supports "autoscale" (dynamic worker count based on load)

**Windows compatibility**: LIMITED. Celery recommends `--pool=solo` or
`--pool=threads` on Windows. The prefork pool does not work reliably.

**Relevance**: The "max tasks per child" pattern is interesting for our
worker — restarting after N graph executions could prevent memory leaks from
long-running LLM sessions. This is not currently implemented.

---

## 3. Platform-Native Supervision

### 3.1 Windows Service Control Manager (SCM)

Windows has a built-in process supervisor via the Service Control Manager.
Python services can be registered via `pywin32`:

```python
import win32serviceutil
import win32service

class VaultSpecService(win32serviceutil.ServiceFramework):
    _svc_name_ = "VaultSpecA2A"
    _svc_display_name_ = "VaultSpec A2A Gateway"

    def SvcDoRun(self):
        # Start the gateway + worker
        self.gateway = subprocess.Popen([...])
        self.worker = subprocess.Popen([...])
        # Wait for stop signal
        win32event.WaitForSingleObject(self.hWaitStop, win32event.INFINITE)

    def SvcStop(self):
        self.gateway.terminate()
        self.worker.terminate()
```yaml

**Registration**: `python service.py install` / `sc create VaultSpecA2A ...`

**Restart policy**: Configured via `sc failure VaultSpecA2A reset= 86400
actions= restart/60000/restart/60000/restart/60000` (restart after 60s on
failure, reset failure count after 24h).

**Pros**:

- Built into Windows — zero dependencies
- Survives user logoff
- Automatic restart on failure
- Visible in `services.msc` UI

**Cons**:

- Requires admin privileges to install
- `pywin32` dependency (heavy, C extensions)
- Service runs in a different session — no console access
- Debugging is painful (no stdout, must use Windows Event Log)
- Not cross-platform

### 3.2 Windows Task Scheduler

An alternative to SCM for non-admin users:

```python
import subprocess
subprocess.run([
    "schtasks", "/create",
    "/tn", "VaultSpecA2A",
    "/tr", "uv run vaultspec service start",
    "/sc", "onlogon",  # Start on user login
    "/rl", "limited",  # No admin required
])
```yaml

**Pros**: No admin privileges, survives logoff, built-in.
**Cons**: Not a real supervisor (no restart-on-crash), polling-based, clunky.

### 3.3 systemd User Units (Linux)

```ini
# ~/.config/systemd/user/vaultspec-a2a.service
[Unit]
Description=VaultSpec A2A Gateway
After=network.target

[Service]
ExecStart=/home/user/.local/bin/uv run vaultspec service start
Restart=on-failure
RestartSec=5
WatchdogSec=30

[Install]
WantedBy=default.target
```text

```bash
systemctl --user enable vaultspec-a2a
systemctl --user start vaultspec-a2a
```yaml

**Key feature — WatchdogSec**: systemd sends `WATCHDOG=1` notifications. If
the service does not call `sd_notify(0, "WATCHDOG=1")` within `WatchdogSec`
seconds, systemd considers it stuck and restarts it.

Python integration via `python-systemd`:

```python
from systemd.daemon import notify
notify("WATCHDOG=1")  # Call periodically from health check loop
```yaml

**Pros**: Built into every modern Linux, robust, well-understood.
**Cons**: Linux-only, requires user-level systemd support.

### 3.4 macOS launchd

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "...">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.vaultspec.a2a</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/uv</string>
        <string>run</string>
        <string>vaultspec</string>
        <string>service</string>
        <string>start</string>
    </array>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
```text

```bash
launchctl load ~/Library/LaunchAgents/com.vaultspec.a2a.plist
```yaml

**Pros**: Built into macOS, persistent across login, `KeepAlive` = auto-restart.
**Cons**: macOS-only, XML plist format, debugging via `Console.app`.

---

## 4. Cross-Platform Supervisor Tools

### 4.1 process-compose

**Repository**: github.com/F1bonacc1/process-compose
**Language**: Go (single binary)
**Architecture**: Procfile-like YAML config with full supervisor features.

```yaml
version: "0.5"
processes:
  gateway:
    command: uv run uvicorn vaultspec_a2a.api.app:app --port 8000
    readiness_probe:
      http_get:
        host: 127.0.0.1
        port: 8000
        path: /health
      initial_delay_seconds: 2
      period_seconds: 5
    availability:
      restart: on_failure
      max_restarts: 3
      backoff_seconds: 5

  worker:
    command: uv run uvicorn vaultspec_a2a.worker.app:app --port 8001
    depends_on:
      gateway:
        condition: process_healthy
    availability:
      restart: always
      backoff_seconds: 2
```text

**Features**:

- HTTP/TCP/exec readiness probes (Kubernetes-style)
- Process dependency ordering (`depends_on` with health conditions)
- Restart policies with exponential backoff
- Log multiplexing with TUI dashboard
- Remote API for programmatic control
- Platform support: Linux, macOS, **Windows**

**Windows compatibility**: FULL. Uses Go's `os/exec` which wraps
`CreateProcess` on Windows. Process groups managed via `CREATE_NEW_PROCESS_GROUP`
and `GenerateConsoleCtrlEvent`.

**Assessment for our use case**:

- Almost exactly what we need for the Phase 3 "daemon mode" architecture
- Single binary, no Python dependencies
- Health probes would replace our custom health-check polling
- `depends_on` with health condition eliminates our startup sequencing code
- TUI dashboard is a bonus for `vaultspec service status`
- Downside: adds a Go binary dependency (not pure Python)

**Verdict**: STRONG CANDIDATE for Phase 3 daemon mode. Could replace our
entire custom supervision stack (LazyWorkerSpawner + WorkerWatchdog +
circuit breaker startup logic).

### 4.2 nssm (Non-Sucking Service Manager) — Windows Only

**What it is**: A C utility that wraps any executable as a Windows service.

```batch
nssm install VaultSpec "C:\Users\user\.local\bin\uv.exe" run vaultspec service start
nssm set VaultSpec AppStdout C:\logs\vaultspec.log
nssm set VaultSpec AppStderr C:\logs\vaultspec-err.log
nssm set VaultSpec AppRestartDelay 5000
```yaml

**Assessment**: Simple but Windows-only. Better than raw SCM for non-Python
developers. Not a cross-platform solution.

### 4.3 pm2 (Node.js)

**What it is**: Node.js process manager with cluster mode, log management,
and deployment system.

**Python support**: pm2 can manage non-Node processes:

```bash
pm2 start "uv run vaultspec service start" --name vaultspec-a2a
```yaml

**Windows compatibility**: FULL (via `pm2-windows-service` for auto-start).

**Assessment**: Works but adds a Node.js dependency. pm2's primary value is
its ecosystem (monitoring, deployment, log rotation). For a Python project,
the Node dependency is a significant downside.

---

## 5. Python Libraries for Child Process Health Monitoring

### 5.1 psutil

Already in our dev dependencies. Provides cross-platform process inspection:

```python
import psutil

proc = psutil.Process(pid)
print(proc.status())        # running, sleeping, zombie, etc.
print(proc.memory_info())   # RSS, VMS
print(proc.cpu_percent())   # CPU usage
print(proc.children())      # Child processes (for tree kill)
```yaml

**Our usage**: `_kill_process_tree()` in `conftest.py` and `app.py` uses
`psutil.Process(pid).children(recursive=True)` for Windows process tree kill.

**Could extend to**: Worker memory monitoring (restart if RSS > threshold),
CPU stall detection (100% CPU for >60s = stuck).

### 5.2 watchdog (filesystem)

**Package**: `watchdog` on PyPI
**Purpose**: Cross-platform filesystem monitoring.

Not relevant for process supervision but worth noting: could be used for
"hot reload on code change" during development (similar to uvicorn `--reload`).

### 5.3 tenacity (retry/backoff)

Already in our dev dependencies. Provides decorator-based retry with
configurable backoff:

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=1, max=30),
    reraise=True,
)
async def _wait_for_health(url: str) -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{url}/health")
        resp.raise_for_status()
```yaml

**Our usage**: Health-check polling in `conftest.py` uses tenacity with
`reraise=True` for hard-fail on timeout.

**Assessment**: Tenacity handles the retry/backoff primitives well. Our
`WorkerWatchdog._attempt_restart()` implements manual exponential backoff
(2s, 4s, 8s) that could be replaced with tenacity, but the manual approach
is more readable for the 3-retry case.

---

## 6. Comparison Matrix

| Tool | Language | Windows | Restart | Health | asyncio | Dep Weight |
|------|----------|---------|---------|--------|---------|------------|
| supervisord | Python | NO | Yes | No | No | Medium |
| circus | Python | Broken | Yes | No | No (ZMQ) | Heavy |
| honcho | Python | Partial | No | No | No | Light |
| process-compose | Go | YES | Yes | HTTP/TCP | N/A | Single binary |
| nssm | C | YES | Yes | No | N/A | Single binary |
| pm2 | Node.js | YES | Yes | No | N/A | Heavy (Node) |
| Windows SCM | C | YES | Yes | No | N/A | Zero (built-in) |
| systemd | C | NO | Yes | WatchdogSec | N/A | Zero (built-in) |
| launchd | ObjC | NO | Yes | KeepAlive | N/A | Zero (built-in) |
| Our custom | Python | YES | Yes | HTTP | YES | Zero (stdlib) |

---

## 7. Decision Analysis

### 7.1 Phase 1 (Current): Custom asyncio Supervision — CORRECT

Our custom stack (`LazyWorkerSpawner` + `WorkerWatchdog` + `WorkerCircuitBreaker`)
is the right choice for Phase 1 because:

1. **Zero external dependencies** — uses only `asyncio.create_subprocess_exec`,
   `process.returncode`, and `httpx` (already a dependency)
2. **Full Windows support** — uses `taskkill /T /F /PID` for tree kill,
   `process.poll()` equivalent for crash detection
3. **asyncio-native** — runs as background tasks in the gateway's event loop,
   no threading or synchronization issues
4. **Tight integration** — circuit breaker gates dispatch calls directly,
   watchdog triggers spawner's `replace_process()`, health checks use the
   same httpx client as IPC

No existing library provides this combination. The closest (process-compose)
would require running a separate Go binary.

### 7.2 Phase 2 (Merge MCP+Gateway): Reduced Supervision Scope

When MCP and Gateway merge into one process (Option B from supervision models
doc), the supervision scope shrinks to just the Worker subprocess. Our existing
`WorkerWatchdog` handles this already. No library change needed.

### 7.3 Phase 3 (Daemon Mode): process-compose as Candidate

For daemon mode, where VaultSpec runs as a persistent background service:

**process-compose** is the strongest candidate because:

- Single Go binary (no runtime dependency)
- Full Windows, Linux, macOS support
- Kubernetes-style health probes (HTTP, TCP, exec)
- Process dependency ordering with health conditions
- Built-in log multiplexing and TUI dashboard
- REST API for programmatic control

**Integration sketch**:

```yaml
# process-compose.yml (shipped with vaultspec)
version: "0.5"
processes:
  gateway:
    command: uv run uvicorn vaultspec_a2a.api.app:app --port ${VAULTSPEC_PORT:-8000}
    readiness_probe:
      http_get:
        host: 127.0.0.1
        port: ${VAULTSPEC_PORT:-8000}
        path: /health
      initial_delay_seconds: 2
      period_seconds: 10
    availability:
      restart: on_failure
      max_restarts: 5
      backoff_seconds: 5

  worker:
    command: uv run uvicorn vaultspec_a2a.worker.app:app --port ${VAULTSPEC_WORKER_PORT:-8001}
    depends_on:
      gateway:
        condition: process_healthy
    readiness_probe:
      http_get:
        host: 127.0.0.1
        port: ${VAULTSPEC_WORKER_PORT:-8001}
        path: /health
      initial_delay_seconds: 3
      period_seconds: 10
    availability:
      restart: always
      backoff_seconds: 2
```text

```bash
# CLI integration
$ vaultspec daemon start     # Starts process-compose in background
$ vaultspec daemon status    # Queries process-compose REST API
$ vaultspec daemon stop      # Sends shutdown signal
$ vaultspec daemon logs      # Streams multiplexed logs
```text

This would **replace** our custom `LazyWorkerSpawner`, `WorkerWatchdog`, and
the subprocess spawning code in `api/app.py`. The `WorkerCircuitBreaker`
would remain (it gates individual dispatch requests, not process lifecycle).

### 7.4 Platform-Native Auto-Start (Phase 3 Extension)

For auto-start on login/boot, generate platform-native service definitions:

```python
def install_autostart() -> None:
    """Register VaultSpec as a login-start service."""
    if sys.platform == "win32":
        # Task Scheduler (no admin needed)
        subprocess.run([
            "schtasks", "/create", "/tn", "VaultSpec",
            "/tr", f"process-compose up -f {config_path}",
            "/sc", "onlogon", "/rl", "limited",
        ])
    elif sys.platform == "darwin":
        # launchd plist
        plist = _generate_launchd_plist(config_path)
        Path("~/Library/LaunchAgents/com.vaultspec.a2a.plist").write_text(plist)
        subprocess.run(["launchctl", "load", plist_path])
    else:
        # systemd user unit
        unit = _generate_systemd_unit(config_path)
        Path("~/.config/systemd/user/vaultspec-a2a.service").write_text(unit)
        subprocess.run(["systemctl", "--user", "enable", "vaultspec-a2a"])
```text

---

## 8. Recommendations

### Immediate (No Action Required)

Our custom asyncio supervision stack is correct for Phase 1. It handles the
specific requirements (asyncio integration, Windows support, circuit breaker
gating, lazy spawn) that no external library provides.

### Short-Term Improvements to Custom Stack

1. **Memory limit watchdog**: Use `psutil.Process(pid).memory_info().rss`
   to detect worker memory leaks. Restart if RSS exceeds threshold.
   (Related: WRK-K02 EventAggregator memory leak)

2. **Stable uptime reset**: Reset `WorkerWatchdog` retry count to 0 after
   the worker has been healthy for >30s. Currently, retry count accumulates
   and never resets (minor: max_retries=3 then circuit breaker opens).

3. **Structured watchdog events**: Emit OTel spans or structured log events
   when the watchdog detects a crash, starts a restart, or exhausts retries.
   This enables monitoring dashboards.

### Phase 3 Evaluation

When starting Phase 3 (daemon mode), evaluate `process-compose` as the
process supervisor. Key evaluation criteria:

- Binary distribution: Can we bundle process-compose with `uv` or require
  separate install?
- Config generation: Can `vaultspec daemon init` generate the YAML config?
- Health probe reliability: Test HTTP probes under Windows Defender firewall
- API stability: process-compose is pre-1.0 — monitor for breaking changes

---

## 9. Key Findings

1. **No asyncio-native supervisor library exists** on PyPI. The ecosystem
   relies on OS-level supervision (systemd, launchd, SCM) or standalone
   tools (supervisord, process-compose). Our custom implementation is the
   correct approach for an asyncio application.

2. **process-compose is the best cross-platform supervisor** for Phase 3
   daemon mode. Single Go binary, full Windows support, Kubernetes-style
   health probes, process dependencies. Would replace ~200 lines of our
   custom supervision code.

3. **supervisord and circus are Unix-only** — neither supports Windows.
   honcho is too simple (no restart logic). pm2 works but adds a Node.js
   dependency.

4. **Platform-native auto-start** (Task Scheduler, launchd, systemd) should
   be a CLI subcommand (`vaultspec daemon install`) that generates the
   appropriate config for the detected OS.

5. **psutil provides process health metrics** (RSS, CPU) that we could use
   for memory-limit-based restart. This is a short-term improvement to our
   existing watchdog.

Sources:

- supervisord.org — Process Control System
- github.com/circus-tent/circus — Mozilla Circus
- github.com/nickstenning/honcho — Procfile runner
- github.com/F1bonacc1/process-compose — Cross-platform process orchestrator
- nssm.cc — Non-Sucking Service Manager
- python `asyncio.subprocess` documentation (3.13)
- Microsoft: Service Control Manager documentation
- Apple: launchd.plist man page
- systemd.service man page
