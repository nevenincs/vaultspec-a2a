---
tags:
  - '#audit'
  - '#desktop-product-profile'
date: '2026-07-20'
modified: '2026-07-20'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# `desktop-product-profile` audit: `S101 retained inputs and lost-ack hardening`

## Scope

This pass reviewed the complete S101 retained-input change and the subsequent
gateway lost-ack and release hardening against the governing desktop ADR, plan,
S100 lineage, W04.P12 execution record, production implementation, tests,
dependency declarations, and Sphinx API surface. The review concentrated on
authority lifetime, supported-target resource behavior, admission linearizability,
credential handling, upgrade compatibility, and real-process evidence.

Verdict: **REVISE / BLOCKED**. The retained byte authority itself is coherent, and
the exercised happy-path and completed-race behavior passes, but the advertised
resource envelope is not target-proven and the staged commit still has two
lost-ack or crash windows that can strand a run start.

## Findings

### retained-snapshot-target-budget | high | The accepted snapshot envelope is not supported-target compatible

`open_verified_capsule_inputs` accepts as many as 512 unique retained snapshots
and 8 GiB of deduplicated bytes, while each unique snapshot keeps one
`TemporaryFile` descriptor open for the complete assembly scope. S100 introduced
sequential package and license sessions specifically to avoid retaining thousands
of handles, and the descriptor models still admit as many as 2,048 packages plus
external licenses. The new unit evidence exercises pool limits of only one and two
snapshots, and the full session fixture is a small Windows-targeted closure; it does
not prove the near-boundary contract on either supported macOS target or the other
target-native environments. A nominally admitted input can therefore exhaust the
platform or process descriptor allowance before reaching the application bound.
The existing S101 PASS and completion record overstate this unproved compatibility
contract.

### commit-consumed-before-durability | high | Commit can destroy the only reservation before a durable run exists

`AdmissionBroker.commit` deletes the active reservation and mints a lease before
`_create_run_core` performs request-specific metadata, preset, eligibility, profile,
drain-admission, database, and dispatch work. A process exit or exception in that
interval leaves neither an active reservation nor a durable run. After restart,
the durable replay branch has nothing to recover and the empty in-memory broker
returns a conflict. A release concurrent with the post-consume interval can also
report `released=False` even though no run ever becomes durable. The current race
test observes only completed HTTP outcomes and injects no post-consume,
pre-persistence failure, so the implementation does not establish the claimed
linearizable transition.

### optional-run-id-loses-ack | high | The schema permits commits that cannot replay a lost acknowledgement

`RunStartRequest` requires a reservation for commit but leaves `run_id` optional.
On a successful commit without a caller-supplied run identifier, the gateway mints
the run id only after consuming the reservation. If that response is lost, the
caller cannot address the durable row and an identical retry encounters the
consumed reservation. Existing admission tests still exercise this valid schema
shape, while the lost-ack service proof covers only the stronger engine request
that supplies a stable id. Lost-ack recovery is therefore not a property of the
published commit contract.

### legacy-lease-status-regression | medium | Status drops lease identities written by the previous gateway version

Before this hardening, committed runs persisted `run_lease.lease_id` without a
reservation id or commit digest. `_persisted_lease_id` now delegates to the strict
new replay-binding parser and returns no lease unless all three fields exist.
Terminal settlement still accepts the legacy shape, but `run-status` silently
omits its lease after upgrade. That breaks the additive recovery surface for a
still-active run created by the immediately preceding version.

### restart-recovery-evidence-gap | medium | The required restart recovery path is not exercised

The real service proof starts the dashboard engine, gateway, and worker and
demonstrates one same-process lost acknowledgement, one durable run, one engine
lease, one worker dispatch, exact replay, and altered-replay refusal. It never
restarts the gateway or dashboard before recovery. The focused status assertion
also runs in the creating process. Consequently the plan requirement that restart
leave no unreconciled lease, and the new durable replay parser's behavior after a
real process boundary, remain unverified.

### cross-suite-helper-and-credential-diagnostics | medium | The service proof depends on private test code and retains raw token bodies

The cross-repository service test imports `_ATTACH` and `_armed_gateway` from a
desktop test module instead of owning a production-facing harness. This violates
the repository rule that tests import directly from the codebase under test and
makes the certification test dependent on another suite's private implementation.
Its relay also stores complete commit bodies containing actor and engine bearer
tokens, and equality assertion diagnostics can render those bodies on failure.
Credential-bearing payloads must not become test diagnostics even though the
production persistence stores only a digest.

