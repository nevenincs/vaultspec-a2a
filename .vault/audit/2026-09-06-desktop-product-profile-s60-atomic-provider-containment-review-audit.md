---
tags:
  - '#audit'
  - '#desktop-product-profile'
date: '2026-09-06'
modified: '2026-09-19'
body_schema: 'body-v2'
body_hash: 'sha256:eedb793cd60b078f63d5460b74636742ea485dc4681763049264d33109ba02e8'
related:
  - "[[2026-07-18-desktop-product-profile-adr]]"
  - "[[2026-07-18-desktop-product-profile-research]]"
  - "[[2026-07-18-desktop-product-profile-plan]]"
  - "[[2026-09-05-codebase-health-process-resource-lifetimes-audit]]"
---
# `desktop-product-profile` audit: `S60 atomic provider containment formal review`

## Scope

Formal review of implementation commit `412c5532` for reopened plan Step `W04.P11.S60`. The review covered all nine committed paths, the governing ADR, research, plan, historical `W04.P11` summary, current S60 execution record, process-resource-lifetimes audit, reopen trace `141147db`, and S49 exact-identity correction `d8453cf0`.

The intended contract is atomic Windows provider admission through `CREATE_SUSPENDED`, exact retained `Popen` process-handle assignment to a kill-on-close Job Object, one documented initial-thread resume after successful assignment, and bounded exact cleanup before any failed spawn returns. POSIX must retain new-session/process-group ownership. No legacy, deprecated, translation, PID-only fallback, machine-wide scan, or compatibility path is authorized.

Verdict: **FAIL**. The suspended launch, Job assignment, resume ordering, assigned-Job teardown, root-exit teardown, late-child containment, transport release, normal cancellation join, and POSIX branch are structurally correct and pass focused real-process verification. One high ownership finding and one medium current-contract finding block S60 closure.

## Findings

### exact-popen-cleanup-scans-host | high | Admission-failure cleanup enumerates every process on the machine

Type: process ownership, operational scalability, and developer-time blocker. Status: open and blocking `W04.P11.S60`. `terminate_exact_popen_tree()` calls `psutil.Process.children(recursive=True)`. The project-locked psutil implementation constructs `_ppid_map()` before walking descendants; on Windows that is a machine-wide process enumeration. The implementation therefore contradicts both its own no-host-scan claim and the reopened Step's exact-identity cleanup contract. A busy or degraded host can make the failure path slower and less predictable, and the provider path now couples an exact retained root to unrelated host process-table availability.

Restore the S49 worker implementation and ownership unchanged instead of sharing this provider helper. An unassigned production provider is still the exact `CREATE_SUSPENDED` root and cannot have created descendants before its first instruction, so assignment failure must kill and wait that retained root handle only. A failure after Job assignment, including initial-thread resume failure, must terminate through the assigned Job. Prove the real production spawn seam with a closed-Job assignment failure: the first-instruction marker remains absent, the exact root is gone under the bound, and the original assignment error remains authoritative. No parent map, process-table scan, PID reopen, or post-exit bare-PID action may participate.

### unassigned-containment-pid-fallback-retained | medium | Dead fallback behavior remains in the containment authority

Type: current-only contract and hidden compatibility path. Status: open and blocking `W04.P11.S60`. `ProcessContainment._terminate_owned()` still contains an unassigned `_pid` branch that logs and calls `kill_pid_tree_async()`. Current constructors set `_pid` only together with `_assigned`, so the branch is unreachable through the supported state machine. Retaining a PID-tree downgrade for a state the current API cannot produce conflicts with the explicit current-only and no-fallback contract and obscures the fact that empty containment is never process authority.

Remove the unreachable downgrade and fail closed if an internally inconsistent unassigned containment ever carries a PID. Keep current callers responsible for cleanup through their retained process or assigned OS containment authority.

## Recommendations

Correct both blocking findings in one S60 amendment, retain the existing accurate queue ownership for the separate pytest zero-peer startup delay and the two stale integrated fixtures, and rerun the native shell/exec, late-child, root-exit, closed-Job production failure, cancellation, worker-regression, static, and Core gates. Keep S60 and its phase open until the amended implementation receives another formal review.

Review verification on native Windows:

- provider containment plus S49 worker regression: 16 passed in 9.15 seconds, 13.91 seconds wall;
- provider, process-containment, worker-spawn, and unready-worker focused set: 35 passed in 17.22 seconds, 22.25 seconds wall;
- integrated provider-owned process-tree cases: 2 passed and 2 deselected in 10.91 seconds, 15.42 seconds wall;
- Ruff lint and format: pass on all five changed Python files;
- ty: pass on the three changed production modules;
- committed diff whitespace check: pass;
- observed process survivors: zero in the executed real-process gates.

The process-resource-lifetimes audit correctly limits the S60 claim to provider containment, records the corrected inherited-pipe proof, and keeps the roughly 23-second zero-peer startup delay plus two stale integrated fixtures with separate owners. This review did not reproduce the full 23-second startup delay; it does not close or reclassify that queued finding.
