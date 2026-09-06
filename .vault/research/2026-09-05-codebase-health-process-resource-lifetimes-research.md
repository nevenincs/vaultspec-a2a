---
tags:
  - '#research'
  - '#codebase-health'
date: '2026-09-05'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:e0bef2b9e6a84cd3393f063f20c631ea81801f7f178f4bbe21aa910e3025f02b'
related:
  - "[[2026-07-19-codebase-health-adr]]"
  - "[[2026-07-18-desktop-product-profile-adr]]"
---
# `codebase-health` research: `process resource lifetimes`

The audit found that the accepted ownership topology can support bounded normal teardown, but its implementation confused root exit with descendant exit and ordinary exceptions with cancellation. The corrective pass repairs those boundaries; stronger owner-crash and deliberate-escape guarantees still need platform supervision.

## Findings

### Tree membership outlives the original root

`src/vaultspec_a2a/utils/process.py` now probes complete process-group membership on POSIX and Job Object accounting on Windows. A root-only liveness probe cannot prove that an orphaned or SIGTERM-resistant descendant exited. Group probes must discount zombies, distinguish unknown from empty, and clear successfully released identities before numeric process identifiers can be reused.

### Resource acquisition and cancellation need a complete ownership handoff

`src/vaultspec_a2a/providers/_subprocess.py` retains the spawn task so cancellation cannot discard a process acquired before the await returns. `src/vaultspec_a2a/utils/async_cleanup.py` retains and joins cleanup before propagating repeated caller cancellation. Shielding without joining leaves background work behind; Python describes that cancellation distinction at https://docs.python.org/3.13/library/asyncio-task.html#shielding-from-cancellation.

### Producers must stop before their resources are collected

`src/vaultspec_a2a/providers/acp_chat_model.py` bounds the full session-cancel send and response, then stops readers and handlers before collecting terminals. `src/vaultspec_a2a/providers/_acp_rpc_handlers.py` checks session closure around terminal acquisition and removes ownership only after successful teardown. `src/vaultspec_a2a/providers/codex_chat_model.py` separates admission closure from completion of its shared cleanup task.

### Native process snapshots avoid a separate CLI lifetime

`src/vaultspec_a2a/utils/process.py` uses Windows Toolhelp32 ancestry snapshots with typed handles and guaranteed release. The previous PowerShell/CIM probe could time out under concurrent test load, degrading ownership evidence. Unknown ancestry remains explicitly unresolved; the existing boolean compatibility policy still accepts unresolved evidence. Native structure layout is documented at https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/ns-tlhelp32-processentry32w.

### Other CLI paths need the same ownership contract

`src/vaultspec_a2a/providers/antigravity_catalog.py` acquires through shared containment, drains both pipes with bounded retention, and reaps after success or cancellation. `src/vaultspec_a2a/lifecycle/engine_serve.py` records stop signals without interrupting Popen acquisition, completes assignment, and observes shutdown through bounded polling before graceful and forced cleanup.

### Native containment has limits beyond ordinary teardown

Windows Job assignment ordinarily occurs after process creation, so startup latency cannot prove containment of early descendants. The provider launcher closes that window by creating shell and exec roots suspended, assigning the retained process handle, and resuming the single initial thread only after Job admission. A failed assignment therefore has one exact suspended root and no possible descendants; killing and waiting that retained handle is complete cleanup without process-table discovery. Other Windows owners that start a root before assignment retain the general limitation. POSIX groups cannot prevent deliberate setsid escape or automatically kill children after owner SIGKILL. Python cannot forcibly terminate callbacks that suppress cancellation. Failed cleanup also needs a separate retry and ownership-recovery contract. Windows assignment semantics are documented at https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject.

## Sources

- `src/vaultspec_a2a/utils/process.py`
- `src/vaultspec_a2a/utils/async_cleanup.py`
- `src/vaultspec_a2a/providers/_subprocess.py`
- `src/vaultspec_a2a/providers/acp_chat_model.py`
- `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`
- `src/vaultspec_a2a/providers/codex_chat_model.py`
- `src/vaultspec_a2a/providers/antigravity_catalog.py`
- `src/vaultspec_a2a/lifecycle/engine_serve.py`
- https://docs.python.org/3.13/library/asyncio-task.html#shielding-from-cancellation
- https://learn.microsoft.com/en-us/windows/win32/api/tlhelp32/ns-tlhelp32-processentry32w
- https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject
