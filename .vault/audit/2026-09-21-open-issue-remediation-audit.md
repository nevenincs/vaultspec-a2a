---
tags:
  - '#audit'
  - '#open-issue-remediation'
date: '2026-09-21'
modified: '2026-09-21'
body_schema: 'body-v2'
body_hash: 'sha256:e714fc1101f8102b30673fcc3e1ccb270121873c6e0a13595f0a1dd9a31cdff9'
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
