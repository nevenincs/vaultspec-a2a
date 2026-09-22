---
tags:
  - '#audit'
  - '#open-issue-remediation'
date: '2026-09-21'
modified: '2026-09-22'
body_schema: 'body-v2'
body_hash: 'sha256:52218ebd13505e3ac0f88a5afecfbf21410409a0741279b89f111f35eb9b7c16'
related:
  - "[[2026-09-21-open-issue-remediation-plan]]"
---
# `open-issue-remediation` audit: `rolling backlog implementation review`

## Scope

Rolling review of plan execution against current A2A and Dashboard contracts.
Completed review covers P01.S02's Dashboard relay mapping and issue disposition.
P01.S03's Compose workspace-boundary defect remains open pending its execution
boundary Step P01.S10. P01.S06's read-only-hook defect is resolved below, with
its implementation, focused verification, and review evidence recorded before
Step closure. P01.S02 is PASS with no critical or high finding in that lane.

## Findings

### workspace-admission-hardening | high | validation could be bypassed before canonical workspace admission | resolved

P01.S03's independent Terra review confirmed the prior prepare/commit preset
read-before-validation defect is fixed: `gateway.py:277` canonicalizes before
validation, and managed foreign, ancestor, and symlink cases are exercised at
both stages. `test_workspace_root_authority.py` passed all 14 tests with a clean
diff; the Sol full review (67 tests) plus Ruff and Ty also passed. The admission
portion of the issue #25 boundary is resolved. The issue remains open for the
separate P01.S10 OS execution-identity and ACP confinement proof.
### compose-provider-service-state | high | admitted roots and shared identity expose credentials and durable state | open

Development, integration, and production Compose profiles mount one `/app/data`
volume into gateway and worker under the same UID/GID. The database,
`a2a-home/service.token`, and workspaces are siblings below that mount. Run
admission accepts any existing absolute directory, so an authenticated request
selecting `/app/data` gives ACP `fs/read_text_file` direct, confirmed reach to
the bearer handoff and database. Mode 0600 does not separate processes with
the same UID. A path-prefix rule alone is insufficient because provider and
terminal children inherit the worker identity and can name absolute paths outside
their working directory.

The superseded workspace-root ADR incorrectly treated mounts as the complete
boundary. The accepted replacement requires Compose-only canonical descendant
admission plus a distinct, capability-free agent UID/GID for every provider and
terminal/tool child, owner-only service state, and a gateway-only credential
mount. P01.S03 owns admission; P01.S10 owns the OS boundary and negative live
proof. Issue #25 remains open until both pass.

### compose-provider-acp-toctou | high/security | privileged ACP callbacks resolve paths before no-follow access | open

P01.S03/P01.S10 review identified a resolve-to-open time-of-check/time-of-use
exposure in privileged ACP read/write callbacks: a path can be resolved and
validated before an attacker swaps a directory or symlink before the open or
create operation. P01.S10 now owns `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`
and `src/vaultspec_a2a/providers/tests/test_project_confinement.py` in addition
to its existing Compose/provider boundary paths. The required proof is
Linux/Compose descriptor-relative, no-follow traversal for reads and
write/create ancestor traversal, directory anchoring, bounded handle lifetime,
and fail-closed behavior, while preserving desktop compatibility. No proof is
claimed yet; issue #25 remains open pending S03 admission and S10 OS-boundary
implementation plus negative live tests.

### workspace-admission-independent-review | high | independent review confirms canonical admission correction | resolved

The independent P01.S03 review passed: the canonicalize-before-validation
correction at `src/vaultspec_a2a/api/routes/gateway.py:277` is exercised across
managed foreign, ancestor, and symlink cases at both prepare and commit. The
focused admission suite passed 67 tests, including 14 independent boundary
cases, and the scoped Ruff and Ty checks passed. The high admission finding is
resolved and S03 is ready to close; no GitHub issue action is taken in this
metadata pass, so issue #25 remains an integrated disposition for P02.S09.

### compose-callback-root-anchor | high/security | intermediate run-root replacement bypassed descendant-only anchoring | resolved

P01.S10 review found that descriptor-relative callback traversal began from the
resolved run-root pathname, leaving intermediate components exposed to a
resolve-to-open replacement race. The correction opens the configured managed
workspace boundary first and traverses every admitted run-root and request
component with no-follow directory handles. The real Linux image proof replaces
an intermediate run-root directory with a symlink to `/app` between resolution
and open; the callback refuses it without reading the service-state sentinel.

### compose-workspace-sharing | high/compatibility | distinct identities could not exchange new or upgraded workspace files | resolved

P01.S10 review found that the service umask and top-directory-only ownership
change made agent-created files unreadable to worker callbacks, callback-created
files unreadable to the agent, and legacy UID/GID 1001 project content
non-writable by UID/GID 1002. The shipped worker profiles now explicitly opt
service-owned named volumes into a bounded no-follow migration that mirrors
owner access to the agent group and preserves executable bits. The launcher sets
a group-sharing umask only after dropping identity; callbacks explicitly create
shared workspace entries. Custom bind mounts receive validation rather than
recursive mutation. The real image proof starts from legacy ownership, executes
a migrated tool, performs bidirectional callback/agent reads and writes, and
confirms hard-linked service state fails closed without mutation.

### compose-provider-boundary-final-review | low | final security review PASS with no remaining finding | PASS

