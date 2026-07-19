---
tags:
  - '#audit'
  - '#a2a-edge-conformance'
date: '2026-07-17'
modified: '2026-07-19'
related:
  - '[[2026-07-14-a2a-edge-conformance-plan]]'
  - '[[2026-07-14-a2a-edge-conformance-W05-P16-S37]]'
  - '[[2026-07-14-a2a-edge-conformance-W05-P16-S38]]'
  - '[[2026-07-14-a2a-edge-conformance-W05-P16-S40]]'
  - '[[2026-07-14-a2a-edge-conformance-W05-P16-S41]]'
  - '[[2026-07-14-a2a-edge-conformance-W05-P17-S42]]'
  - '[[2026-07-14-a2a-edge-conformance-W05-P17-S43]]'
---

# `a2a-edge-conformance` audit: `w05-p16 review`

## Scope

Code review of the W05.P16 relay-activation execution commits, performed by the
`vaultspec-code-reviewer` persona against the plan phase and the governing
edge-conformance and orchestration-edge decision records.

- Commit ee2cdc5 (S37): provenance-aware worker adoption and eviction —
  `src/vaultspec_a2a/worker/app.py` health provenance fields,
  `src/vaultspec_a2a/control/worker_management.py` provenance-gated spawn with
  graceful eviction, new real-loopback tests in
  `src/vaultspec_a2a/control/tests/test_worker_provenance.py`.
- Commit e47c882 (S38, code half): resident staleness detection —
  `route_signature` in `src/vaultspec_a2a/api/routes/gateway.py`, additive
  `routes` field on the service-state schema, doctor CLI route diff in
  `src/vaultspec_a2a/cli/main.py`, live CLI test in
  `src/vaultspec_a2a/cli/tests/test_cli_live.py`.

**Status: REVISION REQUIRED** — no critical findings; sign-off blocked on the
high-severity auth item (or its explicit deferral) plus two medium corrections.

## Findings

### admin-shutdown-unauthenticated | high | Unauthenticated worker shutdown endpoint is now a load-bearing control-plane primitive

`POST /admin/shutdown` in `src/vaultspec_a2a/worker/app.py` carries no
dependency guard, unlike the dispatch endpoint which verifies the internal
bearer. S37 wires this endpoint into the eviction path in
`src/vaultspec_a2a/control/worker_management.py`, making it load-bearing: any
same-machine process with loopback access can hard-kill the worker (local
denial of service, eviction-path abuse). Pre-existing endpoint, unchanged auth
posture, but S37 elevates its blast radius by making self-destruct part of the
control flow.

### sigterm-hard-kill-on-windows | medium | The graceful shutdown wording is a hard kill on the Windows target

The shutdown endpoint calls `os.kill` with SIGTERM, which on Windows maps to
`TerminateProcess` — immediate, no run draining — while the endpoint and
evictor docstrings both call it "graceful." Mitigating: eviction only ever
targets a foreign-gateway worker, so the calling gateway's own in-flight runs
are never the kill target. Any future same-gateway use of this path would
abort in-flight runs.

### legacy-worker-adoption-compat-hole | medium | Missing-provenance workers are adopted, reproducing the S37 defect for pre-fix workers

A worker whose health response predates the provenance field is treated as a
gateway match and adopted, even if it is genuinely a stale orphan wired to a
dead gateway. Deliberate, documented compat tradeoff; self-closes once every
resident worker restarts on this build, but it is not self-healing. The fix
only fully lands after legacy workers are reaped.

### doctor-exit-code-silent | medium | A detected stale resident does not affect the doctor exit code

The doctor command reports `stale_resident` and `missing_routes` in the JSON
body but exits non-zero only on transport errors; the live test asserts return
code zero alongside a positive staleness detection. Automation keying on exit
status will not catch a stale resident — only JSON-parsing consumers will.

### failed-eviction-doomed-spawn | low | A failed eviction still spawns a worker doomed to lose the port bind

When eviction fails, spawn proceeds and the child predictably fails the bind;
the existing 30-second poll and restart-detail path surface it. A known-doomed
spawn could early-return a degraded signal instead.

### dual-gateway-port-race | low | Two distinct gateways sharing one worker port can race evict-and-spawn

Time-of-check to time-of-use between the port-free wait and process start.
This is a misconfiguration (each gateway owns its worker port); same-gateway
concurrent boots both adopt without eviction. Note only.

### missing-routes-one-directional | low | Staleness diff reports expected-minus-live only

A resident newer than the doctor's installed source reads clean. Directionally
correct for a staleness check.

### verified-positives | low | Verified positives recorded for completeness

The Windows port probe uses a connect-probe (the reliable direction on this
platform, avoiding the known-unreliable bind probe). Doctor false-positive
risk is low: route registration is unconditional and deterministic, so the
diff is a pure function of installed source. The service-state schema change
is additive and backward-compatible for the dashboard contract. Test integrity
holds the repo mandate: no mocks, no tautologies; provenance tests exercise
real subprocess workers, and the CLI test mutates the real router around a
real server with correct restore-on-failure ordering. Plan intent alignment:
S37 matches its row; e47c882 correctly scopes itself as the S38 code half with
the operational promotion tracked separately.

### admin-shutdown-unauthenticated-resolved | resolved | Shutdown endpoint now bearer-gated and evictor presents the token

Verified closed in 9556117. The worker shutdown endpoint now carries the same
internal-bearer dependency as dispatch (shared verifier, so no new asymmetry),
rejecting unauthenticated loopback callers before the kill handler runs; the
evictor presents the configured internal token. Tests are real: 401 for
missing and invalid tokens (before-handler, so the kill never fires), the
evictor's token accepted by a token-requiring loopback worker, and a tokenless
evictor rejected leaving the worker alive. Environment nuance recorded: with
no internal token configured, the verifier intentionally passes in
DEVELOPMENT — the dev bypass extending to the kill endpoint is
acceptable-inherited (identical posture to dispatch), hard-fail outside
DEVELOPMENT.

### sigterm-hard-kill-on-windows-resolved | resolved | Docstrings corrected to the Windows hard-kill reality

Verified closed in 9556117. Both the shutdown endpoint and evictor docstrings
now state the Windows TerminateProcess reality (immediate, no run draining)
and that eviction only ever targets a foreign-gateway orphan, so the abrupt
stop cannot drop this gateway's live work.

### doctor-exit-code-silent-resolved | resolved | Stale resident now carries a distinct exit code

Verified closed in 7a6975c. The doctor exits 3 for a reachable-but-stale
resident, distinct from transport-error 1 and usage-error 2, evaluated only on
a successful response; the live test asserts return code 3 alongside the
positive detection. Automation can key on exit status without parsing JSON.

### legacy-worker-adoption-compat-hole-operationally-closed | resolved | Legacy no-provenance worker reaped during promotion

The operational half is done: the final restart-promotion reaped the
previously adopted legacy worker, so a gateway-owned worker emitting health
provenance now holds the port. The compat fallback remains in code by design,
but no legacy no-provenance resident remains at the discovery point.

### s40-recovery-epoch-increment | resolved | Paused-resumable repair now advances the epoch, matching the resumable sibling branch

Reviewed fresh (7e308cf). The paused-resumable outcome now increments the
recovery epoch, consistent with every other applied branch: resumable
branches bump epoch only, checkpoint-lost branches bump generation and epoch.
Leaving generation unbumped is correct — generation identifies the checkpoint
and worker incarnation so the pending permission resumes from the existing
checkpoint, while the epoch is the reconciliation-attempt counter seeding the
startup-repair idempotency key. Before the fix this was the only applied
outcome incrementing neither, so the next boot re-derived the same key and
crashed the unique insert.

### s40-get-or-create-toctou | low | The conflict-tolerant helper is lookup-then-insert, not atomic, under concurrent boots

`get_or_create_control_action` fully solves the targeted sequential-reboot
replay, but two genuinely concurrent boots against the same database could
still race the unique violation between lookup and insert. Not reachable in
practice: startup reconciliation is serial within a boot and concurrent
same-database residents are prevented by the discovery-point liveness guard.
Defense-in-depth recommendation, non-blocking: an on-conflict-do-nothing
insert or savepoint so the helper's name matches its guarantee.

