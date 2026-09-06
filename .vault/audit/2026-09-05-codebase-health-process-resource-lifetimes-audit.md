---
tags:
  - '#audit'
  - '#codebase-health'
date: '2026-09-05'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:3b9bac6f7218f91b44030095ac3da76c0824d1fef4e73dd058135aad71782608'
related:
  - "[[2026-07-19-codebase-health-plan]]"
  - "[[2026-09-05-codebase-health-process-resource-lifetimes-research]]"
---

# `codebase-health` audit: `process resource lifetimes`

## Scope

## Findings

### terminal-release-after-root-exit | high | Releasing an exited terminal abandons its live descendants

Type: resource leak / ownership. Status: fixed and verified. `_acp_rpc_handlers.on_terminal_release` removes registry ownership before cleanup and skips termination for an exited root. A native Windows reproduction returned successful release while a sleeping descendant remained alive. The audit explicitly reaped the leftover.

### terminal-creation-during-shutdown | high | ACP teardown permits new terminals after its cleanup snapshot

Type: concurrency / process leak. Status: fixed and verified. `AcpChatModel._cleanup_session` reaps terminals while RPC producers remain active. A real terminal created during a delayed session-cancel response survived teardown. Stop producer admission before collecting terminal resources.

### cancellation-send-deadline | high | Session cancellation can hang before its timeout begins

Type: shutdown deadlock / deadline. Status: fixed and verified. The ACP session-cancel send acquires `stdin_lock` and drains the pipe outside the response deadline. A real held-lock reproduction remained pending beyond 3.3 seconds with the provider alive. Bound the complete operation.

### cancellation-resistant-task-join | high | Task joins can delay process release indefinitely

Type: task lifetime / deadline. Status: fixed and verified. ACP gathers and Codex `wait_for` cancellation joins can await cancellation-resistant callbacks indefinitely. Use bounded waits, stop producer admission, surface survivors, and retain responsibility for resources.

### partial-provider-initialization | medium | Post-spawn setup failures can leave a provider without a cleanup owner

Type: resource leak / startup. Status: fixed and verified. ACP cleanup requires a context and both reader tasks; Codex cleanup requires a constructed client. A successfully acquired process still requires reaping when later initialization fails.

### terminal-output-backpressure | medium | Undrained terminal output can block process completion

Type: pipe backpressure / bounded resources. Status: queued under existing ACP v1 plan P01.S02. Terminal pipes are read on terminal/output while terminal/wait_for_exit waits for completion. Owner: ACP terminal output implementation. Prove continuous bounded draining above OS pipe capacity and requested retention caps.

### codex-notification-queue | medium | Slow consumers can accumulate unbounded provider frames

Type: memory bound / flow control. Status: queued. `CodexAppServerClient` uses an unbounded notification queue. Owner: provider transport flow-control follow-up. Define overload behavior preserving terminal and control events and prove bounded memory under sustained producer/consumer imbalance.

### config-home-removal-observability | medium | Failed credential-home removal is silently discarded

Type: sensitive resource lifetime / observability. Status: fixed and verified. `_codex_config_home` ignores removal failures, preventing cleanup aggregation from reporting retained copied credentials. Surface actual failures while preserving deliberate retention.

### config-home-sweep-ownership | medium | Age alone does not prove a configuration home is inactive

Type: ownership safety / destructive maintenance. Status: queued. `_config_home_roots` uses age without a live-owner identity check. Owner: configuration-home lifecycle follow-up. Add liveness-backed ownership before age-based sweeping can remove homes still in use.

### catalog-cli-unowned-teardown | high | Catalog cancellation and timeout can abandon CLI descendants

Type: process leak / cancellation. Status: fixed and verified. `discover_antigravity_catalog` spawned outside shared containment, killed only the root on timeout, and had no cancellation cleanup. Discovery now acquires through the shared provider launcher and reaps in finally. Four native Windows tests cover successful root exit with descendants, cancellation, pipe draining, and deadlines.

### catalog-output-budget-after-allocation | medium | Catalog output was limited only after unbounded buffering

Type: memory bound / pipe handling. Status: fixed and verified. `process.communicate` accumulated stdout and stderr before stdout slicing. Concurrent readers now continuously drain both pipes, retain at most one MiB of stdout, and discard stderr content.

### worker-retry-identity-regression | high | Clearing the crashed handle disabled subsequent recovery

Type: implementation regression / recovery. Status: fixed and verified. An intermediate watchdog change called spawner.shutdown before replacement, removing the identity used to authorize later retries. The final implementation reaps the old tree directly and keeps its dead handle until replacement succeeds.

### failed-startup-cleanup-owner | medium | A failed startup reap has no retained retry owner

Type: exceptional cleanup / ownership. Status: queued. `_await_worker_ready` now reports failed cleanup, but `_spawn_worker_owned` still discards its failed attempt when propagation unwinds. Owner: startup transaction recovery follow-up. Retain a retryable failed-attempt record before claiming recovery when the OS refuses termination.

### engine-wrapper-descendants | high | Engine CLI wrapper does not reap descendants on exit

Type: process leak / CLI lifetime. Status: fixed and verified. `lifecycle.engine_serve.serve` uses plain Popen, returns after root exit without tree cleanup, and suppresses a KeyboardInterrupt cleanup timeout without force escalation. Apply the existing containment owner to the engine child and reap before registry release.

### resistant-in-process-callback | medium | Python cannot forcibly stop a callback that suppresses cancellation

Type: architectural limitation / task isolation. Status: queued. Bounded task joins permit independent OS process release and report remaining tasks, but an arbitrary in-process callback can retain Python resources indefinitely. Owner: provider callback isolation follow-up. Establish cooperative callback requirements or move untrusted callbacks into supervised processes.

### provider-reap-false-success | high | Provider teardown ignored an unsuccessful termination result

Type: cleanup truthfulness / ownership. Status: fixed and verified. `_subprocess.kill_process_tree` now checks the containment or PID-tree result and raises `ProcessContainmentError` rather than logging termination and letting terminal release discard ownership. Transport release remains guaranteed.

### unrelated-process-probe-uncertainty | medium | Unreadable unrelated processes could prevent group cleanup verification

Type: portability / liveness verification. Status: fixed and verified. Linux group probing now checks process-group membership before inspecting state, so an unrelated unreadable process cannot contaminate the owned group's verdict.

### windows-failed-reap-verification | medium | Job closure after failed accounting prevents later verification

Type: exceptional cleanup / observability. Status: queued. Closing the Job Object still activates kill-on-close, but discards the accounting handle when native verification failed. Retry continues to report failure rather than inferring group death from the root. Owner: native cleanup recovery follow-up. Define a durable terminal-failure or retained-verification contract.

### codex-concurrent-close | medium | A second close could return while subprocess cleanup still ran

Type: idempotence / lifecycle. Status: fixed and verified. A native Windows `_CodexAppServerClient` reproduction returned from the second aclose while the first cleanup and provider process were still alive. Separate admission closure from a shared close task every caller joins.

### native-handle-signatures | medium | Native process probes relied on default ctypes integer handles

Type: portability / native handle ownership. Status: fixed and verified. HANDLE argument and return types are now pointer-sized for process probing and CloseHandle call sites. Tests measure repeated native process queries and empty-job release without handle-count growth.

### taskkill-helper-lifetime | high | Cancelling PID-tree cleanup could leave its taskkill helper unjoined

Type: subprocess lifetime / cancellation. Status: fixed and verified. Shared PID-tree cleanup now joins through repeated cancellation and bounds/reaps the taskkill helper in finally. Real-process cancellation regression covers owned root and descendant cleanup.

### engine-signal-cleanup | high | SIGTERM could bypass engine cleanup or interrupt process acquisition

Type: implementation regression / shutdown ownership. Status: fixed and verified. The final scoped signal handler records a stop request without raising; Popen and containment assignment complete before a bounded polling wait observes it. Signals cannot unwind the startup handoff. Normal SIGTERM enters graceful stop and forced tree cleanup. Six engine tests pass on native Windows and Linux, including actual wrapper termination.

### native-ancestry-probe-timeout | high | A timed-out PowerShell probe caused foreign-listener tests to accept ownership

Type: ownership verification / operational portability. Status: fixed and verified. The combined Windows suite exposed two existing five-second process-map timeout failures. Native Toolhelp32 snapshots replace the PowerShell/CIM subprocess, eliminating that routine helper timeout and its process overhead. Snapshot handles are closed on every exit.

### failed-close-recovery | medium | Failed provider or engine cleanup still lacks a complete retry contract

Type: exceptional cleanup / recovery. Status: queued. Codex retains a completed close task even when its independent cleanup logged failures; the engine wrapper deregisters after cleanup failure and can label an OSError from teardown as a launch error. Owner: cleanup recovery follow-up, alongside failed-startup-cleanup-owner. Separate completed cleanup from abandoned cleanup, preserve actionable ownership, and report the correct failure phase.

### optional-type-profile | low | The default environment lacks optional server imports required by the full type gate

Type: verification environment. Status: fixed and verified. The default environment reported five missing optional PostgreSQL/OTLP imports outside modified code. A separate environment synchronized from the existing lock with the server extra passes the full source type gate; the shared development environment was preserved.

### existing-strict-private-access | low | Strict provider typing reports a pre-existing protected method access

Type: code quality. Status: queued. The optional basedpyright pass reports the existing Codex `_unexpected_eof_error` cross-class access. The changed source passes the required ty gate. Owner: provider API visibility follow-up.

### unknown-ancestry-classification | medium | Unreadable ancestry was reported as confirmed ownership

Type: ownership evidence / contract drift. Status: fixed and reviewed. Native ancestry now has a three-state result; missing evidence maps to UNRESOLVED instead of CONFIRMED. The existing boolean compatibility behavior continues to accept unresolved ownership. Formal review accepted the narrow classification correction.