The independent `security_final_review` for P01.S10 found no critical, high, or
medium finding. The real production image proof passed 3/3; the Compose proof
suite passed 17/17; and the focused boundary run passed 30 checks, with eight
Windows-only skips covered by the Linux proof. Ruff, Ty, and configuration
checks passed. The evidence covered the actual child UID/GID, empty
supplementary groups, zero capabilities, `no_new_privs`, private environment
and database state, legacy bidirectional workspace I/O, anchored callback
traversal, hard-link refusal without mutation, and launcher failure closed.
The original service-state and callback TOCTOU highs, plus the two resolved
review highs above, are discharged. S10 is ready to close; GitHub issue action
remains outside this metadata commit and belongs to integrated P02.S09
disposition.

### compose-confinement-test-typing | low/quality | os.open race wrappers were too broad for the locked Ty contract | resolved

The S10 integration hook found six Ty diagnostics in the two descriptor-race
test wrappers: their `object`-typed path, mode, and keyword arguments could not
be passed safely to `os.open`. The wrappers now mirror the real `os.open`
signature, preserving the same swap trigger and delegation while making the
test boundary typed. The confinement file passed its focused run (28 passed,
three Windows skips), and the full Ty gate passed.

### lifecycle-readiness-final-review | high/security | unresolved-listener credential probe is discharged | resolved

The independent final P01.S01 review passed two real lifecycle-manager
token/readiness tests and one live Jaeger trace test. The unresolved listener
path was code-reviewed: HTTP readiness is withheld, and the credentialed
worker probe is skipped, until listener ownership is confirmed. No remaining
S01 finding was identified. S01 is ready to close; issue #18 disposition is
recorded here without external GitHub action.

### staged-hook-isolation | low | shared dirty worktree hid concurrent S03 symbols from staged hooks | resolved

The first shared-worktree S06 commit attempt correctly ran the normal hooks but
Ty isolated unstaged S03 changes and reported the staged snapshot's missing
`require_admitted_workspace_root` import. No hook was bypassed and no concurrent
source was staged. The exact ten-file S06 snapshot was reproduced in a clean
sibling worktree from the index, with the locked project environment including
the `server` extra, and the complete hook suite passed before commit. S05 was
then validated and committed separately on that branch. Main remains dirty with
other workers' changes; integration is deliberately left to the coordinator.
This is a low process constraint, not a source defect.
### kimi-provider-gate | medium | CI credential cases could silently skip without kimi-cli | resolved

P01.S05 found that the provider gate installed Codex but did not provision or
require the pinned Kimi CLI, allowing the three historical Kimi configuration
and credential cases to disappear as skips in CI. Resolution: the workflow now
installs the project-authoritative `kimi-cli==1.49.0` and exposes its `uv tool`
bin directory through `GITHUB_PATH`; `Justfile` requires `kimi-cli` and names
all three Kimi cases explicitly alongside the three Codex controls. The
isolated locked run passed all six cases with zero skips, and actionlint plus
the CI contract check passed. The served-provider completed-turn eligibility
lane remains separate and unchanged; no paid live provider turn was used.
Independent review found no remaining critical, high, or medium finding in this
lane. Issue #57 is ready for coordinated closure after commit integration.
### prek-annotation-enforcement | high | read-only Core check warns but exits successfully | resolved

The P01.S06 implementation review found that the direct
`vaultspec-core vault check annotations` command reports a malformed annotation
as WARNING and exits zero. A hook that merely replaces the mutating sanitizer
with that command is read-only but silently admits the condition it is meant to
reject.

Resolution: Core 0.2.2 exposes no strict or fail-on-warning option for this
check. `dev/vault_annotations_gate.py` now invokes the locked Core module with
`vault check annotations --json`, forwards its real diagnostic envelope, and
fails when Core reports a positive `data.diagnostics.total` (or malformed
output), without reimplementing annotation parsing. `prek.toml` keeps the
historical managed hook ID for migration compatibility while routing validation
through this wrapper. The explicit `Justfile` maintenance sanitizer remains
separate and operator-invoked.

The behavioral regression in `dev/tests/test_prek_config.py` uses real isolated
Core workspaces: the clean fixture exits 0 and the bad fixture exits 1 on
Core's warning diagnostic, while complete fixture byte snapshots remain
unchanged in both cases. `pytest dev/tests/test_prek_config.py -q` passed 3/3;
`prek run vault-sanitize-annotations --all-files --no-progress`,
`prek validate-config prek.toml`, and Core precommit migration dry-run all
passed (migration status `unchanged`). Ruff, Ty, and diff checks also passed.
The HIGH gate-semantics finding is therefore resolved with no remaining
critical or high finding in this lane.

### prek-format-baseline | low | locked Taplo formatting check conflicts with Core-managed block | queued

`taplo lint prek.toml` passes, while the locked `taplo fmt --check prek.toml`
command reports the pre-existing Core-generated managed hook block as
unformatted on both the baseline and this patch. Reformatting that block would
rewrite Core-owned output outside this Step's authority. This is a pre-existing
validation/tooling baseline, not a defect introduced by the read-only wrapper;
keep it queued for the Core/tooling owner and do not treat it as an S06 blocker.

### plan-ordering | low | plan check warns on intentional phase ordering | queued

`vaultspec-core vault plan check 2026-09-21-open-issue-remediation-plan`
reports PLAN022 because P02.S09 follows P01.S10 in document order while its
numeric identifier is lower than that preceding Step. The row placement reflects
the plan's explicit integration phase, not an S06 edit. It remains a low
metadata warning for the integrated plan review and is not an S06 blocker.

### dashboard-relay-live-proof | medium | replay behavior lacks one live connected recovery certification | open

The current engine and frontend implement sequence-aware reconnect, explicit
gap signaling, authoritative run-status reconciliation, a 4 MiB engine ring,
and a browser transcript bound of 256 events or 2 MiB. Focused frontend tests
passed 61 cases. The remaining gap is a live connected A2A gateway proof that
drops the browser relay after a known sequence and observes delta replay or an
honest gap followed by terminal status reconciliation. Dashboard issue #137 and
plan Step P01.S08 own it.

### retired-ui-issues | low | five legacy issues no longer describe owned source surfaces | closed

Issues #30 and #31 are satisfied by the current relay replay and browser bounds.
Issues #33 and #34 prescribe retired Valibot, openapi-fetch, and rest-client
surfaces; current Dashboard adapters are intentionally hand-written and
tolerant. Issue #40 describes a removed in-repository UI and service-harness
bridge. All five issues were closed with their current disposition and the live
recovery residue linked to Dashboard issue #137.

### dashboard-rust-tooling | low | configured Cargo path blocked the Rust check | queued

The configured executable `X:/ci-shared/cargo/bin/cargo.exe` was absent, so the
Dashboard engine Rust tests did not run during this review. No conclusion was
drawn about whether another installed Rust toolchain exists. The passing 61-case
frontend result does not substitute for that engine-side check.

## Recommendations

- Complete P01.S03 before P01.S10, then close issue #25 only after real provider
  and terminal/tool children can work in the workspace but receive OS denial for
  token and database sentinels, while privileged callbacks reject symlink escape.
- Keep P01.S06 closed with the Core-diagnostic wrapper and byte-preserving
  regression; retain the explicit maintenance sanitizer outside validation.
- Keep the low Taplo managed-block baseline queued for the Core/tooling owner;
  do not reformat generated hook output in this Step.
- Resolve the PLAN022 ordering warning during the integrated plan review if the
  intentional phase ordering should be represented differently; it is not an
  S06 implementation blocker.
- Execute P01.S08 against a controlled live A2A gateway and close Dashboard
  issue #137 only on observed replay or honest gap and run-status convergence.
- Resolve or locate the Dashboard Rust toolchain before claiming engine-route
  test coverage; keep the absence classified as tooling until checked.
- Keep the five legacy A2A issues closed; future work belongs to current
  Dashboard paths and issue #137 rather than recreating the retired UI surface.

### locked-quality-type-policy | medium/type-policy | prohibited type suppressions removed without replacement | resolved

P01.S11's exact staged snapshot removes the prohibited suppressions without
adding another type escape. The lock-pinned Ty gate passes.

### locked-quality-type-safety | medium/type-safety | reviewed S11 snapshot is clean under the official Ty gate | resolved

The isolated source snapshot exactly matches the shared staged index for all nine
S11 paths. The official Ty command over `src dev docs scripts` passes.

### locked-quality-format | low/formatting | S11 snapshot passes focused Ruff validation | resolved

Focused Ruff validation passes for every Python path affected by the S11 snapshot.

### locked-env-example-service-identity | medium/CI-blocking | root operator example documents required Compose agent identity variables | resolved

`.env.example` documents the launcher, UID and GID defaults, states the host or
desktop exclusion, and the deterministic coverage test passes. The Compose
service boundary remains an S10 dependency already present in this chain.

### blocked-stream-cancel-dispatch | high/concurrency | stable CANCELLING/RECONCILING cancel redrive and stale-CAS refusal | resolved

P01.S12 integrates the reviewed cancellation correction. Direct recovery redrives
only the stable cancellation states; terminal and stale claims refuse through the
compare-and-set result. The focused in-process suite passed 175 tests, including
C-before-T cancellation and T-before-C rejection; independent real-service output
records 4/4 passed in 163.90s at
`C:/Users/hello/AppData/Local/Temp/vaultspec-s12-arch-service-20260921.out`.

### blocked-stream-cancel-settlement | high/correctness | cancellation terminalizes once after active work settles | resolved

The executor preserves terminal-election and per-thread cleanup ordering: the
C-before-T race produces one exact CANCELLED terminal result, while a prior
terminal claim rejects cancellation. Capacity remains unavailable until cleanup
has completed. The independent service summaries retain the stable restart
redelivery transition `accepted_not_applied -> cancelled_no_active_work`.

### blocked-stream-cancel-post-read | medium/concurrency | cancellation wins over a completed blocked read and EOF is rechecked | resolved

Ingest races the cancellation event against the blocked next-event await, then
rechecks state after a read and at EOF. Watchdog and generator cleanup behavior
is unchanged. The focused 175-pass evidence and both captured real-service 4/4
passes cover blocked/pre-ingest cancellation and restart redelivery without test
padding.

### blocked-stream-cancel-lifecycle-evidence | low/test-evidence | independent process evidence covers cancellation lifecycle and redelivery | resolved

The isolated review recorded PASS: 175 focused in-process tests and an
independent four-case real service run. Service artifacts exist at
`C:/Users/hello/.vaultspec-a2a/runtime/service-tests/vaultspec-service-tests-2b9990ec/session-summary.json`
and `C:/Users/hello/.vaultspec-a2a/runtime/service-tests/vaultspec-service-tests-26323e17/session-summary.json`.
Issue #73's implementation scope is closed locally; no external GitHub mutation
is made in this integration commit.

### sqlite-terminal-election-contention | medium/operational-concurrency | bridge retry recovered SQLITE_BUSY during exact cancellation election | open

A real service run observed one `SQLITE_BUSY` at `event_handlers.py:161` during
terminal election; the bridge retry recovered it. P01.S13 owns reproduction and
an evidence-backed choice: prove that bounded retry is the intended contract, or
correct bounded transaction/retry behavior with focused concurrency coverage.

### sqlite-terminal-election-contention-rereview | medium/operational-concurrency | bounded bridge retry recovers the exact terminal receipt after SQLite busy | resolved

P01.S13 reproduced the contention with a real file-backed SQLite `BEGIN IMMEDIATE` writer lock and a zero lock-wait budget. The terminal handler raised the underlying `sqlite3.OperationalError("database is locked")` at the election write; after the transient HTTP failure released the lock, the real `WorkerBridge` retried the unchanged event batch and the second attempt settled the exact `terminal-election-receipt`. The regression recorded exactly two attempts, equal serialized batches, and one durable cancellation: the action is applied with its claim cleared, the thread is `cancelled`, and `run_revision` is `1`. The production bridge loop is explicitly bounded by `ipc_max_flush_retries` (default three) with exponential backoff, and the terminal CAS/evidence receipt makes the duplicate delivery idempotent. No production correction is required. Focused event-handler tests passed 22/22, WorkerBridge IPC tests passed 24/24, and Ruff, format, and Ty passed.

### release-preparation-review | low | P01.S04 review PASS; local preparation preserves Dashboard-owned release-set selection | PASS

The integrated release preparation path accepts only an explicit workflow-dispatch prepare operation, produces reviewable version, lockfile, and changelog metadata, and keeps publication restricted to an existing exact tag at checked-out HEAD. Ten isolated fixtures, workflow/actionlint/YAML contracts, Ruff, Ty, and compilation passed. The direct dry-run and expected failing check left all release metadata byte-identical. No critical, high, or medium finding was identified. Issue #26 remains for the coordinator's integrated disposition; this Step made no external issue change.
### fresh-ingest-recovery-lease-race | high/correctness | fresh INGEST acceptance can race periodic recovery before its lease is durable | open

The initial `INGEST` path in `src/vaultspec_a2a/control/thread_service.py` needs an evidence-backed prepare/finalize claim boundary: action, fresh lease, writer, exact receipt, and requested projection must commit atomically before network delivery. Definite dispatch failure must release the lease; ambiguous delivery must retain it until expiry; successful delivery remains leased until incorporation evidence; periodic recovery must neither claim nor refuse fresh active ingest. No global delay, heartbeat heuristic, or timeout padding is an acceptable substitute.

P01.S14 owns the correction under the accepted control-action-leases decision, with focused initial-dispatch/recovery-race tests and an exact real lazy-worker proof. This metadata pass changes no source and does not claim implementation or closure. Dashboard handoff evidence remains separate: the latest reported live certification was 2/2 in 21.8s, but no run IDs or timeline artifact is present in this A2A/Dashboard vault corpus; the coordinator must attach those identifiers before P01.S08 closure rather than inventing them.
### fresh-ingest-recovery-lease-race | high/correctness | resolved

P01.S14 now commits the initial INGEST action, fresh lease, current writer, exact graph receipt, and requested projection in the accepting transaction before worker delivery. Definite non-delivery releases only the exact lease; ambiguous delivery retains it. A worker acknowledgement moves the run to `running` but does not settle action incorporation or clear its lease. The shared failure owner refreshes the current locked thread and yields to an inactive or newer winner rather than recording stale recovery. A held-ack, real SQLite/ASGI regression drives the actual periodic recovery pass and proves it neither claims, refuses, nor redelivers fresh active ingest; it retains the original receipt and lease. The focused control/action-lease bundle passed 27/27 in 32.80s, API run-start passed 4/4, and the independently captured real lazy-worker case passed 1/1 in 21.88s with RUNNING, healthy worker status, and cancellation inside 30 seconds.

### p01-s14-final-review | low/review | PASS

Review of the changed acceptance, failure, recovery, and lazy-worker paths found no critical or high finding. The only implementation correction was the resolved cached-thread failure observation: the shared helper now locks and refreshes current state before recording recovery, preserving a concurrent terminal or cancellation winner. No delay, heartbeat, timeout padding, or replacement dispatch identity was added. The explicit restart-redelivery case retains its existing lease-TTL margin; ordinary lazy start is bounded to 30 seconds.
### canonical-dispatch-id-concurrency-deadlock | high/test-infrastructure-or-correctness | deterministic full-prefix stall blocks the canonical dispatch-id concurrency proof | open

Canonical CI reproduced a deterministic full-prefix stall at `src/vaultspec_a2a/worker/tests/test_dispatch_ids.py:179`: two `ThreadPoolExecutor` `TestClient` requests block through the AnyIO portal while the test holds the executor ingest lock. This evidence does not yet distinguish a test-infrastructure deadlock from a production correctness defect. P01.S15 owns the bounded root-cause proof and a non-timeout correction while preserving identical-capacity exactly-once behavior; durable CI log/session evidence and temporary-resource cleanup are required.

