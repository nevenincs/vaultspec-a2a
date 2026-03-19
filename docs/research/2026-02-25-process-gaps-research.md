---
name: 'Process Gaps Research'
date: 2026-25-02
type: research
summary: 'Rigorous analysis of Windows 11 subprocess management for A2A agents, detailing pywin32 Job Object implementation and state machine thresholds.'
maturity: 75
feature: process-gaps
---

## Process Gaps Research

**Date**: 2026-02-25
**Domain**: Process Lifecycle

## 1. Windows Orphan Prevention: pywin32 vs. ctypes (Gap G1)

**Architectural Problem**: The orchestrator spawns agents as child subprocesses.
If the orchestrator crashes or is force-killed on Windows, it leaves behind
"orphan" agent processes that continue consuming CPU, memory, and expensive API
tokens, while locking up ports. POSIX signals (`SIGTERM`) do not exist natively
on Windows.

**Inclusion/Exclusion Decision**:

- **Excluded**: `atexit`handlers or manual`psutil.Process(pid).kill()`. These
  fail if the parent process receives a hard crash (e.g., `taskkill /F`).
- **Excluded**: `ctypes`bindings to`kernel32.dll`. While dependency-free,
  manually managing memory pointers and
  `JobObjectExtendedLimitInformation`C-structs in Python is highly error-prone
  and difficult to maintain.
- **Included**:`pywin32`(specifically`win32job`). Verified locally to support
  Python 3.13 (`pywin32-311-cp313`). It provides robust, memory-safe Python
  wrappers around the Windows API.

**Implementation Reference (Windows Job Objects)**:
To guarantee OS-level cleanup, the orchestrator must assign every spawned agent
to a Windows Job Object configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`.

```python
import win32api
import win32con
import win32job
import subprocess

def spawn_agent_in_job(cmd: list[str]):
    # 1. Create a headless job object
    hJob = win32job.CreateJobObject(None, "")

    # 2. Configure the OS to kill all children when the parent handle closes
    info = win32job.QueryInformationJobObject(hJob, win32job.JobObjectExtendedLimitInformation)
    info['BasicLimitInformation']['LimitFlags'] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    win32job.SetInformationJobObject(hJob, win32job.JobObjectExtendedLimitInformation, info)

    # 3. Spawn the subprocess (suspended)
    proc = subprocess.Popen(cmd, creationflags=win32con.CREATE_SUSPENDED | win32con.CREATE_NEW_PROCESS_GROUP)

    # 4. Assign the process to the Job, then resume
    handle = win32api.OpenProcess(win32con.PROCESS_SET_QUOTA | win32con.PROCESS_TERMINATE, False, proc.pid)
    win32job.AssignProcessToJobObject(hJob, handle)
    # Windows API requires resuming the main thread (implementation details via pywin32...)

    # Crucial: The orchestrator MUST keep `hJob` in memory. If hJob is garbage collected, the child dies.
    return proc, hJob
```text

## 2. Process State Machine: Startup Stability Threshold (Gap G2)

**Architectural Problem**: AI Agents, particularly those loading large contexts
or native binaries, have highly variable startup times. Using a naive `PID
exists`check results in false positives ("Running but not ready").

**Inclusion/Exclusion Decision**:

- **Excluded**: Simple`process.poll() is None`(too optimistic, port may not be
  bound).
- **Excluded**: 1-second`startsecs`(Supervisord default). Too short for LLM
  tools initializing local state.
- **Included**: A two-tier`READY`vs`RUNNING` state progression with a
  **30-second stability threshold** (inspired by PM2).

**Rationale**:

1. **`STARTING`->`READY`**: Transition occurs when an HTTP `GET
/.well-known/agent.json` returns HTTP 200. This confirms the ASGI server
   (Uvicorn) is bound and the A2A routing layer is responsive.
2. **`READY`->`RUNNING`**: Transition occurs _only_ if the process survives for
   **30 seconds** without exiting.
   - If it crashes `< 30s`: It is classified as a `STARTUP_FAILURE`. The process
     manager triggers aggressive exponential backoff (e.g., 2s -> 4s -> 8s) to
     prevent CPU thrashing.
   - If it crashes `> 30s`: It is classified as a `RUNTIME_FAILURE`. The retry
     counter is reset to 0, assuming the crash was data-driven (e.g., bad LLM
     context) rather than a fundamental environment failure.