### final-provider-verification | low | Final provider regression evidence is recorded after close-task changes

Type: verification record. Status: complete. The final Codex chat, independent-cleanup, and provider-lifetime selection passed all 55 tests, with one existing service test deselected by repository defaults.

## Recommendations

Formal review found no remaining high or critical issue in this corrective change set. Queued findings above remain open and are not claims of completed platform certification.

## Context

# `codebase-health` audit: `process resource lifetimes`

## Scope

Audit provider and CLI process ownership across startup, cancellation, normal termination, root crash, worker restart, and repeated release. Inspect process trees, asyncio tasks and transports, terminal subprocesses, credential homes, and Windows Job Object handles. Existing accepted ownership decisions authorize corrective implementation.

## Findings

### posix-group-escalation | high | Root exit prematurely declares descendant cleanup complete

Type: resource leak / portability. Status: fixed and verified. `ProcessContainment._terminate_posix_group` waits on the root PID after signaling the group; a SIGTERM-resistant descendant survives. Require real-process coverage with both live and already-exited roots.

### worker-crash-descendants | high | Worker restart can retain the crashed generation's descendants

Type: resource leak / lifecycle. Status: fixed and verified. `_shutdown_worker_process` and `WorkerWatchdog._attempt_restart` skip group teardown after root exit. Reap retained containment before replacement and prove ports and descendants are released.

### cancellation-aborts-cleanup | high | Cancellation skips remaining provider resources

Type: resource leak / cancellation. Status: fixed and verified. `run_independent_cleanups` and `kill_process_tree` can unwind during release, abandoning later tasks, transport closure, or temporary credential cleanup. Preserve cancellation after joining the owned bounded teardown.

### empty-job-handle | medium | Terminating unused containment leaks its allocated Windows handle

Type: resource leak / native handle ownership. Status: fixed and verified. `ProcessContainment.terminate` returns before `close` when it has no PID. Exercise repeated create/terminate cycles with real native handle counts.

### launch-containment-window | medium | Assignment after Windows startup cannot guarantee containment of early children

Type: architectural limitation / portability. Status: queued. Existing `ProcessContainment.assign` relies on provider startup latency; a child created before assignment may escape the job. Owner: process launcher follow-up. Specify atomic job admission or a gated launcher with real native spawn proof before claiming containment from the first instruction.

### posix-owner-crash-and-escape | medium | POSIX groups cannot enforce automatic owner-crash or setsid cleanup

Type: architectural limitation / supervision. Status: queued. Existing session groups require a surviving cleanup owner and descendants retaining group membership. Owner: platform supervision follow-up. Establish supported containment claims and supervisor integration before asserting parity with Windows kill-on-job-close.

## Recommendations

Repair the confirmed ownership violations within the current design, run real subprocess tests with foreign-process survival assertions, review the resulting implementation, and append every additional finding and verification limit here.

### Verification record

- Native Windows: the broad initial run passed 200 tests and exposed two process-map timeout failures; the native snapshot correction then passed all 38 process/containment tests, including both failures and repeated handle-count assertions.
- Linux through WSL: all 52 selected containment, worker, provider, catalog, and engine tests passed. The final signal-handling amendment then passed all six engine tests on Linux and Windows.
- Provider regression: 148 broader provider tests passed during implementation; the new concurrent-close cases passed independently with normal and cancelled callers.
- Required full-source ty validation passes in a separate lockfile-synchronized tooling environment with the server extra. Changed Python files pass Ruff. The optional strict-type baseline issue remains queued above.
- Native macOS execution was unavailable. Platform type checks cover the POSIX/Darwin branch; runtime certification there remains outstanding.

- Final required pre-commit checks passed for the scoped files: Ruff lint/format, whole-source ty, Markdown lint, Vault Doctor, and provider artifact validation. The feature-scoped vault check also passes every check.

### provider-empty-containment-false-success | high | reopened under desktop-product-profile W04.P11.S60

Type: provider lifecycle correctness, process containment and developer-time blocker. Status: reopened/current. Review of the S49 worker assignment-failure correction exposed the same already-shipped contract drift in `providers/_subprocess.py`: `spawn_acp_process` catches `ProcessContainment.assign(pid)` failure and returns the live provider with an unassigned containment, while `_kill_process_tree` later calls that empty containment's `terminate()`. Empty containment has no process identity and returns success, so provider cleanup can report success while the retained ACP/Codex root and descendants remain live. This is distinct from the S49 worker fix and from S50 packaging.

Canonical correction owner is reopened `2026-07-18-desktop-product-profile-plan W04.P11.S60`, whose accepted row requires OS containment for every ACP/Codex provider root before descendant work. Correction must fail admission on assignment failure, reap through the exact retained provider process identity under one bound, avoid a host-wide scan or post-exit bare-pid action, preserve the original assignment error, and prove real root/descendant absence. The earlier `launch-containment-window` finding remains related architectural evidence; its vague process-launcher owner is superseded by this exact reopened Step.