### canonical-api-cluster-isolation | high/CI-blocking | timeout hides the first traceback in recurring canonical API failures | open

Two canonical runs recorded 40 failure marks across five API files, while 136/136 serial tests and the xdist subset passed. The later timeout aborted both runs before any traceback identified the first failing operation. P01.S16 first eliminates or avoids the shared deadlock, captures a `-x` canonical prefix to obtain the first traceback, and then fixes the real shared state, environment, or runner-isolation defect without serializing the whole suite or weakening assertions. Durable log/session evidence and cleanup remain required.

### canonical-dispatch-id-concurrency-deadlock-rereview | low/review | PASS

P01.S15 review found the stall was test-infrastructure ordering, not a production capacity defect: same-thread duplicate requests serialize at terminal arbitration, leaving one request on the held ingest lock and the other behind the arbitration lock. The corrected real TestClient/ThreadPoolExecutor tests await two arbitration users and one ingest waiter, release the held lock in finally, and assert identical replay or distinct-ID refusal. No critical or high finding remains in the changed path. Full dispatch-ID coverage passed 6/6; Ruff format/check and Ty passed. The ignored durable run log is `tmp/s15-dispatch_ids-full.log`.
### canonical-api-cluster-isolation-bootstrap | high/CI-blocking | eager testing package import preempts canonical environment bootstrap | resolved

The captured canonical runner evidence identifies the first shared failure: `testing/__init__.py:21-25` eagerly imports environment/settings before root `conftest.py` sets `VAULTSPEC_ENVIRONMENT=development`. The canonical serial runner consequently constructs `Settings` with the environment undeclared; `/internal/events` returns HTTP 500 and 40 API tests fail. The xdist subset inherits the later declaration and passes, explaining the cluster isolation split. This is a test runner/bootstrap isolation defect, not permission to relax fail-closed production policy or leak a global environment variable. P01.S16 owns the correction in testing bootstrap/runner files and focused tests, with a fresh `-x` canonical prefix and durable cleanup evidence required.

The canonical log recorded 41 failure headings over 24m03.356 total and exited 124 at the 10s post-session reporter deadline. Its exact timing record is: unit owner >=1351.4s, harness 25.25s, total 1443.356s; no `--durations` block flushed. This exit is a runner measurement issue separate from the IPC finding and does not prove a leaked descendant. No additional performance metric is inferred.

P01.S16 resolution and review (2026-09-21): The canonical child now imports `vaultspec_a2a.testing` through a lazy PEP 562 facade, so importing `runner_child` cannot import settings before the child declares its test environment. `runner_child.main()` sets `VAULTSPEC_ENVIRONMENT=development` only for the child execution and restores the prior value in a `finally` block. The focused subprocess regression contrasts this path with an external undeclared process and preserves the production `misconfigured` verdict. The five-file canonical serial API subset passed 64/64, including the `/internal/events` missing-auth 401 negative; the testing suite passed 71/71. Ruff format/check and Ty passed. Review classification: the former HIGH CI-blocking bootstrap finding is resolved; no new critical/high/medium finding was found. The remaining timing record is retained as historical runner evidence, and P01.S17 remains open for IPC lifecycle cleanup.

### worker-ipc-close-deadline | medium/lifecycle | exhausted flush budget can skip IPC client close | open

Review of `src/vaultspec_a2a/worker/tests/test_ipc.py:483` against `src/vaultspec_a2a/worker/ipc.py:127-145` found that when the flush deadline is exhausted, the path can return `delivered=false` without calling `client.aclose`. P01.S17 owns a bounded cleanup correction: close is always attempted after flush exhaustion but itself cannot wait indefinitely; focused timeout/close tests must prove this while preserving bounded flush semantics. This lifecycle finding is separate from the canonical API bootstrap failure and is not evidence of a leaked descendant. No performance metric is inferred.
### worker-ipc-close-deadline | medium/lifecycle | bounded client close after exhausted flush | resolved

P01.S17 corrected WorkerBridge.close() so transport cleanup is always attempted after event delivery consumes the shared deadline. client.aclose() now runs under the named 0.1-second independent allowance (or the larger remaining shared budget), and timeout reports delivered=false without a second batch send. The focused real-ASGI regression proves one exhausted-flush report, retained buffered delivery state, closed client, and completion under 0.2 seconds. The worker IPC suite passed 25/25 in 11.65 seconds; the exact accepted-socket deadline case passed 1/1 in 0.55 seconds; Ruff check/format and Ty passed. Review classification: PASS; no critical, high, or new medium finding. No performance metric is inferred beyond these focused timings.

### desktop-readiness-liveness-crash | high/desktop-lifecycle | canonical CI proves authenticated health can hang after public liveness succeeds and the gateway exits | open

The clean integration canonical run at `c1380b0bc3f0e213c672a96953ca5635103b0c1e` failed `src/vaultspec_a2a/desktop_tests/test_readiness_model.py:138`: public `/health` returned 200, then authenticated `/health` timed out while the gateway `Popen` exited with code 1; the per-test `gateway.log` was empty. This is a real readiness/liveness crash and an observability gap, not an assertion to relax. P01.S18 owns preserving this proof, instrumenting gateway stderr, exit code, lifespan, and per-test log capture, finding the actual crash, and correcting it. No source fix or issue closure is claimed; P01.S08 and P02.S09 remain open.

### runner-descendant-lifecycle-classification | medium/lifecycle | descendant linger is misreported as a root teardown timeout | resolved