### s40-test-integrity | low | S40 tests are real database plus real checkpointer and reproduce the exact crash state

Real SQLite engine and real checkpointer, no mocks. The boot-reboot test
drives two real reconciliation passes asserting the epoch sequence and
per-boot idempotency keys; the self-heal test seeds the precise pre-fix stuck
state and proves the boot replays the duplicate key as a no-op and advances
the stuck epoch instead of crashing. Expected values derive from the
specification, not captured output.

### adopted-worker-status-not-reconciled | medium | Watchdog spawned-gate leaves an adopted worker's status stale, flipping plain health ready to false

Disposition of the promotion observation: a REAL pre-existing defect, not a
telemetry gap. The plain health ready formula disqualifies on a down or
restarting worker status, so a healthy adopted worker reads not-ready and can
mislead external probes. Root cause: the watchdog tick early-returns when this
gateway spawned no worker, and an adopted worker is never spawned by this
gateway, so the non-owned reconciliation branch is never reached and the
status never lifts off its initial value. Not introduced by the reviewed
commits — the adoption early-return and the spawned-gate both predate S37,
which changed only the adoption decision, not worker-state reconciliation.
Does not block PASS: out of the reviewed diff scope, pre-existing, and the
adopted path is currently unexercised at the promoted resident (the final
promotion reaped and respawned, so the worker is gateway-owned). Tracked as a
follow-up plan step.

### admin-shutdown-auth-closure-scope | resolved | Code-level closure is real and fail-closed outside development

Clarifies admin-shutdown-unauthenticated-resolved. The dependency wiring in
9556117 is a genuine closure, not env-cosmetic: whenever the internal token is
set the shutdown endpoint enforces an exact bearer match (401 otherwise), and
when the token is unset it hard-fails with 500 (misconfigured) in every
environment except DEVELOPMENT — the kill handler is unreachable in staging
or production without a configured token. Auth is closed and fail-safe in
every deployed non-dev posture. The only residual exposure is the DEVELOPMENT
tokenless bypass, dispositioned separately below.

### admin-shutdown-dev-bypass-inherited | low | The shutdown endpoint inherits the project-wide DEVELOPMENT auth bypass