### readiness-and-module-doc-drift | medium | Documentation contradicts refusal behavior and does not cross-link the desktop authority graph

`AdmissionReadiness` says a deferred prepare is informational and does not refuse
a reservation, while `AdmissionBroker.prepare` now rejects every verdict other
than ready. The API registry declares the relevant desktop modules, but the
`artifacts`, `package_archives`, `closure_inventory`, `installed_inventory`,
`lock_reconciliation`, and `_archive_authority` module docstrings do not use
Sphinx `:mod:` links to explain their authority and evidence relationships. Module
registration alone does not satisfy the requested cross-reference health of the
major module docstrings.

### bound-emitter-signature-doc-drift | low | The Sphinx declaration omits a supported keyword

The API reference declares `emit_component_manifest_from_bound_inputs` without
its optional `digest_algorithm` keyword, although the production signature
accepts `digest_algorithm=DigestAlgorithm.SHA256`. The rendered reference is
therefore incomplete for a public bound-emission entry point.

## Recommendations

- For `retained-snapshot-target-budget`, reopen S101 in the audit queue. Either
  restore a sequential or bounded-window authority design, or select a lower
  supported-target descriptor budget and prove its full boundary with real
  target-native runs before restoring PASS.
- For `commit-consumed-before-durability`, make reservation-to-run transition a
  recoverable state machine whose accepted commit is durable before the active
  reservation disappears. Add a real fault boundary after acceptance and before
  run persistence, plus release races on both sides of that boundary.
- For `optional-run-id-loses-ack`, require a stable client run id for commit or
  persist a reservation-to-server-run-id replay record before acknowledging
  acceptance. Certify the exact public schema shape under response loss.
- For `legacy-lease-status-regression`, make the status reader backward compatible
  with the prior lease-only metadata and add an upgrade fixture containing that
  exact persisted shape.
- For `restart-recovery-evidence-gap`, extend the real-process certification with
  gateway and dashboard restart between accepted commit and repair, then prove
  one run, one lease, one dispatch, and status recovery.
- For `cross-suite-helper-and-credential-diagnostics`, give the service suite an
  independent production-facing harness and retain only redacted hashes or
  structural summaries of credential-bearing requests.
- For `readiness-and-module-doc-drift`, align `AdmissionReadiness` with the actual
  fail-closed prepare contract and add Sphinx `:mod:` relationships across the
  retained-input, inventory, reconciliation, archive, and manifest authorities.
- For `bound-emitter-signature-doc-drift`, document the bound emitter's
  `digest_algorithm` keyword and default exactly as implemented.

Verification observed in this pass: 57 focused capsule and manifest tests, four
real armed-gateway admission tests, the cross-repository dashboard/gateway/worker
lost-ack service test, targeted Ruff and Ty, and strict Sphinx checks pass. Those
passing results do not cover the high-severity failure boundaries above.

## Staged-admission remediation and re-review — 2026-07-20

This section updates only the staged-admission, lost-ack, restart, and proof
findings. The independent `retained-snapshot-target-budget` high remains open in
the S101 product-profile queue and therefore keeps the aggregate S101 verdict at
revise; it is not relabeled as A2A work.

| Finding | Severity / type | Remediation and evidence | Disposition |
|---|---|---|---|
| Commit consumed before durability | High / durability | `commit` now moves the in-memory reservation to `committing` without deleting it. The route calls `complete_commit` only after the durable run exists and, after rolling back the failed request transaction, classifies an exception against the exact durable binding. A real duplicate-nickname conflict occurs after broker authorization but before run durability, restores the unexpired reservation, and then releases it with the prepared binding. | Resolved |
| Optional run id loses acknowledgement | High / replay contract | Commit and release require a bounded stable `run_id`. The per-run single-flight stripe and persisted reservation plus commit digest make exact replay deterministic after response loss and restart. | Resolved |
| Legacy lease status regression | Medium / upgrade compatibility | Status reads the current exact binding when present and falls back to the preceding lease-only metadata shape. Exact local reserved-row repair requires the new reservation id, while legacy runs remain viewable. | Resolved |
| Restart recovery evidence gap | Medium / verification integrity | A real armed gateway commits a run, terminates its process tree, starts a new production gateway over the same stores, reads the same lease, and accepts the exact commit replay without spawning a worker or redispatching. The full real gateway suite passes 6/6. | Resolved |
| Cross-suite helper and credential diagnostics | Medium / test security | The service proof owns a production-facing helper under `service_tests`, retains only SHA-256 request digests for equality, keeps the one raw actor token in memory solely for a real production mutation, and never includes the raw commit body in assertion diagnostics. | Resolved |
| Readiness documentation drift | Medium / conformance | `AdmissionReadiness` and `PrepareOutcome` now describe the fail-closed readiness gate and the prepare-minted non-secret lease. | Resolved for staged admission |
| Fresh checkpoint restart drift | High / restart compatibility | First ingest materializes every SDD channel. The compatibility reader recognizes LangGraph's real `__start__`-only input-staging row as pre-TeamState rather than missing migrated state. Real serialized migration tests pass 3/3 and the real restart proof passes. | Resolved |
| Proof log and process bounds | Medium / memory and lifecycle | Worker logs are drained in 64 KiB chunks to EOF before the quiet window, unterminated lines are capped at 1 MiB, diagnostics retain 64 KiB, and POSIX teardown probes the complete process group after root exit before TERM/KILL completion. | Resolved |
| V1 body middleware constructed a typing alias | High / availability | The first uncommitted middleware revision called Starlette's `Message` typing alias as a constructor, making authenticated v1 writes fail with 500. It now constructs a typed dictionary. Real ASGI tests prove declared and streamed oversize rejection, and the live production gateway proves 413 before JSON parsing. | Resolved before commit |
| Tooling-only TOML writer failed dependency classification | Low / dependency hygiene | `tomlkit` was explicitly declared in the tooling group for real descriptor tests but omitted from deptry's approved development imports. The DEP004 configuration now names it and repository dependency validation passes. | Resolved before commit |
| Windows tree kill lost already-dead idempotency | Medium / lifecycle compatibility | A late return-code hardening pass treated `taskkill`'s nonzero response for an already-dead PID as failure, contradicting the public idempotent contract. The implementation now checks liveness before launch and treats a nonzero result as success only when the PID is authoritatively gone. | Resolved before commit |
| Strict role grammar changed the empty-key diagnostic | Low / wire compatibility | The bounded role grammar replaced the established whitespace-only role error with a generic pattern error. Empty and whitespace-only keys now retain the prior diagnostic before the stricter grammar validates every other key. | Resolved before commit |

Staged-admission certification is green: production cross-repository lost-ack
1/1, real armed-gateway admission and restart 6/6, dashboard route 19/19, lease
repository 4/4, terminal settlement 6/6, SDD projection 3/3, serialized migration
3/3, mounted frontend 2/2, TypeScript, Ruff, production Rust check, and a freshly
built dashboard CLI. The staged-admission sub-verdict is pass with no known
critical or high finding; the aggregate S101 audit remains revise solely for the
separate retained-snapshot supported-target budget finding above.

## Final adversarial resource and conformance closure — 2026-07-20

The final three-lane review found and resolved the remaining bounded-resource
edges in the staged-admission scope. A durable run followed by a dispatch
exception now completes its exact `ACTIVE` or `COMMITTING` reservation rather
than restoring capacity authority. A proven pre-durability absence aborts; an
unreadable or conflicting durable outcome stays `COMMITTING`, and both active and
uncertain reservations expire under the same TTL so uncertainty cannot exhaust
capacity until process restart. Release is bound in constant time to the exact
prepared request digest.

Authenticated `/v1` writes are capped at 1 MiB before JSON parsing. Run-start
and actor-token models forbid unknown fields; role keys use the production
63-character agent-id grammar; actor tokens and the optional engine bearer are
capped at 512 UTF-8 bytes. The production live-body test receives 413, actor-wire
coverage passes 10/10, and the direct production-state expiry regression plus
the real gateway expiry scenario pass 2/2 without fakes or patched code.

The retained proof now counts matching dispatches in O(1), checks its hard
deadline while draining every 64 KiB chunk, and bounds process-tree termination.
The final real armed-gateway suite passes 7/7 and the freshly rebuilt production
dashboard/gateway/worker lost-ack scenario passes 1/1 in 15.90 seconds. The
contract lane's final verdict is pass with no remaining critical, high, or medium
finding in this scope. The aggregate S101 verdict remains revise only for the
independent retained-snapshot supported-target budget finding above.