The same canonical run failed `src/vaultspec_a2a/testing/tests/test_runner.py:185`: the descendant-linger case expected exit 126 (`DESCENDANT_TIMEOUT_EXIT`) but returned 124 (`TEARDOWN_TIMEOUT_EXIT`), even though the runner reported `tree_reaped=true`. P01.S19 owns preserving process-tree reaping while distinguishing an exited root from a lingering descendant; exit 124 must remain reserved for a genuine root/process timeout. No source fix or issue closure is claimed; P01.S19 remains open.

### runner-post-receipt-lifecycle-classification | high/CI-blocking | a successful post-receipt root exit is misreported as teardown timeout | resolved

The same canonical run failed `src/vaultspec_a2a/testing/tests/test_runner.py:200`: the post-receipt root-exit case expected 0 but returned 124, after pytest had produced a session result and the runner reported `tree_reaped=true`. This false timeout classification blocks the canonical gate. P01.S19 owns the root-versus-descendant classification and must retain 124 only for a genuine root/process timeout; no source fix or issue closure is claimed.

P01.S19 resolution and review (2026-09-22): The completion receipt is now deferred until `pytest.main()` returns, after pytest unconfigure and lease cleanup, so the owner cannot classify a still-shutting-down root from an early session-finish receipt. The outer runner re-samples the root after receipt observation before applying the teardown deadline, retaining `TEARDOWN_TIMEOUT_EXIT` (124) for a genuine still-running root and `DESCENDANT_TIMEOUT_EXIT` (126) for an exited root with live descendants. The exact two canonical regressions passed 2/2 in 4.97s; complete runner coverage passed 6/6 in 9.69s; the full testing suite passed 71/71 in 64.92s; Ruff format/check and Ty passed. Review classification: both the medium descendant-classification and high post-receipt classification findings are resolved; no new critical, high, or medium finding was found. P01.S18 remains open for the desktop readiness/liveness crash.

### canonical-ci-performance-facts | low/measurement | full canonical timing and slowest-node facts recorded without causal attribution | recorded

The authoritative full-run log is `C:\Users\hello\AppData\Local\Temp\vaultspec-a2a-canonical-ci-2d82a0431b4a40c5a1f4d61228289d42.log`. Measured stage facts are total `2210.699s`, harness outer `56.933s` with `122 passed`, unit outer `2199.596s`, and pytest `2196.57s`. The unit pytest collected `4838` items, selected `4634` after `204 deselected`, and finished with `4621 passed`, `10 skipped`, and `3 failed`.

The six slowest unit nodes were: `140.43s` `src/vaultspec_a2a/desktop_tests/test_run_admission.py::test_concurrent_prepare_bounds_capacity_and_commit_is_reservation_bound`; `59.95s` `src/vaultspec_a2a/desktop_tests/test_readiness_model.py::test_desktop_readiness_liveness_minimal_and_readiness_authenticated`; `49.60s` `src/vaultspec_a2a/providers/tests/test_model_stack_warmup.py::test_repeated_cold_compiles_keep_serving_under_five_slot_cpu_load`; `37.65s` `src/vaultspec_a2a/desktop_tests/test_lazy_worker.py::test_idle_boot_starts_no_worker_and_concurrent_demand_starts_exactly_one`; `34.31s` `src/vaultspec_a2a/desktop_tests/test_owned_process_tree.py::test_desktop_worker_tree_contained_and_reaped_on_graceful_shutdown`; and `31.12s` `src/vaultspec_a2a/desktop_tests/test_worker_provenance.py::test_two_gateways_one_worker_authenticated_pairing`. These are descriptive measurements only: they do not establish that any slow node caused a failure or attribute total wall time to P01.S18/P01.S19; isolated reruns are required for causal analysis.
### desktop-readiness-liveness-crash | high/desktop-lifecycle | resolved

The original canonical evidence recorded public `/health` 200 followed by an authenticated health timeout, an exited gateway (`Popen` code 1), and an empty child log. The retained serial-prefix reproduction narrowed the live failure to public `/health` 200, unauthenticated `/v1/service` 401, authenticated `/health` 200, then authenticated `/v1/service` timing out while the gateway remained alive. The cold desktop worker owns an unbound loopback port; on Windows that connection can consume the whole five-second worker probe budget, racing the caller's five-second HTTP budget. S18 now preserves failure exit/lifespan/stderr evidence, uses a two-second service worker probe, and starts the database/journal, checkpoint, and worker observations concurrently under a shared three-second service-health deadline. Timeout results remain truthful degraded diagnostics; no authentication or readiness assertion was relaxed. The real locked-`AsyncSqliteSaver` TCP regression returned degraded checkpoint evidence under 4.5 seconds while retaining the production five-second client contract. Three repeated locked-checkpoint proofs passed at 3.61-3.62 seconds; the focused service/auth/database/readiness suite passed 49/49 in 15.81 seconds; the closest serial desktop prefix passed 28/28 in 103.13 seconds; Ruff, format, Ty, diff check, and independent review passed.

### service-worker-probe-transient-degradation | low/operational | queued

A legitimate worker that cannot answer its exact-200 health probe within the two-second service-state observation budget is reported as degraded for that one service-state response. This is not an authentication bypass: the attach gate remains required, and run-start/watchdog retain their existing shared probe policy. Keep this as a low observation; no existing plan Step explicitly authorizes a different worker-health service-level objective.