In DEVELOPMENT with the internal token unset, the verifier returns OK for a
tokenless caller by design, so the newly-guarded shutdown endpoint accepts
tokenless kills on a dev box — the same bypass the dispatch endpoint already
rides. Assessed acceptable-inherited, not a reopening of the high finding:
it is the sanctioned project-wide IPC posture applied uniformly with no
shutdown-specific asymmetry, it fails closed outside DEVELOPMENT, and the
dev-box threat model already grants any local process far more than a worker
kill (the worker is trivially re-spawned on the next dispatch, which is the
eviction path's premise). Optional non-blocking defense-in-depth: the
shutdown endpoint could opt out of the DEVELOPMENT bypass and require a token
even in dev, since a kill is more destructive than a dispatch. Recorded so a
future reader sees the sharper edge was considered and consciously accepted.

## Re-review status (2026-07-17)

**Status: PASS.** The high-severity finding and both medium corrections are
verified closed in 9556117 and 7a6975c with real auth-rejection and exit-code
tests; the legacy-adoption compat hole is operationally closed by the
promotion reap. S40 is reviewed fresh and clean. Two non-blocking follow-ups
remain: the get-or-create conflict-tolerance hardening (low) and the
adopted-worker status reconciliation (medium, pre-existing, currently
unexercised at the promoted resident). No critical, no open high — the
W05.P16 commit set (ee2cdc5, 9556117, 7e308cf, e47c882, 7a6975c) is clear.

### adopted-worker-status-not-reconciled-resolved | resolved | Watchdog now reconciles an adopted worker's status from the live probe

Verified closed in 823fa8d. The watchdog tick adds, after detection and before
the owned-worker state machine, a pure probe-driven reconcile for workers with
no owned process handle (adopted/externally-managed), bypassing the sticky-down
guard that froze a healthy adopted worker at down. No regression for owned
workers: a crashed owned worker retains its process handle, so the new branch
is skipped and the restart/breaker path still runs; the early return also
means an adopted worker is never restarted or breaker-forced. The companion
readiness fix scopes the heartbeat-freshness gate to owned workers while the
down/restarting disqualifier still applies to every worker, so owned-worker
readiness truth is unchanged. Tests are real-seam and fail pre-fix: a real
watchdog tick against a real loopback health server recovers an adoption-shaped
latched-down worker to up with zero restarts and a closed breaker, and the real
ASGI gateway reports ready true for an adopted worker without heartbeats.
Residual, accepted and informational: plain health readiness for an adopted
worker now rests on HTTP reachability alone — an adopted worker answering 200
while internally broken would read ready there; heartbeat freshness genuinely
cannot apply to a worker that pushes no heartbeats this gateway accepts, and
the richer service-verb worker-ready signal remains authoritative for
dispatch readiness.

### s40-get-or-create-toctou-resolved | resolved | Get-or-create is now atomic via a nested savepoint

Verified closed in 823fa8d. The insert runs inside a nested savepoint; on
integrity error only the savepoint rolls back (outer transaction stays
usable) and the committed row is re-read and returned as a replay; a re-read
returning nothing re-raises, so a non-conflict integrity error is not
swallowed. The lookup-then-insert window is closed and the helper's name
matches its guarantee; savepoint support holds on both backends. Test note:
sequential replay across two real committed sessions is proven (one row,
created true then false); the savepoint-rollback branch under genuine
write-write concurrency is not directly exercised by a deterministic test —
correct by construction, low residual, non-blocking.

## S41 status (2026-07-17 review, recorded 2026-07-19)

**Status: PASS.** S41 (823fa8d) resolves both non-blocking follow-ups from the
W05.P16 re-review — the adopted-worker status reconciliation (was medium) and
the get-or-create atomicity (was low) — each with a real-seam,
non-tautological test that fails pre-fix. No new findings. W05.P16's code
trail is clean end to end.

## W05.P17 review (S42 merge projection + S43 real-project-root probe)

Reviewed against the accepted 2026-07-19 real-project-root mcp projection ADR
(its Implementation section is the contract) and plan phase W05.P17. S42 =
27e9726 (`src/vaultspec_a2a/providers/_acp_project_mcp.py` rework, caller
comment and error docstring, tests). S43 = 2ac722f (probe step record and S18
carry-forward).

### s42-merge-projection-conforms | resolved | Entry-merge projection matches the ADR contract point for point

`project_declared_mcp` reads and parses an existing file, recovers the
pre-merge base, merges declared entries alongside the project's own, preserves
non-server top-level keys, and writes the dict marker (added list, base-absent
flag, base fingerprint). Refusal is correctly narrowed to exactly two cases —
a declared name colliding with a non-projected entry (computed against the
RECOVERED base, so re-projecting our own prior entries is not a false
collision) and an unparseable file — both raised before any write. Cleanup
inverts exactly the marker's added list, deletes the file only when the base
was absent and nothing else remains, and never raises. Crash-residue
re-projection strips the stale marker and carries the ORIGINAL base state
forward, so a later cleanup still restores the true original. Legacy markers
keep whole-file removal for the transition release. Collision matching is
exact-string and case-sensitive, which is correct (the CLI keys servers by
exact name). The caller inverts on every exit path: refusal cleans the
isolated home and re-raises fail-loud, and success routes through the single
finally that cleans up on spawn-raise, stdio failure, or normal close —
satisfying the ADR crash-safety requirement.

### s42-test-integrity | resolved | Real-filesystem tests cover every ADR-enumerated case, no mocks

Fourteen tests map one-to-one to the ADR's required matrix: absent-file
create with entry marker and placeholder env, cleanup restoring absence,
merge preserving both the project's server and a foreign top-level key with
exact restoration after cleanup, loud refusal on name collision with the
foreign file untouched, loud refusal on unparseable with bytes untouched,
crash-residue re-projection over own and foreign residue (idempotent, exact
restoration), mid-run user-added entry surviving cleanup, legacy-marker
whole-file removal, cleanup never touching a marker-less foreign file, and
the deny-set enumeration. Assertions are non-tautological and each fails
against the pre-S42 behaviour.

### s42-isolation-test-repurpose-sound | resolved | The fail-loud guarantee through the real caller is retained, not weakened

The foreign-workspace fail-loud test was repurposed from any-foreign-refuses
to name-colliding-foreign-refuses, correctly tracking the ADR's narrowed
refusal. The load-bearing properties are retained: the stream still raises
before spawn with the foreign file intact, and the armed-run token/isolation
fail-loud test is untouched. A correct narrowing, not a hole.

### s42-cleanup-keys-on-marker-names | low | A user re-adding a reserved projected name mid-run is removed at cleanup

Cleanup keys purely on the marker's added list, so a user entry created
mid-run under one of our reserved projected names would be popped as ours.
Defensible — the projected namespace is reserved — but it is the one mid-run
edit shape the surviving-entry test does not cover. Noted for completeness.

### s42-fingerprint-diagnostic-only | low | The base fingerprint is recorded but never enforced at cleanup

A hand-desynced marker whose added list names a foreign entry will have that
entry removed. This is the exact desync consequence the ADR acknowledges and
accepts; the fingerprint is a diagnostic. Optional future hardening: compare
at cleanup and skip inversion on mismatch.

### s43-scratch-root-discharges-projection-evidence | resolved | The crash-isolated scratch root faithfully proves the merge

Ruling on the workspace judgment call: the projection keys solely off the
file at the workspace root, never git-tracking, so the scratch root seeded
with the normative foreign shape (project server, foreign top-level key, no
marker) exercises the identical code path that RED-failed on 2026-07-18. The
one property a literal repo root would add — real ancestor-tree interaction —
is upstream of this decision, unchanged by S42, and separately unit-tested.
The scratch choice is ADR-aligned (crash-recoverability; a destructive-capable
probe against another live session's tracked file risks exactly the residue
the decision exists to prevent). Ruled acceptable and sufficient for the
projection-half closure; a literal repo-root run is optional at final closure.

### s43-split-verdict-honest | resolved | The split verdict is honest and its non-defect attributions are sound

The projection half is proven with direct before/during/after evidence, not
inferred. The changeset-absent attribution to the provider usage window is
sound: the subprocess closed on the step-timeout with zero assistant messages
and no tool call attempted — the no-model-turn signature — whereas a genuine
exposure defect would show the model running and failing to see the merged
tools. The zero-writes criterion is honestly declared unmeasurable (the
engine-vault delta was entirely a concurrent session's unrelated paths)
rather than falsely passed. S43 is correctly left open. No defect is masked.

### s43-closure-owed | low | Final S43 closure still owes a real changeset and a clean zero-writes measurement

The honest residual, not a defect: the closure re-drive on an available
provider lane must produce an engine-side run-scoped changeset from a
completing solo-coder turn and measure zero-writes on an uncontaminated
engine vault (or with run-scoped filtering). The projection half needs no
further proof.

## W05.P17 status (2026-07-19)

**Status: PASS.** S42 implements the accepted marked-entry-merge ADR point
for point with fourteen non-tautological real-filesystem tests and
all-exit-path cleanup at the caller; the isolation-test repurposing narrows
the trigger without weakening the fail-loud guarantee. S43 is an honest split
verdict: the projection merge is genuinely live-proven on the
previously-failing real-project-root case, and end-to-end closure is
correctly left open on a non-usage-gated provider lane. Two low code notes
and one low closure-owed note, none blocking. W05.P17's code trail is clean.

## Recommendations

- Authenticate the worker shutdown endpoint with the internal bearer and have
  the evictor present the token (finding admin-shutdown-unauthenticated), or
  record an explicit team deferral; sign-off is withheld until one of the two
  happens. Routed to the S37 executor as a required revision.
- Correct the graceful-shutdown docstrings to state the Windows hard-kill
  reality (finding sigterm-hard-kill-on-windows). Routed to the S37 executor.
- Decide the doctor stale-resident exit-code contract: distinct non-zero exit
  for automation, or an explicitly documented JSON-only contract (finding
  doctor-exit-code-silent). Routed to the S38 executor.
- Operational note, no code change: reap legacy no-provenance workers when
  promoting the resident so the adoption compat hole closes (finding
  legacy-worker-adoption-compat-hole).