### service-state-whole-route-deadline | low/operational | queued

S18 bounds and joins the dependency-probe aggregate, but later synchronous service-state projection work (provider eligibility, storage/discovery projection, response serialization, and route signature) has no separately enforced whole-route deadline. The current evidence does not establish an end-to-end violation or justify a broad timeout redesign. Keep this low observation queued for integrated review; P02.S09 does not explicitly authorize an end-to-end deadline change.

### p01-s18-final-review | low/review | PASS

Independent review found the original high resolved and required only the two low observations above. The final structured concurrency path gives each task an owned connection/session boundary: the request session belongs only to its database probe, journal inspection opens its own engine connection, and nested and outer task groups cancel and join all observations. The 3.0-second aggregate does not serially accumulate the journal, checkpoint, and worker budgets. No critical, high, or medium finding remains in S18.

### nested-scheduling-runner-teardown | high/CI-blocking | canonical scheduling evidence reaches runner teardown without a truthful owned-process diagnosis | open

The exact canonical log `Y:\code\vaultspec-a2a-ci-logs\c45b3222-just-ci-20260922-011503.log` records the run reaching 87% in `src/vaultspec_a2a/testing/tests/test_scheduling_evidence.py` after `test_runner6` passed, then the outer runner reporting its own session result followed by the 10-second process-tree exit timeout and reaped exit 124. There is no assertion failure/error and no PID snapshot, so the evidence does not distinguish a nested pytest or xdist descendant from the runner root. P01.S20 owns capturing the exact owned process tree and stack on timeout, identifying the root-versus-descendant cause, and fixing truthful lifecycle/cleanup while preserving the real scheduling tests and the 10-second bound. Skipping the tests or adding global timeout padding is out of scope; no source fix or issue closure is claimed. P01.S08 and P02.S09 remain open.

### canonical-ci-scheduling-performance | low/measurement | scheduling-evidence run timing facts recorded without a misleading comparison | recorded

For the same full run, the measured total was `1607.82s`; the harness stage completed `122` tests in `62.47s`; the unit stage was at least `1481.3s` when it reached 87%; and no pytest `--durations` report was emitted. These are standalone measurements for the exact log above, not a causal attribution or a comparison with the earlier canonical run; the missing durations report leaves per-node attribution unproven until a clean completion or targeted rerun.

### nested-scheduling-runner-teardown | high | resolved

P01.S20 resolution: the completion endpoint and prior owner PID are removed from the runner-child environment before pytest starts. A pre-pytest hello pins the designated execution PID; Windows admits the virtual-environment launcher descendant only while it belongs to the exact owned Job Object, and POSIX requires the spawned root PID. Later completion must name that pinned PID. The scheduling subprocess boundary also removes inherited credentials. Timeout diagnostics record the retained root status and exact Job/process-group member snapshot without command lines or environment. The proven cause is nested completion-channel inheritance; stack capture is unnecessary for that established cause and the owning Step now names the exact seven changed source/test paths.

Final bounded verification: one runner-suite invocation passed 8/8 in 15.71s, including forged sender rejection, real nested xdist rebound rejection, legitimate hello/completion, exit-124 reaping, and exit-126 descendant classification. Ruff and Ty each passed once over all seven changed paths. Earlier same-source scheduling evidence passed 7/7 under the runner. No full CI rerun was started for this review. Self-review result: PASS; no critical, high, or medium implementation finding remains. The full canonical gate and its completed performance report remain pending integrated review.

### completion-identity-reuse-review | low | not applicable to retained runner lifecycle

Independent review proposed a HIGH numeric-PID reuse race. Actual lifecycle inspection does not support it: Windows Popen retains its process HANDLE throughout _await_pytest_exit; its _internal_poll and _wait inspect that handle without closing it, and assign_suspended_process seats that same handle in the Job before resuming the launcher. Job membership and launcher ancestry are checked for the initial hello, sent before pytest and before ordinary descendants receive control; nested environments lack its secret endpoint. On POSIX, the exact root remains unreusable while alive or unreaped; after poll observes/reaps its exit, _root_exit_status governs regardless of any receipt and never applies the root teardown branch. A later completion cannot change the pinned identity. No executable premature-timeout race or unrelated-process kill was demonstrated. The channel prevents accidental inherited nested receipts; it is not an isolation boundary against malicious code already executing inside the trusted pytest interpreter. Classification: review hypothesis, not applicable; no speculative process-identity subsystem added.
### dashboard-relay-live-proof | medium | live A2A relay recovery certification | resolved

Dashboard commit `73d0c1c58cce13c97fdc467b083ca466f0e731bb`, published on `origin/issue-137-live-relay-certification`, supplies the missing controlled live proof. Its real-engine/real-A2A S12 scenario verifies exact scripted content, monotonic relay sequence, and completed terminal truth. S13 starts a deterministic relay burst, observes an honest stale-cursor gap and live broadcast-lag handling, resumes from a known recent cursor for exactly eight contiguous replay frames, accepts cancellation, and reconciles authoritative terminal `cancelled` status. The two live Playwright scenarios passed on the connected gateway (2/2, approximately 22 seconds) before publication. This resolves the sole P01.S08 certification gap; the Dashboard issue can be actioned after the published change is accepted through its repository workflow.

### canonical-ci-final-gate | low/verification | complete integrated canonical gate | PASS

The one permitted final `just ci` run at `99bf928f74d06eb67e65f253ef0ba92a68384f8d` completed with exit 0 in `1430.530s`; durable log: `Y:\code\vaultspec-a2a-ci-logs\99bf928f-just-ci-20260922-021949.log`. It recorded 122 harness tests in 26.54s, 4,627 unit tests passed with 10 environment/platform skips and 204 service deselections in 1278.19s, six docs tests in 0.61s, build artifacts, and a warning-free Sphinx build. The ten slowest unit calls range from 15.43s to 39.24s, led by model-stack warmup (39.24s), worker provenance (25.59s), and owned-process-tree cleanup (23.07s). The earlier failed/timeout gates had different completed work and are not a valid performance baseline; this review records measurement only, not a speedup claim. The runner received and authenticated completion receipts in every owned test stage, including the repaired nested scheduling path.

### p02-s09-integrated-review | low/review | combined remediation is coherent | PASS

Review traced the lifecycle, Compose admission and execution boundary, cancellation and lease recovery, provider qualification, release preparation, read-only hook, and contained test-runner changes against the plan's accepted decisions and the final CI evidence. The S20 Windows launcher identity condition is adequately bounded: the retained Popen handle joins the suspended root to the Job before resume; the pre-pytest hello accepts only a current Job member on that launcher ancestry; completion must come from that pinned execution PID; and nested pytest receives no completion endpoint or owner identity. This provenance channel is not represented as a hostile-code isolation boundary. No critical, high, or unowned medium finding remains. Existing low queue entries remain owned: `prek-format-baseline`, `plan-ordering`, `dashboard-rust-tooling`, `service-worker-probe-transient-degradation`, and `service-state-whole-route-deadline`.
### dashboard-relay-live-proof-evidence | low/evidence | exact published cross-repository certification | recorded

The durable connected-run log `Y:\code\vaultspec-dashboard-worktrees\main\frontend\test-results\agent-final-20260922-024647.log` records S12/S13 passing 2/2 in 20.6s (21.606s outer), exit 0, Dashboard HEAD `73d0c1c58cce13c97fdc467b083ca466f0e731bb`, and A2A HEAD `99bf928f74d06eb67e65f253ef0ba92a68384f8d`. This replaces the approximate timing in the preceding resolution entry and is the authoritative P01.S08 run evidence.

### issue-18-original-scope | medium/triage | lifecycle remediation does not close the broader historical orchestration issue | queued

P01.S01 completed the accepted HTTP-readiness, lifecycle, and trace evidence slice. GitHub issue #18 also names containerization and BOLID investigation that this plan neither implemented nor disproved. Keep #18 open as its own explicit successor queue item; do not describe the lifecycle correction as full issue closure. No new source change is authorized by this review.

### issue-26-original-scope | medium/triage | release preparation does not implement the broader release-please and first-release request | queued

P01.S04 deliberately delivered an auditable A2A preparation path while preserving Dashboard ownership of release-set selection. GitHub issue #26's original release-please/autorelease and first-release scope remains unimplemented and is not satisfied by that bounded work. Keep #26 open as its explicit successor queue item; no release automation is authorized by this review.

### p02-s09-disposition-correction | low/review | open GitHub successors are explicitly owned, not silently closed | PASS

The integrated PASS means no critical or high implementation finding remains and every discovered item has a durable owner. It does not claim that #18 or #26 are closed: each remains open with the medium triage disposition above. The live relay certification is complete and published, while Dashboard #137 awaits normal repository acceptance before issue action. The five A2A issues with completed bounded corrections (#25, #57, #72, #73, and the lifecycle slice of #18) require the parent coordinator's explicit GitHub disposition; this review neither merges code nor closes issues.
### merge-release-tag-trigger-glob | high/release-automation | regex-style tag filter could not match normal release tags | resolved

The reconciled remote workflow used `v[0-9]+.[0-9]+.[0-9]+*` as a GitHub tag filter. GitHub evaluates this field as a glob rather than the strict regular expression used later by the workflow, so a normal tag such as `v0.2.0` would not start publication. The filter is now the intentionally broad `v*.*.*`; the existing build step remains the authority that rejects anything other than strict `vMAJOR.MINOR.PATCH` before artifact construction.

### merge-release-dispatch-operation | high/release-automation | release-please dispatch selected preparation instead of publication | resolved

The release-please workflow dispatched `release.yml` with only the tag, while the reconciled workflow defaults `operation` to `prepare`. A release created with the repository token therefore could dispatch metadata preparation with empty preparation inputs instead of proving and publishing the immutable tag. The dispatch now supplies `operation=publish` together with the tag, and the contract test requires that input.

### merge-release-contract-drift | medium/test-contract | local release guard rejected the remote tag trigger | resolved

The local contract test still required `workflow_dispatch` as the only release trigger and therefore failed against the remote release-please/tag automation. The test now requires both dispatch and the broad tag glob, verifies the reusable qualification ref works for either trigger, and retains the checksum, provenance, complete-cohort, and publish-last assertions.

### merge-integration-review | low/review | reconciled release and remediation histories are coherent | PASS

Review traced the combined release-please dispatch, tag/ref validation, reusable qualification gate, native build matrix, checksum validation, provenance attestation, exact cohort upload, attached-provenance verification, and final draft publication. It also checked the remote remediation source resolutions against their focused tests and validated the merged vault corpus. The two high and one medium merge findings above are resolved. No critical, high, or unowned medium finding remains from this reconciliation pass.

