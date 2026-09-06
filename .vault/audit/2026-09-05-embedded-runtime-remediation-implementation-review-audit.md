---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-05'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:d34d2d1b58f629bdd708099d28517a3119d07c2ff4c1a1a0e7ab244647da3c7a'
related:
  - '[[2026-09-05-embedded-runtime-remediation-plan]]'
  - '[[2026-09-05-embedded-runtime-remediation-qualification-inputs-reference]]'
  - '[[2026-09-05-embedded-runtime-robustness-audit]]'
  - '[[2026-09-05-embedded-runtime-remediation-no-legacy-curation-audit]]'
---
# `embedded-runtime-remediation` audit: `rolling implementation review queue`

## Scope

This queue records findings surfaced while executing the approved embedded-runtime-remediation plan. Each entry retains severity, type, status, evidence, and owning follow-up. Historical ER01-ER28 evidence remains in the embedded-runtime-robustness audit.

## Findings

### qualification-pair-lock-drift | high | Dashboard does not select the captured A2A baseline

Type: contract and evidence gap. Status: open. At S01, the clean Dashboard checkout is `330b2efe294c8ab134fff2142f9fae98afd14fec`, but its component lock selects A2A `d59b41b6c1ac8b6e498326ea74ab32898ac9c08b` with release identity `0.1.0`. The clean A2A execution baseline is `0b94bf8636d7145ae9420adeb1af635ef81f9dd7`; its freshly built executable reports `0.3.0` and hashes to `B5F1DA8EDD6A6DC99C3FBD81645EFBA4BDF6646544B4140F4C51AE81E2EDF08F`. This is an exact identified incompatibility in the qualification pair, consistent with historical ER23/ER24. It blocks A27 and dependent Dashboard measurements, while independent local remediation continues. Ownership: `W01.P01.S02` records the coordinated consumer boundary, `W04.P10.S47-S50` conforms it, and `W05.P13.S64-S65` supplies closing proof.

### durable-message-capacity-absent | high | A10 has no declared queue capacity Q

Type: concurrency and durability. Status: open. Current source exposes bounded progress, ACP, stream-registry, and IPC buffers, but no atomic per-run or service capacity for durable follow-up messages. A Q+1 test cannot be defined without inventing a limit after observing results. This retains historical ER03 rather than weakening A10. Ownership: `W02.P04.S16-S18`; closing measurement: `W05.P11.S52`.

### frozen-binary-collects-test-modules | medium | The freeze closure analyzes and archives test packages

Type: packaging and operational risk. Status: open. The S01 freeze log analyzed the repository's acceptance, desktop, service, and unit-test packages because the PyInstaller specification calls `collect_all("vaultspec_a2a")`. The produced `PYZ-00.toc` contained 463 entries matching A2A test-package namespaces. The wheel's denylist does not constrain a PyInstaller build from the source checkout, so the current onedir closure can carry non-runtime test code and its dependency reach despite the declared pruned-runtime intent. The smoke checks still pass; this finding concerns release composition, size, and unnecessary code surface. Ownership: `W04.P10.S50` must correct or explicitly justify the actual frozen closure before `W05.P13.S65` certifies it.

S04 reproduction: a task-owned build environment deliberately containing both `server` and `freeze` dependencies again analyzed test namespaces and warned that `vaultspec_a2a.testing` could not import because pytest was absent. The completed artifact still passed smoke and contained no exact PostgreSQL driver modules. This is additional evidence for the existing packaging finding, not an ER18/server-profile failure; severity, status, and S50/S65 ownership are unchanged.

### qualification-capture-provenance | high | Frozen inputs lack replayable capture commands

Type: evidence reproducibility. Status: open; review-blocking for `W01.P01.S01`. The reference records exact-looking binary, checkout, host, toolchain, settings and lane facts, but the execution record preserves only the build command, two Python expressions described as running under uv, a test command and Core validation. It does not retain an exact invocation or immutable raw-output digest for the clean pre-build status, executable hash and onedir extent, Dashboard revision and component-lock parse, host identity, provider executable versions, selected settings, or complete lane/disposition output. That does not satisfy A32's exact-command boundary and makes configuration override or transcription drift impossible to distinguish later. Ownership: correct S01 itself by recording replayable locked commands and results or immutable output artifacts for every frozen input, including the two-repository clean state and source revision, before reviewing the Step again.

Resolution status: resolved in the S01 correction; formal re-review pending. The qualification reference now retains exact PowerShell/locked-uv capture recipes, compact canonical raw JSON, SHA-256 output digests for identity (`338CA23E...`), host/toolchain (`8C0CA3EA...`), runtime config (`45F14465...`), external catalog (`D6984BB5...`), internal posture (`65BA2E94...`) and Dashboard bounds (`A0B49E9E...`), plus a source-manifest digest (`C409D644...`) and per-file hashes. It preserves the original clean pre-build status arrays and distinguishes ignored build output.

### dashboard-pretest-deadlines-incomplete | high | The frozen deadline inventory omits active consumer bounds

Type: contract and evidence completeness. Status: open; review-blocking for `W01.P01.S01`. The reference freezes the Dashboard broker's 120-second heartbeat staleness and 1.5-second health probe but omits other active bounds at the same consumer generation: broker read 15 seconds, broker control 60 seconds, broker catalog discovery 45 seconds, lifecycle discovery freshness 30 seconds, gateway stop-plan budget 5 seconds, and product drain connect/max-deadline bounds of 5/600 seconds. The 30-second lifecycle freshness and 120-second broker freshness are different surfaces and must not be collapsed. S02 owns resolving their contract semantics, but S01 explicitly owns freezing pre-test deadlines before results can influence them. Ownership: add the exact current values, source owners, and qualification use to the S01 reference, then let S02 reconcile which bound governs each operation.

Resolution status: resolved in the S01 correction; formal re-review pending. At Dashboard commit `330b2efe...`, the reference now records broker read/control/catalog budgets of 15/60/45 seconds, resident freshness/health of 120/1.5 seconds, product lifecycle freshness/stop-plan of 30/5 seconds, and product drain connect/max bounds of 5/600 seconds. It names and hashes `a2a.rs`, `a2a_lifecycle.rs`, and `gateway_drain.rs`, retaining the two freshness predicates as different surfaces.

### database-pool-backend-conflation | medium | The pool limit is presented as a SQLite admission bound

Type: evidence accuracy. Status: open. The `Database admission` row combines SQLite's 5,000ms busy timeout with a pool of 5 plus 10 overflow. Live source applies `db_pool_size` and `db_pool_max_overflow` only when the URL starts with PostgreSQL; the default SQLite engine does not receive those QueuePool arguments. A28 could therefore measure the wrong connection ceiling if this row is read as one backend's configuration. Ownership: S01 must label 5 plus 10 as PostgreSQL-only and record the effective SQLite pooling behavior separately before connection-peak qualification.

Resolution status: resolved in the S01 correction; formal re-review pending. The reference now separates SQLite's 5,000ms busy timeout from PostgreSQL's configured QueuePool size 5 plus overflow 10. It records that file SQLite currently resolves to SQLAlchemy `AsyncAdaptedQueuePool` with observed library defaults 5/10 while A2A passes neither configured pool kwarg on the SQLite branch; the values are therefore version-bound observation rather than a SQLite service contract.

### in-process-mode-posture-unspecified | medium | The supported-mode inventory does not freeze internal lane disposition

Type: evidence completeness. Status: open. The eight-row table is correctly described as the complete external registration set, but the Step requires a supported-mode inventory and the closing paragraph names mock and deterministic lanes without their exact keys or effective current posture. At capture, environment arming is false and no in-process lane is served; explicit test arming adds `deterministic/in-process-deterministic`, while `mock/in-process-mock` additionally requires a configured mock base. Ownership: S01 must record these exact conditional keys and current served disposition while retaining their exclusion from external-provider proof.

Resolution status: resolved in the S01 correction; formal re-review pending. The reference and canonical posture capture now name `deterministic/in-process-deterministic` and `mock/in-process-mock`, record arming false, arming environment absent, mock base absent, and effective served set empty. It also records the armed-without-mock and armed-with-mock results and retains their exclusion from external-provider proof.

### dashboard-rust-toolchain-unlaunchable | low | Focused Dashboard Rust tests cannot start on this host

Type: validation environment. Status: open; non-blocking for the S01 evidence-only correction. Both `cargo test -p vaultspec-product gateway_drain` and `cargo test -p vaultspec-api a2a_lifecycle` resolve Cargo to `C:\ci-shared\cargo\bin\cargo.exe` and fail before compilation with Windows reporting that no application is associated with the specified file. Exact source-constant assertions and SHA-256 capture remain available and are sufficient to freeze the S01 inputs, but this host cannot supply executable Rust-test confirmation. Ownership: repair or replace the configured Cargo toolchain before `W01.P01.S02` consumer-contract verification, then rerun both commands; retain the failure as environment evidence rather than treating it as a product-test result.

### qualification-capture-provenance-rereview | high | RESOLVED - frozen facts have replayable commands and canonical digests

Type: evidence reproducibility. Status: resolved at corrected S01 commit `00fa034705727903d464ae4d937d9fdf14edce23`. Formal re-review recomputed all seven retained canonical JSON lines and obtained the recorded SHA-256 digests. It also recomputed all 17 source-manifest entries against the named A2A and Dashboard checkouts with zero mismatches, and independently matched the executable hash. The exact commands, raw compact observations, digest convention, clean tracked-status scope and ignored-build-output exclusion are sufficient for this evidence-only Step; later behavioral qualification must still create its own revision-bound observations.

### dashboard-pretest-deadlines-rereview | high | RESOLVED - active consumer bounds are frozen by distinct surface

Type: contract and evidence completeness. Status: resolved at corrected S01 commit `00fa034705727903d464ae4d937d9fdf14edce23`. Formal re-review matched all nine recorded values to the three hashed Dashboard source owners: broker read/control/catalog 15/60/45 seconds, broker freshness/health 120/1.5 seconds, product lifecycle freshness/stop-plan 30/5 seconds, and product drain connect/max 5/600 seconds. The 30-second lifecycle predicate and 120-second broker predicate remain explicitly distinct; S02 retains ownership of contract reconciliation.

### database-pool-backend-rereview | medium | RESOLVED - SQLite and PostgreSQL limits are separated

Type: evidence accuracy. Status: resolved at corrected S01 commit `00fa034705727903d464ae4d937d9fdf14edce23`. The corrected reference assigns the 5,000ms busy timeout to SQLite and the configured QueuePool size 5 plus overflow 10 to PostgreSQL only. Its separate observation that the locked SQLAlchemy version currently chooses `AsyncAdaptedQueuePool` defaults 5/10 for file SQLite is explicitly version-bound and not treated as an A2A SQLite capacity contract.

### in-process-mode-posture-rereview | medium | RESOLVED - exact conditional keys and effective posture are complete

Type: evidence completeness. Status: resolved at corrected S01 commit `00fa034705727903d464ae4d937d9fdf14edce23`. Formal re-review reproduced the empty effective in-process set with arming absent/false, `deterministic/in-process-deterministic` under explicit arming, and the additional `mock/in-process-mock` only with a nonblank mock base. Seventy-three focused provider admission and in-process catalog tests pass, and both lanes remain excluded from external-provider proof.

### dashboard-rust-toolchain-launcher-rereview | low | Default shared shim remains broken but focused Rust validation is available

Type: validation environment. Status: open, narrowed and non-blocking. The default PATH resolves Cargo and rustc through unlaunchable symbolic links in `C:\ci-shared\cargo\bin`, but the user rustup shims are valid. With `C:\Users\hello\.cargo\bin\cargo.exe` and `RUSTC=C:\Users\hello\.cargo\bin\rustc.exe` explicit, `cargo test -p vaultspec-product gateway_drain` passed 16 tests and `cargo test -p vaultspec-api a2a_lifecycle` passed 21 tests. The original low classification remains appropriate because this is a launcher-path defect with an exact working route, not missing consumer certification. Ownership: repair the shared shim or PATH before final qualification; use the recorded explicit shims for S02 meanwhile. No critical, high, or medium S01 correction defect remains.

### embedded-discovery-wire-contract-drift | high | A2A producer and Dashboard consumer cannot interoperate

Type: contract and integration. Status: open. At A2A `97f8dc2478cc75338c6c77e3ba9202fa87c59454`, the armed desktop producer writes `service.json` with integer version, package-derived generation and nested process/endpoint. Dashboard `330b2efe294c8ab134fff2142f9fae98afd14fec` consumes `gateway-discovery.json` with receipt identity, release set, string protocol range, state-schema range and heartbeat. The resolved contract is Dashboard's receipt-bound schema with actual packaged migration range `0001`-`0016`; the legacy record is excluded from the embedded lane. Ownership: `W04.P10.S47-S48`, release closure `S50`, proof `W05.P13.S64-S65`.

### embedded-broker-foreign-substitution | high | Product broker can select a foreign resident for mutation

Type: authorization and lifecycle. Status: open. Live Dashboard source dual-resolves product discovery and legacy resident discovery, classifies a foreign owner as `ForeignReadOnly`, but the seven-operation broker has no attach-mode guard and includes mutations. The resolved embedded contract permits only the receipt-joined product process; foreign resident state is separately observable and read-only. Ownership: broker steps `W04.P09.S43-S45` and lifecycle/discovery steps `W04.P10.S47-S48`; closing proof `W05.P13.S64-S65`.

### embedded-discovery-receipt-compatibility-gap | high | Parsed identity is not joined to the active receipt

Type: state compatibility and evidence. Status: open. Dashboard currently accepts broad state schema `0001`-`9999` and does not prove the discovery generation, install identity and release member against its active receipt before attach. The coordinated contract requires exact lock/member/receipt/executable/discovery agreement and the packaged migration range. Ownership: `W04.P10.S47-S50`; closing proof `W05.P13.S64-S65`.

### embedded-component-authority-drift | medium | Supplier-local manifest claims conflict with Dashboard release authority

Type: architecture and packaging. Status: open. A2A `desktop/contract.py` derives generation from the package and describes a supplier-local component manifest, while accepted Dashboard decisions place selection and release receipt authority in Dashboard. Dashboard commit `dbc15e6f0976d82919f19ecebd991499e25a2b02` now records the single-home coordinated contract and preserves the current lock drift. Ownership: `W04.P10.S47-S50`; qualification `W05.P13.S65`.

### dashboard-rust-toolchain-s02-validation | low | RESOLVED - focused consumer tests run through explicit rustup binaries

Type: validation environment. Status: resolved for S02. From Dashboard `engine`, explicit `C:\Users\hello\.rustup\toolchains\1.96.0-x86_64-pc-windows-msvc\bin\cargo.exe` with matching `RUSTC` ran discovery-focused product tests (19 passing across the selected binaries) and `vaultspec-api a2a_lifecycle` (21 passing). An initial repository-root invocation failed because that directory has no `Cargo.toml`; it was a corrected command-location error. The shared PATH shim finding remains open independently.
### dashboard-vault-baseline-validation-debt | low | Full Dashboard Core check is not globally clean

Type: documentation hygiene. Status: open; unrelated and non-blocking for S02. `vaultspec-core vault check all` at Dashboard `dbc15e6f0976d82919f19ecebd991499e25a2b02` reports one pre-existing schema error (`runner-fleet-conformance` ADR has no grounding reference) and 80 warnings, chiefly stale feature indexes plus retired exec mappings and missing research sections. Focused `references` is clean; the new contract's body and feature index are valid. Ownership: Dashboard architecture-corpus curation, outside this remediation plan.

### s02-broker-decision-outside-adr | high | New broker capabilities conflict with the ADR-fixed seven-verb surface

Type: architecture and decision ownership. Status: resolved by S02 correction; originally review-blocking for `W01.P01.S02`. The coordinated reference assigns `S43`-`S45` durable follow-up messaging, permission response, and native command discovery/execution, but the accepted Dashboard orchestration-edge ADR is the authoritative home for the engine-fronted contract and says the whitelist grows to exactly seven verbs. That ADR also requires any edge change to be a reviewed contract event. A reference cannot silently expand or supersede the accepted decision, and the existing seven verbs contain none of the new capabilities. Ownership: correct S02 by amending the accepted Dashboard edge ADR to authorize the exact expanded whitelist and semantics, then make the coordinated reference derive from and mutually reference that decision. Do not advance to S03 while this conflict remains.

Resolution status: resolved in Dashboard architectural correction `02101b52d15e31a23b9c5cb181c9f6e648b25261`. The accepted edge ADR now carries a dated reviewed event expanding the authoritative whitelist from seven to exactly eleven verbs and mutually references the coordinated contract. No runtime surface changed; `S43-S45` retain implementation ownership.
### s02-future-broker-wire-underspecified | high | S43-S45 lack an implementable cross-repository wire contract

Type: contract completeness. Status: resolved by S02 correction; originally review-blocking for `W01.P01.S02`. The reference gives the current seven verbs exact methods, routes, 15/45/60-second budgets and retry posture, but describes the later message, permission, and native-command capabilities only in prose. It does not freeze exact engine verb names; A2A methods and paths; payload field, count and byte bounds; typed success, durable-receipt and conflict shapes; request/scope identity rules; or per-operation retry and status-reconciliation behavior. Native command discovery and execution are also two distinct exchanges despite being grouped as one capability. This leaves both repositories free to implement incompatible contracts in S43-S45, contrary to S02's purpose. Ownership: correct S02 by recording the complete bounded wire matrix under the authoritative edge decision and deriving the reference from it before runtime changes begin.

Resolution status: resolved in Dashboard architectural correction `02101b52d15e31a23b9c5cb181c9f6e648b25261`. The ADR and derived reference now name four exact engine verbs and A2A routes, every request field and bound, success and durable receipt shapes, typed A2A and Dashboard error envelopes, run/request/command/idempotency identities, budgets, scope/auth guards, replay, and authoritative reconciliation.
### s02-release-provenance-contract-incomplete | high | S50 handoff omits the accepted version-only producer artifact contract

Type: architecture and packaging. Status: resolved by S02 correction; originally review-blocking for `W01.P01.S02`. The accepted Dashboard provisioning ADR requires A2A to publish deterministic fixed-name per-target release archives with SHA-256 sidecars before the consumer lands, removes Dashboard source checkout, freeze, and commit pinning, converts the component lock to a released-version reference, and makes Dashboard fetch, verify, then bundle. The coordinated reference records the current commit-pin mismatch but reduces intended S50 behavior to building a released artifact and updating the lock/member/receipt chain. That wording does not preserve producer-first ordering, A2A build ownership, archive/sidecar verification, version-only selection, or deletion of source coupling, and can be read as allowing the rejected Dashboard-build or commit-pin path. Ownership: correct S02 by incorporating the accepted provenance constraints verbatim in meaning and citing their ADR authority; S50 then implements that already-decided contract.

Resolution status: resolved in Dashboard architectural correction `02101b52d15e31a23b9c5cb181c9f6e648b25261` and the corrected A2A S50 plan row. The contract now requires A2A to publish fixed per-target versioned archives and SHA-256 sidecars first; Dashboard selects only a released version, fetches/verifies/bundles, and removes source checkout, freeze, and commit pinning. Final lock/member/receipt/process/discovery agreement remains implementation proof owned by `S50` and `S65`.
### s02-formal-review | high | FAIL - contract authority and completeness defects block advancement

Type: implementation review. Status: open; S02 review failed at A2A `e9a56ff08edbe248600a21daa583183410ea822e` and Dashboard `dbc15e6f0976d82919f19ecebd991499e25a2b02`. The documentation-only commits are mechanically scoped and the replay evidence is sound: all 17 recorded source hashes and aggregate `D8EA71B...` digest reproduce, the exact current seven verbs and 15/45/60-second budgets match source, focused A2A tests pass 39, Dashboard discovery-focused tests pass 19, lifecycle tests pass 21, and broker tests pass 70 using explicit valid rustup shims. The known discovery, receipt, foreign-process, and component-authority product gaps are correctly assigned to S43-S50 and do not independently defect this evidence step. The three preceding HIGH defects are in S02's contract record itself, so S02 must be reopened and corrected before S03.

Correction status: implemented at Dashboard `02101b52d15e31a23b9c5cb181c9f6e648b25261`; formal re-review pending. The correction preserves the review failure as history, changes no runtime wire, and reopens/closes only S02 after Core and contract-consistency validation.

### s02-existing-verb-retry-contract-regression | high | Correction drops the current mutation retry and reconciliation rules

Type: contract completeness and regression. Status: resolved by S02 correction; originally review-blocking for corrected `W01.P01.S02` at Dashboard `02101b52d15e31a23b9c5cb181c9f6e648b25261`. The correction resolves the three original HIGH subjects, but replacing the broker table removed its retry-rule column. Neither the amended authoritative edge ADR nor any current Dashboard ADR/reference now preserves the frozen current behavior that `run-start` permits exactly one retry after an ambiguous connection or protocol failure using the same run, reservation, and payload before authoritative status reconciliation; `run-cancel` forbids blind retry and reconciles status; and `clarification-respond` forbids blind retry while preserving request identity and reconciling the result. Live source still contains the specialized run-start replay/reconciliation path. The new three mutating capabilities have complete idempotency and reconciliation rules, but S02 owns the complete eleven-verb contract and cannot regress existing wire facts while adding four operations. Ownership: correct S02 by restoring the three existing mutation rules in the authoritative edge decision and its derived operation table, without weakening the new idempotency contract.

Resolution status: resolved in Dashboard correction `89706fb2641bd5482667437ae1e4abf2d8194fd8`. The authoritative ADR now states retry and reconciliation for all eleven verbs, and the derived eleven-row table carries a dedicated rule column. It restores run-start's single ambiguous connection/protocol retry with identical run/reservation/payload and authoritative status reconciliation, run-cancel's no-blind-retry/status rule, and clarification response's request-preserving no-blind-retry/result rule without weakening the new mutation receipts.

### s02-edge-adr-d2-marker | low | A literal plus sign corrupts the D2 decision marker

Type: documentation quality. Status: resolved by S02 correction; originally non-blocking by itself. Dashboard `02101b52...` leaves the line `+**D2 — Actors and tokens are provisioned by the engine at run start.**` after the new amendment. Core markdown validation accepts it as prose, but the literal plus breaks the ADR's established bold decision-marker form and makes D2 harder to scan and parse semantically. Ownership: remove the stray plus in the S02 documentation correction.

Resolution status: resolved in Dashboard correction `89706fb2641bd5482667437ae1e4abf2d8194fd8`. The literal plus was removed and D2 is again a standalone bold decision marker.

### s02-corrected-formal-rereview | high | FAIL - original defects resolved but retry-contract regression remains

Type: implementation review. Status: open. Re-review at A2A `df8645c723d16298252c831ea8982836bbb59aed` and Dashboard `02101b52d15e31a23b9c5cb181c9f6e648b25261` confirms the accepted edge ADR legitimately expands seven verbs to exactly eleven; the four additions have exact names and routes, bounded inputs and outputs, typed receipts/refusals/conflicts/errors, identity, idempotency, authentication, scope, budgets, retry and reconciliation rules; ADR and reference mutually link and agree; producer-first fixed per-target versioned archives and SHA-256 sidecars, version-only Dashboard fetch-verify-bundle, removal of source build/checkout/commit pinning, and final receipt/process/discovery agreement are explicit; and S50 matches. A focused assertion passes the eleven-row matrix, four route bindings, bounds, envelopes, provenance and mutual links. A2A Core validation is clean, only S01/S02 are closed, S03 remains untouched, and both repositories are clean. The preceding HIGH regression prevents a PASS until the existing mutation retry rules are restored.

Correction status: implemented at Dashboard `89706fb2641bd5482667437ae1e4abf2d8194fd8`; formal re-review pending. A deterministic assertion counted exactly eleven table rows, checked every read and mutation retry/reconciliation rule, and rejected either malformed D2 marker.

### s02-final-formal-rereview | low | PASS - no critical, high, or medium S02 defect remains

Type: implementation review disposition. Status: resolved at A2A `54a871a1ca6bfd5c969c7dd86dd64ff7a66a462e` and Dashboard `89706fb2641bd5482667437ae1e4abf2d8194fd8`. Final re-review reproduced exactly eleven broker rows and a retry/reconciliation rule for every operation. `run-start` permits exactly one ambiguous connection/protocol retry with identical run id, reservation id, and complete payload, then authoritative status reconciliation while retaining an inconclusive lease and forbidding a second identity. `run-cancel` has no blind retry and requires authoritative status reconciliation before another explicit action. `clarification-respond` has no blind retry, preserves run/request/resolution identity, and reconciles authoritative run-status/checkpoint truth. Five reads permit only new independently bounded reads, and the three new mutations retain one identity-stable reconciliation replay, authoritative receipts, and typed `outcome_unknown` on a second ambiguity. The amended accepted ADR and derived reference agree on eleven verbs, routes, bounds, envelopes, identity, authentication, scope, idempotency, error behavior and producer-first release provenance; the D2 marker is repaired. Focused assertions covering both the retry matrix and all earlier HIGH corrections pass. Core validation is clean, the S02 Step Record points to the final Dashboard contract and preserves correction validation, only S01 and S02 are closed, S03 has no record and remains open, and both repositories were clean at the reviewed heads. The prior failure entries remain historical evidence; all S02 review-blocking findings are resolved and execution may advance to S03.

### provider-selection-positive-proof-absent | high | Catalog P03.S19 and P03.S20 remain open

Type: integration evidence. Status: open and qualification-blocking only for dependent external-provider and Dashboard claims. Live Core state at A2A `803dca968945d703092dbe8ecfaee0c6290cbd9f` reports provider-model-catalog 14/21 with prerequisite implementation rows `P01.S10` and `P01.S11` open and assembled evidence rows `P03.S19` and `P03.S20` open. The exact-mode registry contains eight external registrations, but only `codex/codex-app-server` has a literal completed-turn admission citation; that historical citation, catalog enumeration, selectability, handshake success, and skips do not prove the required real Dashboard-to-provider positive path or its state matrix. Ownership: provider-model-catalog `P01.S10-P01.S11` and `P03.S19-P03.S20`; remediation `W05.P12.S57` revalidates the released binary/receipt-matched Dashboard pair before `S58-S64` may consume the proof. Independent local remediation remains authorized as recorded in the S03 prerequisite reference.

### provider-capability-plan-state-source-drift | medium | Source presence cannot stand in for the 0/4 owner plan

Type: lifecycle and evidence accuracy. Status: open. Live Core state reports provider-capability-evidence 0/4 although `src/vaultspec_a2a/providers/provider_capabilities.py` exists and the legacy feature ledger names a target. No composition/population completion, exact-lane evidence, invalidation proof, or served disclosure is closed by that source presence. Ownership: provider-capability-evidence `P01.S01-P02.S04`; remediation `W03.P08.S35-S36` may implement under those explicit prerequisites but cannot report the owner plan complete or use it as external qualification evidence.

### provider-catalog-s08-step-record-gap | low | Checked catalog work lacks its Core execution trace

Type: lifecycle traceability. Status: open and non-blocking for S03. `vaultspec-core vault plan status .vault/plan/2026-08-02-provider-model-catalog-plan.md` reports checked `P01.S08` without a Step Record. The checked row remains current plan state, but the missing trace prevents treating its legacy ledger entry as reproducible positive evidence. Ownership: provider-model-catalog lifecycle reconciliation `P03.S23`; do not backfill proof by inference.

### provider-catalog-route-host-state-leak | medium | Focused route test assumes credentials are unavailable

Type: test isolation. Status: open and non-blocking for the S03 evidence-only record. The exact command `uv run --locked python -m pytest src/vaultspec_a2a/providers/tests/test_lane_admission.py src/vaultspec_a2a/providers/tests/test_provider_capabilities.py src/vaultspec_a2a/providers/tests/test_in_process_catalog.py src/vaultspec_a2a/api/tests/test_provider_catalog_route.py -q` produced 90 passes and one failure: `test_authenticated_route_serves_all_registered_lanes_in_order` expected OpenAI catalog status `unavailable`, while the checkout-local settings resolved it as `available`. The test constructs the real app without isolating its `.env`-backed settings, so its fixed availability assertion changes with host configuration. A rerun excluding only that named test passed 90 tests with one deselection. Ownership: provider-model-catalog validation hardening `P03.S22`; make the test control its settings or assert structurally valid environment-dependent health without exposing credentials. This failure is not positive S19/S20 evidence.
Resolution status: the route defect is corrected at provider-model-catalog `7d8c04df06299dc58ae8fd1a5f4092291f3042ab`; owning step `P01.S11` is reopened and pending. The test now asserts the real host's observed OpenAI and Z.AI availability through provider-keyed typed records rather than fixed positions or credential assumptions. It preserves independent configuration, transport, authentication, catalog, exact-mode admission, and selectability meanings: catalog/health states must agree, available catalogs carry entries/revision/expiry/authentication, unavailable catalogs carry no entries and a bounded reason, and both unadmitted lanes remain non-selectable. The formerly failing route and assembled 49-test local behavior set pass. Formal review `16066b83983a90a6a7dc067f98510e3fc5c040fc` established that S11 remains blocked by preceding `P01.S10` and missing real persisted legacy startup redispatch proof. Provider-model-catalog `P03.S19-P03.S20` and remediation `W05.P12.S57` remain downstream qualification owners.

### s03-formal-review | low | PASS - prerequisite evidence and qualification gates are complete

Type: implementation review disposition. Status: resolved at A2A `fefd7540e26ba0d41b08440d653e16a2915b4112`. The S03 reference accurately keeps provider-model-catalog `P03.S19` and `P03.S20` open and defines their required positive path, frozen-selection comparisons, and refresh, stale, unauthenticated, unavailable/unadmitted, admitted, replay/conflict, legacy-restart, and Dashboard-state evidence without treating enumeration, selectability, handshake, skips, historical provider-level proof, or in-process work as a substitute. It correctly gates dependent external-provider and Dashboard qualification at remediation `S57` while allowing independent environment, durability, context, broker, lifecycle, artifact, local-load, deterministic, and capability-matrix work under each owner's prerequisites. Exact-mode identity remains provider plus execution mode: eight external registrations are retained, only `codex/codex-app-server` carries an exact completed-turn admission citation, and provider-level or sibling-mode proof does not transfer. Both canonical replay digests reproduce exactly (`94A91AE6...` and `2525AAD1...`). The full focused test command reproduces 90 passes plus the one audited host-state route failure; excluding only that named isolation defect passes 90 with one deselection. This is adequate for the S03 evidence-definition step because no S19/S20 positive qualification is claimed. Core confirms provider-model-catalog 14/21 with `P01.S10`, `P01.S11`, `P03.S19`, and `P03.S20` open; provider-capability-evidence 0/4; checked catalog `P01.S08` without a Step Record; and remediation S01-S03 closed with S04 next. The four implementation-observed findings are correctly classified HIGH, MEDIUM, LOW, and MEDIUM and retain their stated owners. Core validation and commit mechanics are clean. No critical, high, or medium defect in S03 itself remains, so W01.P01 may complete and execution may advance to S04.

### postgres-server-profile-prerequisite | medium | RESOLVED - PostgreSQL checks run under their locked optional profile

Type: evidence environment and dependency isolation. Status: resolved by corrected `W01.P02.S04`; formal re-review pending. Supported `UV_PROJECT_ENVIRONMENT` flows now synchronize distinct bounded `server-env`, `freeze-env`, and `build-env` paths with `uv sync --locked`, then execute with `uv run --no-sync`. The server record proves exact requested and installed profile contents (digest `72A2469C...`) and 15 passing URL/settings/engine checks. The freeze record proves the three PostgreSQL distributions and imports absent (digest `F4EAE3C1...`). The server-equipped build record proves them present before packaging (digest `C3378273...`), while the bounded post-build scan proves zero blocked modules among 5,720 PYZ names and zero blocked paths among 2,746 artifact files (digest `A0D70509...`). Exact commands, canonical outputs, roots, match grammar, hashes, and source-boundary digest `15CBFE69...` are retained in the corrected Step Record. Ownership after re-review remains the regression surfaces in `pyproject.toml`, `test_sync_url_derivation.py`, and the frozen spec, with final plan review at `W06.P14.S72`.

### s04-driver-exclusion-evidence-not-replayable | high | Decisive absence checks are recorded as placeholders

Type: evidence reproducibility. Status: open; review-blocking for `W01.P02.S04`. The Step Record claims that the freeze-only profile cannot import asyncpg, psycopg, or `langgraph.checkpoint.postgres` and that a server-equipped frozen build contains none of those exact modules or driver-named paths, but records the first command as `python -c <driver-import discriminator>` and the second only as an unnamed parse of `PYZ-00.toc` plus an artifact scan. Neither entry is executable, and no retained script, canonical raw output, digest, or per-path inventory supplies the missing procedure. Independent review reconstructed both checks and reproduced zero modules and paths, but reviewer inference is not a replay contract and cannot justify marking ER18 resolved under A32. Ownership: correct S04 by retaining exact locked commands or checked-in bounded probes for both absence checks, their source/build roots, match grammar, canonical results and digest; also record the exact locked server-profile sync dry-run invocation.

Resolution status: resolved in the S04 correction; formal re-review pending. The Step Record now contains four complete PowerShell/here-string Python recipes: freeze-only sync/import/distribution capture, server sync/profile capture/test, server-equipped freeze build/archive scan, and the zero-match durable-command assertion. It retains full compact JSON and SHA-256 digests, exact roots, requested and installed packages, 5,720 parsed PYZ names, 2,746 artifact files, match grammar, TOC/tree/binary hashes, and the source/status manifest. No placeholder remains.

### s04-uv-environment-claim-inaccurate | medium | Unsupported no-op environment option invalidated the isolation claim

Type: validation environment accuracy. Status: resolved in the S04 correction; formal re-review pending. The original commands used an unsupported no-op environment option and therefore ran against the shared project environment despite claiming separation. The corrected evidence uses only task-specific `UV_PROJECT_ENVIRONMENT` paths, explicit locked synchronization, and `uv run --no-sync`; each canonical record contains the actual `sys.prefix` and selected package contents. A targeted assertion over the S04-owned durable command surface reports zero occurrences of the removed option (digest `8735358C...`). Ownership: S04 correction complete; the unrelated Starlette deprecation remains assigned to S08.

### s04-formal-review | high | FAIL - implementation is sound but evidence mechanics block closure

Type: implementation review disposition. Status: historical fail; correction implemented and formal re-review pending. Review at `df84b7480603411c1af9e2dc0d3142d7bdf15261` confirms the `server` extra is the explicit locked PostgreSQL profile; base and `freeze` contain none of asyncpg, psycopg, or `langgraph-checkpoint-postgres`; the PyInstaller spec excludes all three import surfaces; 15 URL/settings/engine tests pass under the server profile; lock checking and the server sync dry-run pass; and a reconstructed archive scan finds zero exact driver modules among 5,704 parsed names and zero driver-named paths among 2,743 artifact files. The new test is a meaningful configuration discriminator because it fails when a package leaves `server`, enters base/freeze, or loses its freeze exclusion; runtime resolution and artifact scans remain separate evidence. The known collect-all test-module finding is correctly preserved as MEDIUM under S50/S65. The seven committed S04 paths are scoped correctly, feature Core is clean, only S04 closes, and unrelated codebase-health working changes were not considered or touched. The preceding HIGH reproducibility defect prevents advancement to S05 until S04's record is corrected.

### s04-corrected-formal-rereview | low | PASS - dependency-profile evidence is replayable and isolated by task environment

Type: implementation review disposition. Status: resolved at `dba2b7eebb61301679f515661f175154fedd12bd`. Final re-review executed the supported task-specific `UV_PROJECT_ENVIRONMENT` flows for distinct `server-env`, `freeze-env`, and `build-env` roots, with explicit `uv sync --locked` followed by `uv run --no-sync`; the shared project `.venv` is not selected and the removed deprecated option has zero occurrences across S04 durable surfaces. The server capture reproduces digest `72A2469C...` and 15 passing PostgreSQL URL/settings/engine tests. The freeze-only capture reproduces `F4EAE3C1...` with all three PostgreSQL distributions and import roots absent. The server-plus-freeze capture reproduces `C3378273...` with the drivers present before packaging, while the exact retained TOC/tree scan reproduces `A0D70509...`: 5,720 PYZ module names, 2,746 artifact files, zero blocked module or path matches, TOC hash `06AA128F...`, artifact manifest `1AE311B5...`, and binary hash `474B0E68...`. Source hashes and removed-option digest `8735358C...` also match. The explicit lock sync/check commands succeed. The server extra remains the sole declared home of asyncpg, psycopg, and `langgraph-checkpoint-postgres`; base and freeze stay SQLite-only, and the PyInstaller exclusion boundary is independently enforced. The new test remains a discriminating metadata boundary while environment and artifact probes verify realized behavior. ER18 resolution is justified; the collect-all test-module finding remains MEDIUM/open under S50/S65. Core validates the feature, only S04 closes, S05 remains next with no record, and concurrent codebase-health/runtime working changes were excluded from scope and preserved. No critical, high, or medium S04 defect remains; S05 may proceed.

### no-legacy-provider-model-decision | high | active legacy-success gates are superseded

Type: architecture and lifecycle reconciliation. Status: resolved at the
2026-09-05 no-legacy curation amendment; runtime removal remains open under
provider-model-catalog `P01.S10`. Earlier entries that treated successful legacy
profile disclosure, restart, or redispatch as a prerequisite remain historical
review evidence only. The accepted catalog decision now requires current
schema-v1 catalog selection as the sole provider/model authority and a typed
unsupported/incompatible outcome for every retired request, response, settings
alias, and durable-state shape before construction or dispatch, with no
translation, migration, substitution, or redispatch. The unchecked catalog
`P01.S11` and `P03.S20` rows and remediation prerequisite reference now carry
that negative proof. Remediation `W01.P02.S05` still depends on completed
`P01.S10`/`P01.S11`; the passing ER19 host-state correction alone cannot close
it. Full conflict inventory and live-code drift are recorded in
`2026-09-05-embedded-runtime-remediation-no-legacy-curation-audit`.

### no-legacy-curation-formal-review | high | FAIL - accepted Kimi ADR retains static map and profile authority

Type: architecture review disposition. Status: open at curation commit `41519f11bd093311cebedc0f34bd575a845eac30`; blocks provider-model-catalog `P01.S10` closure. The curation correctly reopens/aligned `P01.S11`, updates active catalog/remediation requirements, preserves historical execution/audit facts, and keeps runtime removal open. However, accepted `2026-07-17-kimi-provider-adr` still normatively requires `MODEL_MAP`/`PROVIDER_DEFAULT_MODELS` entries and a `[team.profiles.kimi]` overlay, contradicting the catalog ADR's sole current-schema authority. Exact correction and full disposition are recorded in `2026-09-05-embedded-runtime-remediation-no-legacy-curation-audit`; amend the Kimi ADR, then repeat formal review before S10 closure.

### no-legacy-active-plan-profile-option | high | open

Type: lifecycle conflict. Status: open at curation commit `41519f11bd093311cebedc0f34bd575a845eac30`; blocks provider-model-catalog `P01.S10` closure. Active served-capability-contract step `W05.P10.S28` retains an alternative that can redefine eligibility without unconditionally removing profiles from preset disclosure. The catalog ADR now prohibits profile summaries and preset-carried provider/model authority. The row must require profile removal in every branch and may separately retain or redefine only a topology signal with no provider/model/profile meaning. Full classification is in the no-legacy curation audit.

### no-legacy-curation-review-correction | high | active Kimi and served-plan conflicts resolved

Type: architecture review correction. Status: implemented; formal re-review
pending. The accepted Kimi ADR now preserves only its transport, current auth,
permission, isolation, and provisioning decisions while deferring all
provider/model/control selection to the catalog ADR and retiring static maps,
profiles, deprecated aliases, and alternate-transport fallback. Active served
contract step `W05.P10.S28` now removes profile disclosure unconditionally and
permits only topology-only eligibility with no execution-selection authority.
The preceding FAIL findings remain historical review evidence; catalog
`P01.S10` remains open for runtime removal.

### no-legacy-corrected-curation-rereview | high | FAIL - active eligibility equivalence conflicts with topology-only rule

Type: architecture and lifecycle review disposition. Status: open at `d9fd625587fbcb45857741bd8c8de94483f61ca9`; blocks provider-model-catalog `P01.S10` closure. The accepted Kimi ADR and served-capability `W05.P10.S28` corrections resolve both previously reported HIGH findings. A full active-row rescan found `W05.P10.S44` still equates preset-list eligibility with run-start dispatch eligibility, contradicting S28's topology-only, zero-selection-authority boundary. Retire that equivalence and handle preset topology readiness separately from the accepted run-start dispatch result. Full evidence and classification are recorded in the no-legacy curation audit.

### no-legacy-curation-second-review-correction | high | S44 eligibility domains separated

Type: architecture and lifecycle resolution. Status: corrected on 2026-09-05 after review commit `bdeb379482eabbb26a6af09e79a3d69de18565e4`; formal re-review remains pending. Unchecked served-capability step `W05.P10.S44` no longer equates preset-list topology readiness with run-start dispatch acceptance. Any retained preset signal has the topology-only, zero-authority boundary established by S28. The independent run-start requirement removes its redundant eligibility boolean or defines a retained result only as the accepted dispatch outcome after catalog selection and live admission gates, never as preset or profile eligibility. No plan row is closed and no runtime implementation is claimed by this correction.

### no-legacy-curation-final-rereview | low | PASS - authority and eligibility domains are reconciled

Type: formal architecture review disposition. Status: resolved through `665a26f94fe3a1f4af84a72bef0c3d8c2bf36d7e`. S44 now separates topology-only preset readiness from post-catalog dispatch acceptance and restores no provider/model/profile/selection authority. All prior Kimi, S28 and S44 review findings are resolved; accepted-ADR, active-plan and current-reference scans find no remaining architecture conflict. Historical records are preserved, no plan row closes, and runtime legacy removal remains explicitly open under catalog `P01.S10` with proof in `P01.S11` and `P03.S20`. All four affected feature Core checks report zero errors and zero warnings. No critical, high or medium curation defect remains; architecture curation review passes.

### acp-gemini-no-legacy-curation-correction | high | active contract corrected; runtime proof open

Type: architecture and rolling lifecycle finding. A live `P01.S10` audit found
two further compatibility surfaces: the ACP `models.availableModels` catalog
fallback and `gemini/gemini-cli-acp`, retained solely for existing configs. The
accepted catalog, provider-abstraction, and harness decisions now make ACP
catalog discovery configOptions-only and retire Gemini provider support in full.
Catalog `P01.S10`, `P01.S11`, `P03.S19`, and `P03.S20` carry removal, exact
seven-mode inventory, and negative proof. Frozen qualification captures remain
historical. No implementation or plan completion is claimed by this curation.

### expanded-gemini-retirement-curation-review | high | FAIL - accepted obligations remain outside corrected corpus

Type: formal architecture review disposition. Status: open through A2A `e76aff0dd5550d5fb041150760eb70ce0725f327` and Dashboard `5cae73928c8ffb4b47dcb322971a002ef208a258`. The nine-path A2A and six-path Dashboard changes correctly establish configOptions-only ACP discovery, exact seven-mode current inventory, complete Gemini retirement, topology-only presets, current schema-v1 catalog selection, typed refusal of retired state, and historical-only treatment of frozen eight-mode evidence. No plan row closes and live runtime removal remains owned by catalog `P01.S10` with proof under `P01.S11`, `P03.S19`, and `P03.S20`. Dashboard generic provisioning decisions remain generic and need no amendment; Antigravity's `.gemini` vendor path and Gemini-branded opaque labels create no Gemini lane authority. However, accepted tool-cores still defines Gemini as a command-line web lane and active P03.S16 owes proof for all remaining command-line lanes; accepted integration-testing still says a real Gemini path remains available for opt-in compatibility smoke. Accepted universal-rule-propagation also carries MEDIUM stale supported-provider examples. The formal review therefore fails until the two HIGH accepted obligations are amended and reviewed. Core checks are mechanically clean.

### expanded-gemini-retirement-curation-correction | high | reported A2A document conflicts corrected

Type: architecture and lifecycle review correction. Status: implemented on
2026-09-06 after review commit
`df1b05a6f70911928e6561dbeeb3a5dd305eeae3`; formal curation re-review
pending. The accepted web-grounding decision and unchecked tool-cores
`P03.S16` now quantify only over current provider-model catalog members and
give retired `gemini/gemini-cli-acp` no activation, persona, retrieval,
compatibility, or future proof obligation. The accepted real-stack
certification decision preserves deterministic service certification and
allows opt-in compatibility smoke only for current catalog lanes, with no
Gemini route or smoke debt. The accepted universal-rule-propagation decision
preserves provider-independent RuleManager delivery for current lanes while
marking Gemini examples and `.gemini/rules` as historical and
non-authoritative.

Historical dependency rationale, frozen captures, completed records, and the
original text of each amended ADR remain intact. Antigravity's vendor-owned
`.gemini/antigravity-cli` storage and Gemini-branded opaque model labels
remain nonconflicting vendor data for `antigravity/antigravity-cli`.
Dashboard curation remains passed at `f93c2fb4`. No runtime edit or plan-row
closure is claimed; provider-model-catalog `P01.S10` and its proof rows
continue to own live removal and qualification.

### expanded-gemini-retirement-curation-final-rereview | low | PASS - prior accepted-document conflicts resolved

Type: formal architecture review disposition. Status: resolved at `869ef969175223d065730a81d1a684a3d96b605c`. Tool-cores now limits every universal and remaining-lane obligation to current catalog members and gives retired Gemini zero activation, web, compatibility, or proof debt; unchecked P03.S16 states that boundary without closing. Integration testing limits optional compatibility smoke to current catalog members and makes prior Gemini availability/smoke prose historical. Universal rule propagation identifies only the provider-independent RuleManager mechanism as active, makes Gemini and `.gemini/rules` examples historical, and preserves Antigravity vendor storage and opaque labels without inventing a Gemini lane.

Accepted-ADR, active-plan, and current-reference scans now agree on configOptions-only ACP discovery, the exact seven-mode current inventory, schema-v1 catalog authority, and no provider/model/profile legacy support. Frozen eight-mode captures and completed historical facts remain intact. The correction has exactly six documentation paths, changes no source, preserves all checklist states, and leaves runtime retirement open under catalog P01.S10 and proof steps. All affected A2A and Dashboard feature Core checks report zero errors and zero warnings. No critical, high, or medium architecture-curation finding remains; the expanded curation review passes.

## Recommendations

- Keep the captured A2A and Dashboard identities distinct until the Dashboard component lock, release manifest, discovery generation, and running process agree.
- Establish the durable message capacity before running A10; do not reuse an unrelated stream or IPC buffer as `Q`.
- Make the freeze recipe collect explicit runtime modules and data or exclude every test namespace, then inspect the built archive as part of the release lifecycle discriminator.

- For `qualification-capture-provenance`, add a bounded capture recipe or immutable evidence file that reproduces every frozen value with project-locked tools and names both repository revisions and clean states.
- For `dashboard-pretest-deadlines-incomplete`, freeze every current broker, lifecycle, discovery, and drain deadline while keeping the 30-second and 120-second freshness predicates tied to their distinct consumers.
- For `database-pool-backend-conflation`, split SQLite timeout/pooling facts from the PostgreSQL QueuePool 5-plus-10 configuration.
- For `in-process-mode-posture-unspecified`, list the deterministic and mock execution keys, current arming state, conditional requirements, and exclusion from external work evidence.

- For `dashboard-rust-toolchain-launcher-rereview`, keep the explicit working user rustup shims in verification commands until the broken shared symlinks or PATH order are repaired; this environment cleanup does not block S02 evidence.

- For `s02-broker-decision-outside-adr`, amend the accepted Dashboard orchestration-edge ADR through its review process so the exact expanded whitelist has one authoritative decision home; keep the coordinated reference factual and derived.
- For `s02-future-broker-wire-underspecified`, define every S43-S45 exchange end to end, including verb, route, bounds, receipt/conflict schema, identity, timeout, retry and reconciliation behavior, before either repository implements it.
- For `s02-release-provenance-contract-incomplete`, carry the provisioning ADR's producer-first, version-only, fixed-archive and SHA-256 fetch-verification requirements into the coordinated handoff and make S50's ownership unambiguous.

- For `s02-existing-verb-retry-contract-regression`, restore the exact `run-start`, `run-cancel`, and `clarification-respond` retry and reconciliation rules under the authoritative edge decision and reflect them in the derived eleven-verb table.
- For `s02-edge-adr-d2-marker`, remove the literal plus before the D2 decision marker.

- For `s04-driver-exclusion-evidence-not-replayable`, replace both placeholder verification entries with exact bounded commands or retained probes and canonical results/digests, including the exact sync dry-run command.
- For `s04-uv-environment-claim-inaccurate`, retain task-specific uv project environments and explicit locked sync plus no-sync execution for every dependency posture.
- For `no-legacy-provider-model-decision`, remove the remaining runtime and Dashboard legacy paths under catalog `P01.S10`, then prove typed refusal and current-schema restart under `P01.S11` and `P03.S20`.

### s10-retired-nested-authority-crosses-durable-and-ipc-boundaries | high | open

Type: state compatibility and schema validation. Status: blocks provider catalog
`P01.S10` and therefore remediation `W01.P02.S05`. Formal review of A2A
`15766f92` reproduced valid-digest schema-v1 records that remain accepted after
adding root `profile_id`, selection `model_profile`, or control `profile_id`,
because unknown nested keys are ignored and excluded from the digest.
`DispatchRequest.model_assignment` also accepts nested retired fields. Ownership:
provider-model-catalog `P01.S10`; require closed exact-key durable and IPC schemas
and terminal redispatch proof for every retired nested shape before contact.

### s10-corrupt-mode-falls-through-to-fallback | high | open

Type: safety and fail-closed behavior. Status: blocks catalog `P01.S10` and
remediation `W01.P02.S05`. A coherent-digest persisted selection with an
impossible provider/mode pair passes parsing. Compiler construction then catches
the factory's structural `ValueError` as lane unavailability and substitutes a
fallback; a committed test uses `unavailable-mode` as the primary and expects
that result. Ownership: provider-model-catalog `P01.S10`; validate every frozen
lane structurally before construction, separate corruption from runtime
unavailability, and fail corrupt state terminally with no provider/worker
contact.

### s10-lane-admission-test-integrity-loss | medium | open

Type: evidence integrity and regression coverage. Status: open. Deleting the lane
admission suite also removed still-current all-provider classification,
deny-by-default, live proof-citation resolution, rotten-citation,
proof-immutability, and web-implies-turn discriminators. Profile-specific cases
are retired, but the current catalog admission invariants need adapted
replacement coverage. Ownership: provider-model-catalog `P01.S10`.

### s10-topology-preset-web-claim-guard-loss | medium | open

Type: product-truth regression coverage. Status: open. The deleted preset
web-claim suite was the only anti-vacuous scan of shipped team descriptions.
Persona and graph tests do not protect this topology-only product surface.
Ownership: provider-model-catalog `P01.S10`; restore a provider-independent scan
that forbids web/research promises in preset descriptions.

### s10-runtime-formal-review | high | FAIL - retired/corrupt state can be accepted and substituted

Type: formal implementation review disposition. Status: open at A2A
`15766f92bdb094a78ab783620522547e3223ea5a`. Removal of static model/profile
policy, Gemini support, ACP/Codex compatibility paths, and public legacy schema
surfaces is broadly complete; current inventory and production model call sites
are correct, project confinement remains covered, and focused tests/OpenAPI/Ruff
checks pass. The two HIGH durable/IPC fail-closed defects above prevent catalog
`P01.S10` closure and keep remediation `W01.P02.S05` blocked. The uncommitted S10
Step Record is review evidence only and cannot close the implementation.

### s10-correction-resolves-nested-fields-and-impossible-modes | low | resolved

Type: state compatibility review. A2A `e2934a2e` closes persisted and IPC key
sets at every nested layer and prevalidates every role/fallback provider-mode
pair before construction. Existing-digest retired fields, a corrupt later role,
and an impossible fallback now fail before worker or factory contact. The prior
two HIGH findings are resolved for those exact cases. Current admission citation
and topology-only preset claim tests also resolve the two prior MEDIUM coverage
findings.

### s10-structural-native-control-errors-still-fallback | high | open

Type: safety and fail-closed behavior. Status: blocks catalog `P01.S10` and
remediation `W01.P02.S05`. Provider-specific control semantics are not included
in whole-assignment prevalidation, while worker resolution still catches broad
factory `ValueError` as runtime unavailability. Unsupported or duplicate native
controls and other structural/configuration failures can therefore construct a
fallback. Independent review reproduced an unsupported Codex control reaching
and returning the fallback. Ownership: catalog `P01.S10`; prevalidate every
provider's control semantics, introduce a typed runtime-unavailable condition,
and catch only that condition for fallback, with later-role/fallback zero-contact
proof.

### s10-correction-formal-rereview | high | FAIL - structural errors can still substitute fallback

Type: formal implementation review disposition. Correction `e2934a2e` is scoped
and resolves the reported nested-key, impossible-mode and coverage defects, but
the remaining HIGH control/error-typing gap violates the same no-substitution
contract. Focused exact-commit verification passes 136 tests and Ruff/format/diff
checks pass. Keep provider-model-catalog `P01.S10` and remediation
`W01.P02.S05` open pending correction and formal re-review.

### s10-native-control-fallback-correction | high | resolved

Type: safety and fail-closed behavior. Final A2A correction `6e7015a6` validates
provider-specific controls across the complete frozen assignment before any
construction and makes compiler fallback catch only the dedicated production
`ProviderRuntimeUnavailableError`. Structural control, auth and configuration
errors cannot select a fallback. Primary, later-role and fallback corruption
prove zero contact; a real missing optional ACP runtime and a composed compiler
case prove the sole allowed typed fallback path. The remaining S10 HIGH is
resolved.

### s10-production-unavailability-monkeypatch-proof | medium | resolved

Type: test integrity. Superseded `98b61322` used a forbidden monkeypatch to
manufacture the production runtime condition. Final `6e7015a6` removes it and
uses the real absent optional ACP binary boundary; the production factory emits
the typed runtime-unavailable result without patching, faking or suppressing a
failure.

### s10-final-runtime-rereview | low | PASS

Type: formal implementation review disposition. Status: resolved through A2A
`6e7015a6c55fdf8633dbd35e4d8f40caa13425ed`. All nested-schema,
provider/mode, native-control, fallback and restored-coverage findings from both
prior reviews are resolved. Exact-commit factory verification passes 46 tests;
the final broad exact-commit suite passes 1,378 with 38 deselected and zero
failures in 270.47 seconds; Ruff, format, Ty, diff and feature Core checks pass.
No critical, high or medium S10 runtime defect remains. Provider-model-catalog
plan closure and its uncommitted Step Record remain executor-owned; remediation
`W01.P02.S05` may consume S10 only after that lifecycle closure and the separate
S11 prerequisite.

### s10-lifecycle-closure-review | low | PASS

Type: lifecycle and formal review disposition. A2A closure
`0c47e4c5758995d7bc55ef924b6547c11c07fa08` has exact passing-review parent
`039eea81fcb48d94daeadd369a442f41e7ebe6cb`, changes only four Core-managed
lifecycle paths, and checks only provider-model-catalog P01.S10. Its Step Record
matches all 125 actual source/OpenAPI paths and the reviewed commit identities,
validation counts, and complete deletion replacement map. Feature Core checks
are clean. Catalog P01.S11 and remediation W01.P02.S05 remain open, so this
closure introduces no false remediation completion. Formal lifecycle review
passes with no remaining finding.
### p01-s11-rag-data-plane-version-drift | medium | closed

Type: test environment and repository tooling. Historical status: open and
nonblocking for
P01.S11 runtime behavior. The S11 broad provider, gateway, redispatch, IPC and
compiler run passed 964 tests with 36 deselected and one environment failure:
`test_the_declared_channel_is_the_servers_own_root_authority`. Its real MCP
subprocess reached the shared vaultspec-rag endpoint at PID 56028 on
`127.0.0.1:8766`, but the service did not report a version compatible with the
0.4.23 client, so `search_vault` returned the typed service-down error before
the test could inspect project confinement. A read-only `vaultspec-rag server
start` probe confirmed the running service cannot be attached and requires an
operator-owned restart. Owner: embedded-runtime-remediation `W01.P02.S06` and
vaultspec-rag service lifecycle. The shared process was not stopped or restarted
inside P01.S11.

Resolution evidence (W01.P02.S06): the real production-registry stdio MCP
entry point and a real RAG service now run from the same exact version selected
by `uv.lock`. The service owns a private loopback port and isolated status,
data and Qdrant-storage directories; it uses the current `--local-only` and
`--no-updates` controls. Its published service record must match the locked
version and private port before the MCP call runs. The project-pin discriminator
passed against that private data plane, the complete pinning module passed 33
tests, and owned cleanup stopped the private service. The unrelated service
retained PID 56028, port 8766 and package 0.4.23 across the run; the
service-token SHA-256 was
`6a1967743b274c05f778759a1c70141f8717d70308bea34beb69df994c9ded5a`
and the digest comparison was `changed=false`. Ruff, format and Ty pass.
### p01-s11-cold-catalog-shutdown-timeout | medium | open under W04.P10.S49 after S07 diagnosis

Type: provider-degradation test stability and resource lifecycle. Status: open
and nonblocking for the reviewed S11 test changes. A post-broad focused rerun
observed one existing restart evidence test spend 91.79 seconds in a cold
provider-catalog refresh, log a Claude discovery `TimeoutError`, and then exceed
its five-second Uvicorn shutdown wait while the cancelled request and SQLite
connection unwound. The same test passed in the preceding 71-test focused run
and the 964-pass broad run, and the final changed-path discriminator run passed
20 tests, so this is intermittent host/provider degradation rather than a
repeatable selection-authority failure. Owner: embedded-runtime-remediation `W01.P02.S07` for representative-host
diagnosis and `W04.P10.S49` if the shutdown path requires runtime correction.
W01.P02.S06 did not execute a provider-catalog refresh or Uvicorn shutdown and
therefore does not claim this distinct finding. Preserve the failure for a
bounded cold-refresh/shutdown discriminator; do not widen a timeout as a
substitute.
### p01-s11-test-only-formal-review | high | FAIL - fresh production worker proof is absent

Type: prerequisite implementation review disposition. Catalog test commit
`ba9f70bd4d280ca95a3f31131443949317a0ae9d` preserves the current-only runtime
contract and its focused/static checks pass, but its positive restart case calls
redispatch directly against the minimal `ASGITransport` recording worker. It
does not boot fresh production gateway/worker instances or prove that the
production worker consumes the exact frozen selection. The retired request
matrix also checks only generic non-empty 422 detail rather than the expected
typed, non-disclosing refusal. These evidence findings are owned by catalog
P01.S11; remediation W01.P02.S05 remains blocked. The separately queued RAG
version drift and cold-catalog shutdown timeout remain correctly classified
MEDIUM under W01.P02.S06.
### p01-s11-validation-error-input-reflection | medium | resolved

Type: runtime security and response disclosure. Tightening the P01.S11 retired
input discriminator exposed that FastAPI's default request-validation response
returned the rejected caller value in each error object's `input` field. A
retired provider, model or profile value was therefore refused before dispatch
but reflected through the public 422 response, violating the no-disclosure
contract. The gateway now owns a bounded `RequestValidationError` handler that
retains the actionable validation `type`, field `loc` and safe `msg` while
removing `input` and `ctx`. Real loopback tests prove exact typed field errors,
exact bounded stale/domain reasons, absence of every submitted retired value,
and preservation of actionable current-schema validation. Resolved in the
P01.S11 correction following `ba9f70bd`; formal re-review remains required.

### p01-s11-correction-formal-rereview | high | FAIL - complete frozen identity remains unproven

Type: prerequisite implementation review disposition. A2A correction
`550f26fc944182eca92d5afe007f925dd3e9d388` resolves the prior fake-worker and
validation-disclosure findings: restart now crosses a production child gateway,
auto-spawned worker, real loopback and Executor, while the global 422 handler
retains OpenAPI-declared actionable fields and removes reflected rejected values.
However, the restart discriminator samples provider, mode, model, controls and
revision rather than comparing the full frozen JSON/digest or binding that exact
complete assignment to production-worker consumption. Catalog P01.S11 and
remediation W01.P02.S05 remain blocked by this HIGH evidence gap. An initial
worker-health ReadTimeout failure followed by a clean 61.71-second rerun after
concurrent live-process cleanup remains owned by the queued W01.P02.S06
resource-lifecycle work.
### p01-s11-graph-cache-omits-frozen-assignment | high | resolved pending formal review

Type: execution state isolation and restart integrity. The full-assignment
production discriminator exposed that the worker graph cache keyed only on team
preset, canonical workspace and autonomous mode. Concurrent runs with different
schema-v1 frozen assignments could therefore share whichever graph compiled
first, silently substituting one run's provider/model/control/fallback authority
for another's. The P01.S11 correction makes the canonical semantic digest of
the complete closed IPC model assignment the fourth required cache-key element,
rejects a changed assignment on an already mapped thread, and retains reuse only
for exact equal assignments. Real child gateway/worker recovery now drives two
equal freezes and one distinct freeze at the same topology/workspace/mode and
proves separate per-thread checkpoint digests; direct cache tests cover equality,
partitioning, and changed-assignment refusal. No three-element compatibility
constructor remains. Owner: P01.S11; formal re-review is required before closure.

### p01-s11-node-metadata-is-not-thread-scoped | high | resolved pending formal review

Type: execution state isolation and truthful disclosure. While binding complete
assignment evidence, a distinct concurrent run revealed that the control
surface's graph node metadata cache was global by node name rather than scoped by
thread. Histories or team projections for runs sharing node names could therefore
show provider/model metadata from the most recently registered graph. The S11
correction keys live graph metadata by thread and node at registration, cache-hit,
relay, emission, team-status and snapshot seams, with no global lookup. The
production Executor also writes the graph's safe node descriptors and complete
assignment digest into each run's LangGraph checkpoint; completed-run history
prefers that durable thread-scoped authority. A real child gateway/worker recovery
with concurrent equal and distinct assignments proves each run retains its own
provider, model and digest, and a direct relay test proves one thread cannot
overwrite another. Owner: P01.S11; formal re-review is required before closure.

### p01-s11-execution-reentry-omits-frozen-assignment | high | resolved pending formal review

Type: remediation prerequisite and message/resume integrity. The S11 correction
keys worker graphs by complete assignment digest, but message, permission,
clarification, verdict and direct-control recovery dispatch constructors omit
`model_assignment` and therefore send `{}`. Current-schema runs with non-empty
frozen assignments are refused instead of executing their next turn. Owner:
P01.S11. Route every execution re-entry through one shared resolver for the
exact validated current-schema frozen compiler map; absent, corrupt, retired or
old-schema authority must fail typed incompatible before dispatch with no repair
or migration. Cover every re-entry surface with a real current-run test.

### p01-s11-thread-assignment-binding-depends-on-cache-residency | high | resolved pending formal review

Type: remediation prerequisite, concurrency and cache safety. Assignment mismatch
is checked only while the mapped graph remains in the LRU. After normal eviction,
a changed assignment recompiles; concurrent first dispatches can also compile
different assignments before either mapping lands. Owner: P01.S11. Atomically
bind thread identity to digest before compile, compare independent of graph
residency, serialize in-flight same-thread compilation, and test eviction plus
concurrent equal/different deliveries with zero provider construction on mismatch.

### p01-s11-current-checkpoint-evidence-is-not-reconciled | medium | resolved pending formal review

Type: durable evidence continuity. Descriptor and full-assignment digest fields
are written only on first ingest, so a pre-existing current-schema checkpoint is
not populated during fresh-worker recovery and can lose agent/digest history
after live metadata pruning. Owner: P01.S11. Reconcile missing evidence only from
an exact validated current-schema frozen authority; never repair or migrate an
absent/old provider schema, which remains typed incompatible before contact.

### p01-s11-full-assignment-correction-review | high | FAIL

Type: prerequisite implementation review disposition. Exact correction
`aae2ac389ddb63a891b90c77b9236b6bb6e7db29` resolves cross-thread cache-key and
node-metadata contamination, and independent focused checks pass, but the two
HIGH execution-authority gaps above block catalog P01.S11 and remediation
W01.P02.S05. S11 remains open; no remediation row is closed by this review.

### p01-s11-checkpoint-projection-validation | medium | resolved pending formal review

Type: persisted-state robustness. History accepts malformed or valid-but-wrong
checkpoint assignment digests without reconciling them to exact current-schema
frozen authority, and open descriptor dicts can override node/agent identity.
Owner: P01.S11. Close and bound checkpoint evidence at read, compare the compiler
digest server-side, and return typed degraded/incompatible state; never repair or
translate missing, old or retired provider authority.

### p01-s11-team-status-thread-association | medium | resolved pending formal review

Type: concurrent projection integrity. Thread-scoped metadata lookup is fixed,
but team status flattens agents from multiple active threads without retaining
their thread ids, leaving equal role names ambiguous. Owner: P01.S11 or the team
status contract workstream; preserve run association and prove two concurrent
same-role runs.

### p01-s11-cross-thread-agent-accessor | low | resolved pending formal review

Type: hardening. An optional no-thread agent-state accessor remains, although no
current production caller uses it. Require thread identity so future code cannot
silently recreate the retired global fallback.

### p01-s11-reentry-binding-and-recovery-correction | high | resolved pending formal review

Type: remediation prerequisite and state integrity. One exact current-schema
resolver now supplies every graph re-entry. Atomic per-thread digest binding is
established before compile, survives graph eviction, compares checkpoint evidence
on fresh workers and serializes concurrent first delivery. Checkpoint evidence is
closed and reconciled through ordinary turn input or the real resume command's
atomic update; malformed, wrong, absent provider authority and retired authority
fail bounded before provider contact. History, team status and SSE agents carry
their originating run id, and no optional global agent-state accessor remains.

Two implementation findings surfaced and were corrected in the same pass. A
pre-resume `aupdate_state` invalidated the parked LangGraph interrupt, so evidence
now rides `Command.update`. A fast worker could consume the questionnaire before
identical clarification replays read it and those replays returned 409 despite a
matching accepted durable action; matching request and resolution identity now
returns that action. Real loopback worker tests cover both paths. Owner: P01.S11;
formal re-review remains required before S11 or remediation S05 can close.

### p01-s11-final-correction-formal-rereview | high | FAIL

Type: remediation prerequisite review disposition. Exact catalog correction
`3ee6529d2eb533ba7088e871b90169560bbb4880` fixes shared current-schema re-entry,
per-thread digest comparison across cache/restart/races, atomic resume evidence,
clarification replay, checkpoint projection and explicit history/team/SSE thread
association. Independent focused and real-worker checks pass. Three HIGH catalog
findings still block P01.S11 and remediation W01.P02.S05: otherwise current
metadata accepts retired root profile/model-map authority; checkpoint lookup is
scheduled before capacity reservation and has no deadline, allowing unbounded
stalled tasks and locks during backend degradation; and terminal runs retain
per-thread cache/digest identity for the worker lifetime. A MEDIUM exact-cache-key
cross-thread compilation herd also remains queued. Correct these through catalog
P01.S11, retain interrupted/reconciling identity, prove bounded cleanup and
zero-contact retired refusal, then obtain another formal review. No remediation
row is closed by this audit update.

### p01-s11-bounded-authority-lifecycle-correction | high | resolved pending formal review

Type: remediation prerequisite and bounded state integrity. P01.S11 now refuses
the complete retired root authority set before parsing an otherwise current
freeze; reserves worker capacity atomically before scheduling, checkpoint reads
or graph locks; shares one configured total checkpoint deadline; releases every
reservation on all exit classes; retires per-thread digest/cache identity on
completed, failed and cancelled settlement while retaining parked interrupts;
and single-flights compilation across threads by the complete graph cache key.
Real held-SQLite, endpoint 429, cancellation, timeout, high-volume terminal,
durable late-reentry and same/distinct-key concurrency controls pass. No retired
state is parsed, reflected, migrated or dispatched. Owner remains P01.S11;
remediation W01.P02.S05 and S11 stay open until formal re-review.

### p01-s11-bounded-lifecycle-correction-formal-rereview | high | FAIL

Type: remediation prerequisite review disposition. Catalog correction
`3f5ef6e7d401506fb9a5ee3fb471162af6e8fe91` resolves the retired-root,
precompile deadline, terminal identity retention and exact-key compile-flight
findings, and its focused evidence passes. One HIGH capacity-ownership race still
blocks P01.S11 and remediation W01.P02.S05: a settled dispatch releases its plain
thread-id reservation in `_mark_ingest_done` and again in the outer handler
`finally`, so an intervening new dispatch's reservation can be removed by the
old owner. Require one owned/tokenized or single-site release invariant and an
orchestrated A-terminal/B-reserve/A-finally discriminator across endpoint and
direct paths. No remediation row is closed by this audit update.

### p01-s11-capacity-generation-ownership-correction | high | resolved pending formal review

Type: remediation prerequisite and concurrency integrity. Worker capacity is now
owned by an opaque per-dispatch generation token rather than a bare thread-id set.
Every release is identity checked, so an older terminal or outer-finally cleanup
cannot erase a new dispatch's reservation after same-thread reuse. The
orchestrated A-release/B-reserve/A-finally control proves B remains counted and
holds the configured bound against a third dispatch; endpoint and direct
completion, failure, timeout and cancellation controls retain their release
coverage. Owner remains P01.S11; S11 and remediation W01.P02.S05 stay open for
formal re-review.

### p01-s11-capacity-generation-final-formal-rereview | high | FAIL

Type: remediation prerequisite review disposition. Exact catalog correction
`bded79c79ba3437fc9f34bcbf82ab1d8d395797c` replaces thread-id-only release with
opaque monotonic per-dispatch ownership. Every endpoint and direct ingest/resume
path carries the exact reservation object, repeated cleanup is safe, and an old
finalizer cannot remove a newer same-thread permit. Independent focused checks
and an orchestrated A/B/stale-finalizer/full-cap control pass. All earlier S11
retired-authority, checkpoint deadline, identity lifecycle, cache-flight,
checkpoint projection and messaging corrections remain intact. The ABA defect is resolved, but the MEDIUM concurrent identical ingest/resume
response-ordering issue is review-blocking because same-ID replay is an explicit
P01.S11 contract: execution stays single and bounded, yet the duplicate can
receive 429 instead of the required idempotent success response. P01.S11 and
remediation W01.P02.S05 remain blocked pending atomic ID/capacity admission and
concurrent endpoint evidence. This audit update closes no row.

### p01-s11-concurrent-duplicate-admission-correction | medium | resolved pending formal review

Type: remediation prerequisite and idempotency ordering. The worker endpoint now
rechecks the exact stable dispatch ID after an awaited capacity refusal and
before emitting 429. Concurrent identical ingest and resume requests therefore
reuse the admitted 200 response without a second schedule or reservation, while
a different same-thread ID and real process-cap exhaustion remain typed 429.
Production-lock endpoint controls prove one retained ID, one generation, equal
replay bodies and complete token release. Owner remains P01.S11; S11 and
remediation W01.P02.S05 stay open for final formal re-review.

### p01-s11-concurrent-duplicate-final-formal-rereview | low | PASS

Type: remediation prerequisite review disposition. Exact catalog correction
`6db8cd3b384872b8cdb8b5b731fa4495fd4d7bbd` rechecks stable dispatch identity
after an awaited capacity refusal. Concurrent identical ingest and resume calls
now receive equal idempotent 200 responses with one scheduled task, one retained
ID and one fully released generation token; different IDs and real capacity
exhaustion remain typed 429. The opaque ownership/ABA fix and every earlier S11
execution-authority, checkpoint, terminal-lifecycle, graph-flight, projection and
messaging correction remain intact. Independent worker/Executor checks pass, and
no review-blocking finding remains. P01.S11 is ready for its separate Core
lifecycle closure; remediation W01.P02.S05 must wait for that closure. This audit
update closes no row.
### p01-s11-core-lifecycle-closure | low | closed prerequisite

Type: remediation prerequisite lifecycle. Provider-model-catalog `P01.S11`
closed through Core after formal PASS review
`3578151f3b5e5f18cba2eb17967755be3cd120cc`. Its Step Record retains the full
current-only implementation chain, exact behavior evidence and finding
classifications. This supplies a completed prerequisite to remediation without
closing remediation `W01.P02.S05`; that row remains open for its own assembled
qualification and review.

### p01-s11-core-lifecycle-closure-formal-review | high | FAIL

Type: remediation prerequisite lifecycle review. Catalog closure
`2d29d5c980e9e80bc48391fd8596746361d913de` changes the expected five lifecycle
paths, toggles only P01.S11, and correctly leaves catalog P03.S19-P03.S23 and
remediation W01.P02.S05 open. Scoped Core checks are clean. The closure remains
blocked because its Step Record omits the original S11 implementation
`7d8c04df`, FAIL review `16066b83`, Core reopen `194f4fa6`, 49-test evidence,
nine expanded-suite deselections and explicit disposition of the original
legacy-restart/premature-closure HIGH findings under the superseding no-legacy
architecture. Reopen, complete that evidence chain, re-close through Core and
repeat lifecycle review before remediation consumes the prerequisite. This audit
update closes no remediation row.

### p01-s11-lifecycle-provenance-correction | high | resolved pending formal re-review

Type: remediation prerequisite traceability. Catalog P01.S11 was reopened and
its Step Record now includes original implementation `7d8c04df`, the 49-test
result, FAIL review `16066b83`, Core reopen `194f4fa6`, exact expanded count of
585 passed with nine deselected and eight classified environment failures, and
the complete later correction chain. It explicitly resolves the original legacy
restart gap through the approved no-legacy supersession and zero-contact refusal,
and the premature closure through reopen plus prior S10 completion. Core
re-closed only P01.S11. Remediation W01.P02.S05 remains open pending its own work
and may not consume this prerequisite until lifecycle re-review passes.

### p01-s11-lifecycle-provenance-final-formal-rereview | low | PASS

Type: remediation prerequisite lifecycle review. Correction
`b5841a766badf9b7dd8f7b887d943cbd5d0fa8ba` restores the complete catalog S11
implementation, review and Core reopen chain; the original 49-test evidence;
exact 585-pass, nine-deselection, eight-environment-failure count; and explicit
supersession/resolution of both historical closure HIGH findings. Only catalog
P01.S11 is re-closed. Catalog P03.S19-P03.S23 and remediation W01.P02.S05 remain
open, no runtime changes, and full Core is clean apart from plan status's known
S08 missing Step Record. The catalog prerequisite lifecycle review passes and
remediation may now consume the closed S11 input without closing S05 by inference.

### w01-p02-s05-er19-owner-verification | medium | corrected pending formal review

Type: dependency verification and host-relative catalog evidence. Closed owner
provider-model-catalog P01.S11 was verified against the live
`test_authenticated_route_serves_all_registered_lanes_in_order` production ASGI
route at A2A `c1da77cd`. The observed compact result was OpenAI `available`, 129
models, authenticated, revision and expiry present; Z.AI `unavailable`, zero
models, bounded reason present. For both providers catalog health equalled the
catalog state, exact-mode admission remained `not_admitted`, and `selectable`
remained false. Enumeration therefore did not inherit or create completed-turn
admission.

The exact route discriminator passed once in 3.34 seconds and the full route file
passed 11 tests in 6.03 seconds. The surrounding current selection/catalog set
passed 34 tests; current-lane plus zero-retired-authority guards passed 10. Ruff,
format and Ty passed for the route file. No runtime or test correction is needed,
no deprecated/legacy path was restored, and no new implementation finding was
surfaced. W01.P02.S05 remains open for formal review; downstream catalog
P03.S19-P03.S20 and remediation W05.P12.S57 retain assembled external/consumer
qualification ownership.

### w01-p02-s05-er19-evidence-formal-review | low | PASS

Type: formal evidence review disposition. Evidence-only commit `1daa2ea9e1b2d5aeb726c3f818fc689cee508ecd` has exact parent `c1da77cdcdaa16846be96c76fdaea2cb7206035d`, changes only the two owning audit documents, and passes `git diff --check`. The production ASGI route test keys the parsed response by provider identity, accepts only observed `available` or `unavailable` catalog state for OpenAI and Z.AI, requires catalog/health equality, and validates the corresponding closed payload shape. The v1 DTO bounds reason text, identifiers, entries, controls and provider collections. Both exact registered modes remain independently `not_admitted` and nonselectable regardless of discovery outcome; the current exact-mode inventory and zero-retired-authority guards pass, so no deprecated provider/profile/model authority is restored.

Independent review reran the exact discriminator (one pass), the complete route file (11 passes), and the current-lane plus zero-retired-authority guard set (10 passes); Ruff format/check and Ty pass for the route test. The recorded 34-pass surrounding catalog/selection result is consistent with the already reviewed and closed P01.S11 prerequisite. Full Core reports all 19 checks clean for `embedded-runtime-remediation`. No runtime or test correction is required and no new finding surfaced. S05 is review-passed but remains open for its separate Core lifecycle closure; downstream external and Dashboard qualification remains owned by W05.P12.S57.

### w01-p02-s05-core-lifecycle-closure | low | closed

Type: dependency-verification lifecycle. Formal PASS review
`3ed2ccdc0342f34e623cb507b914b68dba5f2f8c` independently reproduced the
host-relative route semantics, exact-mode non-admission, current-lane inventory,
zero-retired-authority guards and static evidence at implementation commit
`1daa2ea9e1b2d5aeb726c3f818fc689cee508ecd`. Core created the L3 Step Record and
closed only W01.P02.S05. S06-S08 remain open; downstream Dashboard/external
qualification remains W05.P12.S57. No runtime or test path changes in this
lifecycle closure. Mandatory closure-record review remains pending.

### w01-p02-s05-core-lifecycle-closure-formal-review | low | PASS

Type: lifecycle-record review disposition. Closure commit `b77cb4212754048a27c2b10a1f439e8e87728fb0` has exact parent `3ed2ccdc0342f34e623cb507b914b68dba5f2f8c` and changes exactly the five expected Core lifecycle paths: two owning audits, the new S05 Step Record, feature index and remediation plan. It closes only W01.P02.S05; S06-S08 remain open and Core identifies S06 as the next open Step. The Step Record accurately preserves the 11-test route-file, 34-test surrounding catalog/selection, 10-test current-lane/zero-retired and static evidence counts plus formal PASS review identity. The rolling audit binds that review to evidence commit `1daa2ea9e1b2d5aeb726c3f818fc689cee508ecd`.

No runtime or test path changed, index and audit lifecycle state agree with the plan, `git diff --check` passes, and all 19 feature Core checks report zero diagnostics with no missing execution records. No finding surfaced. S05 lifecycle closure passes; later external and Dashboard qualification remains open under W05.P12.S57.

### w01-p02-s06-isolated-rag-pinning-evidence | medium | closed

Type: test-environment isolation and real MCP behavior evidence. The S06 change
keeps the shipped registry surface unchanged while deriving an exact current
`vaultspec-rag[mcp]` requirement from this checkout's `uv.lock`. The live test
starts a real local-only service with owned status, data and Qdrant-storage
directories and an OS-selected loopback port, verifies the published version
and port, then launches the production `vaultspec-search-mcp` stdio entry point
from that same exact distribution. A non-workspace project pin outranks the
valid repository launch directory over the real MCP tool boundary. Cleanup is
bounded, uses the private service record as stop authority after partial start,
and never issues a stop for a merely reserved port.

The isolated discriminator passed in 46.46 seconds and the complete pinning
module passed 33 tests in 47.93 seconds. Ruff check, Ruff format and Ty pass for
the changed test; `git diff --check` passes. The shared service identity remained
PID 56028, port 8766 and package 0.4.23; service-token SHA-256
`6a1967743b274c05f778759a1c70141f8717d70308bea34beb69df994c9ded5a`
compared `changed=false`. No deprecated or legacy API, option,
translation, warning suppression or product registry pin was added. No new
implementation finding surfaced. The distinct cold provider-catalog/Uvicorn
shutdown observation was not exercised by this RAG test and remains open under
W01.P02.S07 diagnosis and W04.P10.S49 runtime ownership. W01.P02.S06 remains
open for formal implementation review.

### w01-p02-s06-shared-rag-token-disclosure | high | closed

Type: security and evidence handling. Commit `9d56e23e40e46e9cb754cfb3512365d96d524948` persists the live shared RAG service token verbatim in `.vault/audit/2026-08-02-provider-model-catalog-implementation-review-audit.md:220` and `.vault/audit/2026-09-05-embedded-runtime-remediation-implementation-review-audit.md:463,839`. The token is credential material, not a safe durable fingerprint. This blocks S06 closure even though the test did not stop or otherwise mutate the shared daemon. Remove the raw value from all current documents, retain only a one-way digest/equality result, and rotate the exposed token through the operator-owned RAG lifecycle before re-review. Do not rewrite historical commits or make the S06 test control the shared daemon.

### w01-p02-s06-private-service-cleanup-incomplete | medium | closed

Type: test resource lifecycle and degraded cleanup. `_run_rag_cli` at `src/vaultspec_a2a/providers/tests/test_harness_mcp_pinning.py:96-122` bounds a control subprocess and kills that subprocess on timeout. During context cleanup at lines 182-198, however, a timed-out or cancelled `server stop` can leave the already detached private service alive because no terminal owned-process fallback or post-stop absence check runs. The normal-path stop passed, but S06 explicitly owns bounded isolated cleanup and must remain review-blocked until cancellation/stop degradation cannot leak its daemon. Use the private service record's exact ownership identity for a bounded fallback, shield cleanup from caller cancellation within a total deadline, verify the owned process/port is gone, and add a discriminator that exercises cancellation or failed stop without touching any shared service.

### w01-p02-s06-isolated-rag-pinning-formal-review | high | FAIL

Type: formal implementation review disposition. The four-path commit has the intended test/audit scope and `git diff --check` passes. `uv.lock` selects exactly one RAG version and the helper applies that exact `vaultspec-rag[mcp]` requirement to both a private local-only service and the production-registry `vaultspec-search-mcp` stdio entry point. Status, data and Qdrant roots are test-owned; the published version and loopback port are checked before the MCP call. The real non-vacuous discriminator names the pinned non-workspace and excludes the valid launch workspace. Independent review reran it once (`1 passed` in 55.66 seconds), the entire module (`33 passed` in 62.88 seconds), Ruff format/check and Ty; all pass. Full remediation Core reports 19 clean checks. No legacy/deprecated product surface was added, ER20 alone is marked resolved pending review, and the separate cold catalog/Uvicorn finding remains open under S07/S49.

The plaintext shared credential is a HIGH security defect, and degraded cleanup is a MEDIUM resource-lifecycle defect in S06 itself. S06 does not pass formal review and must remain open pending both corrections and re-review.

### w01-p02-s06-review-corrections | high | closed

Type: security evidence and isolated process lifecycle. The raw shared-service
credential identified by formal FAIL review `14ae6ddf` was removed from all
three current durable locations; a full repository scan finds no remaining
occurrence. Audit evidence now uses only SHA-256 digests and explicit comparison
results. The operator lifecycle rotated digest
`6a1967743b274c05f778759a1c70141f8717d70308bea34beb69df994c9ded5a`
to `ef678ba14829aacf0285d936238812284235a2a7cf7ff3899f8fab3e1ecb45dd`
(`changed=true`). After all corrected S06 tests, the shared service was healthy
at PID 58992, port 8766, version 0.4.23 with the post-rotation digest unchanged
(`changed=false`). The test never controls that shared lifecycle.

Private cleanup now retains the exact `psutil.Process` identity obtained from
the private service record, validates its private health identity without
rendering the credential, shields cleanup from caller cancellation, gives the
normal service stop ten seconds inside a thirty-second total cleanup deadline,
and falls back to terminating only the retained private process tree. Completion
requires both that exact process identity and its loopback listener to be absent.
A real discriminator starts the private service, removes executable lookup only
after readiness so the actual stop-control launch fails, cancels the owner task,
and proves fallback use, process absence, port closure and unchanged shared
digest. On the final exact source, the complete module passed 34 tests in
112.39 seconds: the real project-pin case took 66.37 seconds and the
cancellation/failed-stop case took 43.88 seconds. No mock, monkeypatch, fake transport, deprecated/legacy surface
or warning suppression was added. S06 remains open for formal re-review.

### w01-p02-s06-start-timeout-reap-unbounded | medium | closed

Type: test readiness and subprocess lifecycle. Correction `f7a9b14d349a8ac9c815d7e7b1296f2edd62d65a` bounds `process.communicate()` initially, but its timeout branch at `src/vaultspec_a2a/providers/tests/test_harness_mcp_pinning.py:138-142` kills only the direct `uvx` control process and then awaits a second `process.communicate()` without a deadline. A spawned child retaining the inherited output handles, or a kill/reap failure, can therefore hold initial service start beyond the declared 120-second readiness budget. The thirty-second cleanup envelope bounds stop calls only after an owner is discovered; it does not bound this pre-yield start path. S06 owns bounded readiness and remains review-blocked. Put launch, timeout termination, output drain and late-record discovery inside one total deadline; terminate the exact spawned control tree when required; cap captured output; and add a real-process timeout discriminator proving terminal return plus cleanup of any late-published owned service without touching the shared daemon.

### w01-p02-s06-isolated-rag-pinning-correction-formal-review | medium | FAIL

Type: formal correction review disposition. The correction changes the same four intended paths and resolves both earlier findings. The disclosed credential is absent from the full current tree; current audit prose retains only one-way SHA-256 comparisons. Operator-owned rotation is recorded without the new credential, and the S06 code has no shared-service control or network path. Private cleanup retains a non-rendering exact process/token identity, verifies the private endpoint, shields cleanup from caller cancellation within a thirty-second deadline, tries the exact-version CLI stop, falls back only to the retained process tree, refuses a changed listener identity, performs bounded late-record discovery and requires both process and listener absence. The new real discriminator makes stop-process creation fail by removing executable lookup only after the private daemon is ready, cancels the owning task, and proves fallback, process absence and port closure. Independent re-review passed that case once in 51.22 seconds; the recorded exact module result is 34 passes, including both live cases. Ruff format/check, Ty, `git diff --check` and all 19 remediation Core checks pass. No legacy/deprecated surface was added. ER20 alone remains corrected pending review, while the cold catalog/Uvicorn finding stays open under S07/S49.

The initial-start timeout branch remains outside a total reap deadline, so bounded readiness is not yet proved. S06 does not pass and remains open for correction and re-review.

### w01-p02-s06-readiness-envelope-correction | medium | closed

Type: test readiness and subprocess lifecycle. Formal review `02edd63c` found
that the initial CLI timeout killed only `uvx` and then awaited pipe drainage
without a remaining deadline. The correction sends stdout and stderr to owned
temporary files, caps each decoded stream at 64 KiB, and assigns launch, process
wait, exact control-tree kill, wait/reap and output read one total deadline.
Service startup reserves part of its readiness budget for late atomic
service-record discovery; an observed detached service then enters the already
shielded, thirty-second owned cleanup path. A published record whose exact PID
was already felled by control-tree cleanup is accepted only after the private
listener is also absent.

The new real-process discriminator writes a filesystem wrapper that launches
the exact locked `uvx --from vaultspec-rag[mcp]==0.4.23 vaultspec-rag server
start` command, waits until that real service publishes its private record, and
then deliberately holds the control handles. The marker proves the timeout is
post-publication and non-vacuous. The control envelope returns, late discovery
binds cleanup to the private record, and assertions prove the exact private
process and loopback port absent while the shared digest remains unchanged. It
passed independently in 52.22 seconds. The final exact-source module passed 35
tests in 143.04 seconds: timeout 49.77 seconds, real pin 48.78 seconds, and
cancellation/failed-stop 43.18 seconds. Ruff, format, Ty, diff and feature Core
checks remain required before commit. No product hook, compatibility path,
deprecated/legacy behavior, fake transport, monkeypatch or warning suppression
was added. S06 remains open for formal re-review.

### w01-p02-s06-readiness-cleanup-deadline-split | medium | closed

Type: test readiness and owned-service lifecycle. Correction `1d3f99e9afcb2a8265882a9fdaee97bd004fb90e` makes the CLI control subprocess itself bounded, but `_isolated_rag_service` still composes two independent budgets. It sets `readiness_deadline = start + start_timeout_seconds` at `src/vaultspec_a2a/providers/tests/test_harness_mcp_pinning.py:409`, may spend that budget on launch/reap plus late-record discovery, and only afterward enters `_cleanup_private_rag_service`'s separate thirty-second timeout at line 282. The new proof exposes this split at line 1010 by accepting a sixty-second readiness request when the combined operation returns in anything under ninety seconds. This does not satisfy S06's required one total launch, termination, output-drain, late-record and owned-cleanup deadline.

S06 remains review-blocked. Establish one absolute deadline before control launch and pass its remaining budget through control-tree reap, late-record discovery, CLI stop/fallback and process/port absence proof. Reserve cleanup inside that same deadline and make the discriminator require terminal return within the requested sixty seconds, including a degraded late-service cleanup path. Preserve exact-identity refusal and shared-service isolation.

### w01-p02-s06-readiness-correction-formal-rereview | medium | FAIL

Type: formal correction review disposition. The four-path correction resolves the earlier unbounded pipe wait: stdout/stderr use owned files, decoded reads cap each stream at 64 KiB, and the CLI wrapper plus exact observed descendants are killed and reaped inside the control deadline without `communicate()` or pipe-EOF waits. Its real wrapper launches the exact locked RAG service, observes the private record before holding handles, times out non-vacuously, discovers the detached service and proves process/listener absence. Independent review reran that case (`1 passed` in 51.58 seconds). The recorded module result is 35 passes across all three live cases. Raw credential material is absent from the current tree, only one-way comparisons remain, operator-owned rotation evidence is non-secret, and the prior cancellation/failed-stop cleanup remains intact. Ruff format/check, Ty, diff and all 19 remediation Core checks pass. ER20-only scope and the separate S07/S49 cold-catalog/Uvicorn ownership remain intact; no legacy/deprecated behavior was added.

The remaining split deadline is a MEDIUM defect in S06's explicit bounded-readiness success shape. S06 does not pass formal review and remains open for correction and re-review.

### w01-p02-s06-single-absolute-deadline | medium | closed

Type: test readiness and owned-service lifecycle. Formal review `1322d4ef`
confirmed the previous correction still added a relative cleanup budget after
readiness. The context now mints one absolute deadline before control launch.
It reserves five seconds for late record discovery and fifteen seconds for
owned cleanup before giving time to readiness. The same absolute timestamp is
passed through the bounded CLI stop, exact process-tree fallback and final
process/listener absence poll; no phase resets or extends it. The real degraded
wrapper test requests sixty seconds and asserts the complete launch, control
timeout/reap, late-record binding and owned cleanup return in less than sixty.
It passed independently in 39.69 seconds and at 35.52 seconds inside the final
module run. The full module passed 35 tests in 161.51 seconds; the real pin case
took 80.75 seconds and cancellation/failed-stop took 43.58 seconds.

### w01-p02-s06-terminal-pid-signal-race | medium | closed

Type: test subprocess lifecycle and cleanup race. The first combined run of the
single-deadline correction surfaced an exact child exiting between
`psutil.Process.is_running()` and `kill()`, which raised `NoSuchProcess` and
failed the timeout proof despite the process already being terminal. The
correction retains the exact captured process identities and accepts only
`psutil.NoSuchProcess` or the asyncio process handle's `ProcessLookupError` as a
successful terminal signal race. Every other signal/reap error remains visible.
The focused and complete reruns above pass with private process and port absence
and unchanged shared digest. No new product, deprecated/legacy, compatibility,
mock, monkeypatch, fake transport or warning-suppression path was added. S06
remains open for formal re-review.

### w01-p02-s06-stop-timeout-consumes-fallback-budget | medium | closed

Type: degraded cleanup and deadline partition. Correction `785029d5e81e512958d561e68f4493fece6735f2` now mints one operation deadline, but `_cleanup_private_rag_service` passes that final deadline unchanged to `_run_rag_cli` for the normal stop attempt at `src/vaultspec_a2a/providers/tests/test_harness_mcp_pinning.py:296-311`. When an absolute deadline is present, `_run_rag_cli` derives its wait and reap reservations from the full remaining interval and does not apply `timeout_seconds` as an earlier stop-attempt boundary. A stop command that launches successfully and hangs can therefore spend the remaining cleanup interval on its own wait and control-tree reap; the catch at lines 314-315 then has no time left for the exact owned-daemon fallback or process/port absence proof. The existing degraded cleanup test forces stop-process creation to fail immediately, so it does not discriminate this path.

S06 remains review-blocked. Reserve an earlier absolute stop-control deadline inside the single operation deadline, leaving explicit time for exact owned-daemon termination and absence checks. Pass only that earlier deadline to `_run_rag_cli`, keep the final operation deadline on fallback/verification, and add a real-process discriminator whose stop command starts, holds, and times out while the retained daemon is still reaped and process/port absence is proved before the original requested deadline.

### w01-p02-s06-single-deadline-correction-formal-rereview | medium | FAIL

Type: formal correction review disposition. The correction changes the same four intended paths and resolves the prior split envelope: one monotonic operation deadline is minted before launch; control reap, capped file output, late-record discovery and cleanup receive deadlines derived from it; the real degraded-start proof now requires completion inside its requested sixty seconds and independently passed in 36.85 seconds. Terminal PID races catch only `psutil.NoSuchProcess` or `ProcessLookupError`; exact retained process identity, changed-listener refusal and process/port absence remain required. The prior credential redaction and operator-owned rotation evidence, read-only shared fingerprint comparison, cancellation cleanup, exact locked RAG version, ER20-only scope, S07/S49 cold-catalog ownership and zero legacy/deprecated surface remain intact. The recorded module result is 35 passes, and Ruff format/check, Ty, diff and all 19 remediation Core checks pass.

The normal stop-timeout path still consumes the fallback reservation, so CLI stop, fallback and verified absence are not all guaranteed inside the one deadline. S06 does not pass formal review and remains open for correction and re-review.

### w01-p02-s06-stop-slice-preserves-fallback-budget | medium | closed

Type: degraded cleanup and deadline partition. Formal review `47f541201bb601aa8f20b1668f8e8c21c87c70b3` found that the normal exact-version stop control received the final operation deadline and could consume the time required for retained-owner fallback and absence proof. The cleanup now derives an earlier stop-control deadline and reserves eight seconds inside the original absolute operation deadline for exact-owner process-tree termination and process/listener absence verification. No phase resets or extends the original bound.

A deterministic filesystem wrapper successfully creates the exact locked `uvx --from vaultspec-rag[mcp]==0.4.23 vaultspec-rag server stop` child with its real arguments, records the child PID and command, suspends it, and holds the control process. The stop slice expires while the private daemon remains owned; cleanup records fallback use and proves the retained process and private port absent before the explicit 120-second total deadline. The focused proof passed in 53.24 seconds with a 51.57-second test body. After the final exact-command assertions, the authoritative exact-source module passed 36 tests in 215.98 seconds; the same case took 63.65 seconds. The shared-service digest remained unchanged. No product fault hook, mock, monkeypatch, compatibility path, deprecated/legacy behavior, or warning suppression was added. S06 remains open for formal re-review.

### w01-p02-s06-nonzero-control-exit-exception-mismatch | medium | closed

Type: test subprocess lifecycle and error contract. The first hung-stop discriminator surfaced that `_run_rag_cli` represented a real nonzero control-process exit with `AssertionError`, while degraded cleanup accepts the helper's operational `RuntimeError` contract. That mismatch could bypass retained-owner fallback after a launched stop control failed normally. The helper now raises bounded `RuntimeError` with capped captured output for every nonzero exit; start failures still propagate, while cleanup can execute its exact-owner fallback. The focused and complete reruns above prove terminal cleanup. The failed exploratory run also exposed a Windows wrapper constant mistake before the exact suspended child was created; the wrapper now uses the documented Windows creation flag value and the passing test asserts the recorded exact command and PID.

### w01-p02-s06-fallback-budget-final-formal-rereview | low | PASS

Type: formal correction review disposition. Correction `79c01caa9b8e7330778a8c6f698b16dcf081617d` resolves the remaining stop-timeout budget finding inside the existing single operation deadline. Cleanup derives an earlier stop-control absolute subdeadline from the final operation deadline and leaves at least eight seconds for exact retained-owner process-tree termination plus process/listener absence verification. No phase resets the clock. Nonzero control exit now raises typed `RuntimeError` carrying at most the already capped output, so degraded cleanup reaches fallback; only terminal `psutil.NoSuchProcess` and `ProcessLookupError` races are accepted while all other identity/control failures remain visible.

The real filesystem wrapper launches the exact locked `uvx --from vaultspec-rag[mcp]==0.4.23 vaultspec-rag server stop --port <private> --json` child, records its PID and argv, suspends it, and holds the parent until the earlier stop slice expires. It asserts the private port differs from the recorded shared port, then proves fallback use, exact private process absence, listener closure and unchanged shared digest inside the original 120-second deadline. Independent review reran the focused case (`1 passed` in 52.96 seconds; 51.59-second body); the recorded final module result is 36 passes. Ruff format/check, Ty, diff, secret scans and all 19 remediation Core checks pass.

All prior S06 credential redaction/rotation, shared-service isolation, cancellation cleanup, bounded start/output/late-record behavior and ER20-only ownership remain intact. The distinct cold catalog/Uvicorn finding remains S07/S49, and no compatibility, legacy or deprecated surface was added. No finding remains. S06 is review-passed and ready for separate Core lifecycle closure; this review leaves it open.

### w01-p02-s06-core-lifecycle-closure | low | closed

Type: dependency-verification lifecycle. Formal PASS review `613d23e2b5e73eaa948cc49c745743d328c074ea` independently accepted the exact locked client/service pinning boundary, private service isolation, credential redaction and rotation evidence, single absolute launch/readiness/cleanup deadline, exact-owner fallback, terminal PID-race handling and typed nonzero control failures. The authoritative exact-source module passed 36 tests in 215.98 seconds, including the real suspended exact stop command in 63.65 seconds inside its explicit 120-second total deadline. Ruff, format, Ty, diff, secret scans and both feature Core checks passed; the shared service remained healthy with its rotated digest unchanged.

Core closed only `W01.P02.S06`. Every historical FAIL and PASS review remains above. ER20 and all S06-owned correction findings are closed. The distinct cold provider-catalog/Uvicorn shutdown finding remains open under `W01.P02.S07` and `W04.P10.S49`; S07 is the next open remediation step.

### w01-p02-s06-core-lifecycle-closure-formal-review | low | PASS

Type: lifecycle-record review disposition. Closure commit `b4700b752fb87e1b00bdc2cbdd4c588e0e0c2ae7` has exact parent `613d23e2b5e73eaa948cc49c745743d328c074ea` and changes exactly six Core-managed Vault paths: the three owning audits, new S06 Step Record, remediation index and remediation plan. It closes only `W01.P02.S06`; Core reports six of 81 Steps complete, no missing execution records and `W01.P02.S07` next. No runtime or test path changed.

The Step Record retains the complete `9d56e23e` through `613d23e2` implementation/FAIL-correction/PASS chain, the authoritative 36-test module result, all four real-process discriminators, exact 120-second hung-stop evidence, static/diff/secret scans, rotated shared-fingerprint stability and final formal review identity. The linked PASS review supplies the clean 19-check remediation Core result, and both remediation and provider-model-catalog feature checks independently return zero diagnostics at closure. Historical FAIL/PASS entries remain in place; only their current finding statuses move to closed. ER20 is closed, while the distinct cold catalog/Uvicorn finding remains open under S07/S49.

Current-tree scans find no disclosed raw credential or restored legacy/deprecated claim. Index, audits, Step Record and plan agree. No finding surfaced; the S06 lifecycle closure passes mandatory review.

### w01-p02-s07-compile-loop-gap-diagnosis | medium | closed

Type: performance evidence and measurement integrity. S07 retains ER21's original failed 25.312691-second compile with a 0.6182457-second maximum loop gap and the unchanged M15 success. Current source still offloads the cold model stack before provider construction. Fresh controls on the named Windows/Ryzen host measured a 3.5688-second on-loop gap, 0.0851-second offloaded gap and 0.0552-second production compile gap. The new gate drives five fresh production compile subprocesses under five owned CPU-bound processes, matching frozen execution capacity `C=5`, while an idle event-loop control under the same load terminally refuses an inconclusive scheduler-starved sample. Final idle gap was 0.0191561 seconds; compile gaps were 0.0464355-0.0816821 seconds; every load owner accrued 43.34-48.55 CPU seconds. The 0.5-second ceiling is unchanged. The warmup module passed 4 tests in 66.85 seconds and requires no production correction.

### w01-p02-s07-venv-load-owner-redirector | medium | resolved

Type: measurement-harness process ownership. The first new load run reported 3 passed and 1 failed before compile sampling because every Windows venv `python.exe` handle referred to an idle redirector while its child performed the CPU work. The gate correctly refused zero measured CPU rather than treating it as representative load. S07 now launches the current base interpreter directly, retains those exact process handles, requires CPU accrual before and across all trials, and terminates/waits or kills each in `finally`. The focused loaded gate passed in 55.82 seconds; a post-failure process scan found zero matching owned burners.

### p01-s11-cold-catalog-shutdown-timeout-s07-reassessment | medium | open under W04.P10.S49

Type: provider degradation and gateway lifecycle. S07 reran the exact production restart/catalog case six fresh times: one 21.42-second pass, then five passes at 17.10-19.03 pytest seconds (20.56-23.61 wall seconds). The authoritative final exact-source combined gate passed five tests in 89.00 seconds, with the loaded compile case at 52.90 seconds and the restart case at 16.65 seconds. No shutdown timeout reproduced. The historical 91.79-second observation included a real Claude discovery timeout; current catalog discovery is independently bounded and shielded, while process-tree/graceful shutdown remains owned by `W04.P10.S49`. No evidence couples it to model warmup, so S07 records diagnosis only and does not close or reassign the lifecycle finding.

No runtime authority, provider surface, compatibility path, deprecated option or threshold changed. S07 remains open for formal review.

### w01-p02-s07-load-cleanup-terminal-race | low | resolved

Type: measurement-harness resource cleanup. Final review of the owned CPU-load helper found a process could exit between `poll()` and `terminate()`. Cleanup now accepts only terminal `ProcessLookupError`, still waits each exact process and escalates its same handle on timeout, and the test asserts every retained `psutil.Process` identity is absent after the load context. The authoritative combined run passes and an independent command-line scan reports zero matching burner processes.

### w01-p02-s07-compile-window-includes-teardown | medium | closed

Type: performance measurement integrity. In `src/vaultspec_a2a/providers/tests/probe_loop_responsiveness.py:59-116`, `_run_compile` captures `compile_seconds` immediately after `get_or_compile_graph`, but then awaits `bridge.close()` and exits the checkpointer context before returning while the shared heartbeat continues until `_measure` stops it at lines 149-150. The asserted `max_loop_gap_seconds` therefore covers graph compilation plus bridge/checkpointer teardown, while `work_seconds` covers compilation alone. Independent formal review reproduced the named `C=5` gate and one trial reported `work_seconds=2.3452` with `max_loop_gap_seconds=11.0947`; a loop gap almost nine seconds longer than the measured work proves the two fields do not describe the same interval. This invalidates the five-trial compile-only conclusion and blocks S07 evidence closure.

Freeze or pause the heartbeat at the exact compile completion boundary and return that bounded sample independently from teardown. Keep bridge/checkpointer cleanup terminal and separately measured. Re-run the idle calibration and five non-vacuous current production compiles under the fixed 0.5-second ceiling on the named load, preserving the failed observation.

### w01-p02-s07-post-compile-teardown-stall | medium | open under W04.P10.S49

Type: resource lifecycle and performance diagnosis. The same independent run observed an 11.0947-second event-loop gap after the 2.3452-second compile measurement but before the probe returned. The current probe cannot attribute that interval between `WorkerBridge.close()`, checkpointer exit and ambient scheduling, so it is not evidence that graph compilation regressed or that bridge close alone blocked. Instrument the two teardown phases separately with the same idle/load calibration, preserve exact timing and cleanup evidence, and route any confirmed production lifecycle defect to its owning worker/checkpoint or S49 lifecycle path. Do not suppress the observation by stopping measurement without retaining a separate teardown result.

### w01-p02-s07-compile-loop-diagnosis-formal-review | medium | FAIL

Type: formal implementation review disposition. Commit `76cb91e54c42b6b9881b16e97dbcb47d354ce50e` has the intended five-path test/research/audit scope and no production change. RAG-first semantic lookup reached `worker/graph_lifecycle.py`; its limited code corpus warning was retained, followed by whole-source inspection and exact-symbol confirmation that current `_compile_graph` still awaits `asyncio.to_thread(warm_model_imports)` before provider construction. The new Windows base-interpreter owners are non-vacuous: the independent gate reached the compile assertion only after all five owners accrued CPU, remained active across trials, were reaped, and the idle scheduler control stayed below 0.5 seconds. A post-failure scan found zero burner processes. The original 25.312691-second/0.6182457-second failure and M15 pass remain historical evidence, and the threshold is unchanged.

The exact cold catalog/current-schema restart case independently passed once in 24.50 seconds, supporting the documented absence of warmup coupling while leaving its separate S49 ownership open. Ruff format/check, Ty, diff and all 19 remediation Core checks pass; no legacy/deprecated surface was added. The recorded six cold-catalog passes and original load results remain evidence, but the independent named-load run failed with gaps `0.0620, 11.0947, 0.0572, 0.0569, 0.0666` seconds (`1 failed` in 76.51 seconds). The contaminated timing window and separately unclassified teardown stall are MEDIUM findings. S07 does not pass and remains open for correction and re-review.

### w01-p02-s07-exact-phase-boundary-correction | medium | closed

Type: performance measurement integrity. Correction after formal FAIL `691f62cc60260e30a82ef5c8c1682276bbe8aba7` makes the heartbeat's last-tick timestamp shared state and freezes each maximum gap synchronously at the same monotonic timestamp that ends its reported duration. The compile result therefore ends before cleanup starts. `WorkerBridge.close()`, checkpointer exit and a post-cleanup ambient scheduler interval each receive their own reset duration/gap window. A real unloaded probe reported compile 2.5533 seconds / 0.0417-second gap, bridge close 3.4184 / 0.0268, checkpointer exit 0.0014 / 0.0014 and ambient scheduler 0.1021 / 0.0157.

The first corrected `C=5` five-trial run intentionally kept the teardown ceiling assertion and failed with 4 passed / 1 failed in 144.76 seconds. All exact compile windows passed the unchanged 0.5-second ceiling at 0.0546-0.1796 seconds. Trial four conclusively located the separate stall: bridge close took 7.1849 seconds and produced a 3.6920-second loop gap, while checkpointer exit stayed at 0.0012-0.0032 seconds and ambient scheduler at 0.0156-0.0175 seconds. This preserves and explains the earlier contaminated 11.0947-second observation without claiming equivalence between the two samples.

### w04-p10-s49-worker-bridge-close-loop-stall | medium | open under W04.P10.S49

Type: production resource lifecycle and serving responsiveness. Under five proven CPU-bound owners, the real `WorkerBridge.close()` path retried its buffered event against the intentionally unreachable gateway. One of five correction trials blocked the event loop for 3.6920 seconds during 7.1849 seconds of bridge close; the other bridge gaps were 0.0272-0.0769 seconds. The retry path is non-vacuous, and the exact phase windows exclude graph compile, checkpointer exit and ambient scheduling as the owner in that sample. S07 neither suppresses nor marks this teardown threshold green. The stable S07 regression asserts only the owning compile window's fixed 0.5-second contract while retaining teardown duration/gap fields and an independently exercised retry discriminator. Runtime lifecycle diagnosis and correction remain open under `W04.P10.S49`.

After this ownership split, the exact warmup module passed 5 tests in 139.74 seconds. The current-schema production restart/catalog test separately passed in 51.63 seconds (50.79-second call) without shutdown failure. Ruff, format, Ty and diff checks pass. Both remediation and robustness Core checks complete all 19 checks; their only initial diagnostics were final-newline hygiene warnings corrected through Core. The current-only source scan finds no retired or deprecated token, and the owned-load process scan is empty. S07 stays open for formal re-review.

### w01-p02-s07-phase-boundary-correction-formal-rereview | low | PASS

Type: formal correction review disposition. Correction `82c8e5181453e2c3a6f7712c2f9d8a6048342876` has exact parent `691f62cc60260e30a82ef5c8c1682276bbe8aba7` and changes the same five S07 test, research and audit paths as the original evidence pass. The heartbeat now resets each phase at an exact monotonic boundary and freezes its maximum gap synchronously at the identical endpoint used for duration. Compile, `WorkerBridge.close()`, checkpointer exit and ambient scheduling therefore have independent, internally consistent windows. The stable discriminator requires every reported teardown gap to fall within its own duration and proves the unreachable-gateway bridge retry is non-vacuous, while the five-owner load gate applies the unchanged 0.5-second ceiling only to S07-owned compile windows.

The historical 25.312691-second/0.6182457-second ER21 failure, the formal-review contaminated 2.3452-second/11.0947-second sample, and the correction's first intentionally failing diagnostic remain preserved. That diagnostic measured all five compile gaps at 0.0546-0.1796 seconds, bridge close at 7.1849 seconds with a 3.6920-second gap, checkpointer exit at no more than 0.0032 seconds and ambient scheduling at no more than 0.0175 seconds. The distinct bridge lifecycle finding remains MEDIUM and open under `W04.P10.S49`; there is no xfail, suppression or lifecycle-pass claim in S07.

Independent re-review passed the full warmup module, 5 tests in 113.80 seconds, and the current-schema restart/catalog discriminator, 1 test in 42.34 seconds. Ruff format/check, Ty and diff checks pass. Both remediation and robustness Core checks report all 19 checks clean; the current-only scan finds no retired/deprecated surface and the owned-load process scan is empty. No new finding surfaced. S07 is review-passed and ready for separate lifecycle closure; this review leaves it open.

### w01-p02-s07-lifecycle-closure | low | closed pending closure-record review

Type: lifecycle traceability. Formal PASS `6c742790f42b21d433c371ed6db738c866d0fcd7` accepted correction `82c8e5181453e2c3a6f7712c2f9d8a6048342876` after original implementation `76cb91e54c42b6b9881b16e97dbcb47d354ce50e` and formal FAIL `691f62cc60260e30a82ef5c8c1682276bbe8aba7`. The S07 Step Record retains original ER21 25.312691-second work / 0.6182457-second gap / 1557 ticks, unchanged M15 success, corrected non-vacuous `C=5` compile gaps 0.0546-0.1796 seconds, independent 5-test and restart checks, static/Core/current-only scans, and the exact review chain.

Vaultspec Core closed only `W01.P02.S07`; plan status is 7 of 81 Steps complete and `W01.P02.S08` is next. ER21's compile diagnosis is closed. The phase-isolated 7.1849-second `WorkerBridge.close()` / 3.6920-second loop stall and the distinct cold provider-catalog/Uvicorn lifecycle issue both remain MEDIUM and open under `W04.P10.S49`. All historical failures and reviews remain in the audit. No runtime source changed during lifecycle closure.

### w01-p02-s07-core-lifecycle-closure-formal-review | low | PASS

Type: lifecycle-record review disposition. Closure commit `566b58a6b2127e90fa888b640621fa9ae24632ee` has exact parent `6c742790f42b21d433c371ed6db738c866d0fcd7` and changes exactly five Core-managed Vault paths: the two owning audits, new S07 Step Record, remediation index and remediation plan. The only plan-row transition is `W01.P02.S07`; Core reports 7 of 81 Steps complete, no missing execution records and `W01.P02.S08` next. No runtime or test path changed.

The Step Record preserves the complete `76cb91e5` implementation -> `691f62cc` formal FAIL -> `82c8e518` correction -> `6c742790` formal PASS chain and the authoritative evidence: original ER21 25.312691-second work / 0.6182457-second gap / 1557 ticks, unchanged M15 success, corrected non-vacuous `C=5` compile gaps 0.0546-0.1796 seconds, independent 5-test warmup and one-test current-schema restart checks, static checks, both 19-check Core gates, retired/deprecated scan and empty owned-process scan. The historical 2.3452-second work / 11.0947-second contaminated gap and the correction's intentionally failing diagnostic remain in the audit trail.

ER21 and its S07-owned compile-window measurement findings are closed. The phase-isolated 7.1849-second `WorkerBridge.close()` / 3.6920-second loop stall and the separate cold provider-catalog/Uvicorn lifecycle finding remain MEDIUM and open under `W04.P10.S49`; neither audit nor Step Record claims teardown closure. Current Core checks for remediation and robustness are clean, source-support history is unchanged, and no legacy/deprecated product claim was introduced. No new finding surfaced; the S07 lifecycle closure passes mandatory review.

### w01-p02-s08-starlette-blocking-portal-deprecation | low | closed

Type: upstream dependency maintenance. Baseline AnyIO 4.15.1 / Starlette 1.6.0 fails `import starlette.testclient` under `-W error::DeprecationWarning` at installed line 53 because Starlette evaluates `anyio.abc.BlockingPortal`. PyPI has no newer release. S08 adds an exact uv source for official merged commit `bbee894422c6cc1306327335ae385b901ccfec13` and regenerates `uv.lock`; the graph remains 211 packages and source metadata remains version 1.6.0. After locked sync, the warning-as-error import and real TestClient GET pass, the old access scan is empty, and exactly three canonical `anyio.from_thread.BlockingPortal` accesses remain. There is no warning filter, AnyIO downgrade, local patch, compatibility shim or old runtime option.

### w01-p02-s08-unreleased-starlette-tree-delta | medium | mitigated pending official release

Type: dependency provenance and regression surface. Official PR 3498 changes only three TestClient annotations, but its merge commit tree is 27 commits / 54 files / 2,586 additions / 357 deletions beyond Starlette tag 1.6.0. The immutable official source is the only immediate current fix because no released artifact contains the correction, but it widens S08 beyond a three-line package delta. The exact 12-module TestClient consumer run under deprecations-as-errors completed 197 passes and two failures. A representative worker/control/internal-auth set passed 28 tests. The failures were differentially reproduced against registry 1.6.0, so neither is caused by the pin. Formal PASS `333080e4a351b9450158c8b8375d9beb301a98a1` accepts that regression evidence for the supported embedded-binary lane. The MEDIUM dependency-provenance risk remains open until an official Starlette release replaces the source pin.

### w01-p02-s08-wheel-source-boundary | low | bounded by embedded-binary product contract

Type: packaging and distribution boundary. `tool.uv.sources` governs this repository's uv-managed frozen build but is not emitted into wheel `Requires-Dist`. An independently pip-resolved wheel would still select released Starlette 1.6.0 and encounter the warning. The remediation ADR defines this component as a Dashboard-embedded binary rather than a standalone wheel product. `uv export --locked` emits the immutable Git source, and `uv run --locked --group freeze` imports TestClient without warning while installed `direct_url.json` binds requested revision and commit ID to `bbee8944`; `scripts/build_binary.py` invokes PyInstaller through that same interpreter. S08 adds no compatibility support for an independent wheel lane.

### s08-team-status-node-summary-baseline-failure | medium | open under W05.P13.S67

Type: current-source test/state projection drift. `TestTeamStatus.test_node_summaries_surface_as_agents` expected one agent and received an empty list. It failed in the 12-module pinned run and individually. A controlled reinstall of registry Starlette 1.6.0 reproduced the same failure, proving it is not introduced by S08. Owner `W05.P13.S67` must reconcile the status projection/fixture before loaded status qualification; S08 does not relax or edit the test.

### s08-plan-approval-response-baseline-failure | medium | open under W02.P03.S78/W02.P03.S13

Type: current-source durable permission test drift. `TestInternalEvents.test_plan_approval_relay_creates_durable_permission_and_can_be_responded` expected HTTP 200 and received typed 409. It failed in the 12-module pinned run and individually, then reproduced unchanged against registry Starlette 1.6.0. The durable action-receipt and settlement owners `W02.P03.S78` and `W02.P03.S13` must reconcile the fixture with current permission ownership; S08 preserves both the typed response and the failing assertion.

The exact current lock, warnings-as-errors import/GET, installed-source scan, frozen-build interpreter proof and 28-test representative set pass. The broad result is 197 passed / 2 pre-existing failures in 195.99 seconds. Final dependency, static and Core results are recorded below. S08 stays open for formal review.
### s08-shared-environment-incomplete-distribution-metadata | low | resolved

Type: evidence-environment integrity. The locked sync exposed incomplete pre-existing `.venv` records for `watchfiles 1.2.0` and `zstandard 0.25.0`: `uv pip check` could not find their installed `METADATA`, and the distributions lacked uninstall records. S08 reinstalled those exact locked current versions into the same environment, without changing either dependency constraint or lock resolution. `uv pip check` then reported all 188 installed packages compatible, and the exact Starlette warnings-as-errors discriminator remained green. This is resolved environment repair evidence rather than a dependency-policy change.

### s08-whole-tree-ty-provider-model-test-diagnostics | low | open under W06.P14.S72

Type: repository static-check baseline. Whole-tree `uv run ty check` reports five diagnostics, all in unchanged provider-model test code: three object subscript/assignment diagnostics in `ipc/tests/test_model_assignment_schema.py`, one missing required `model` argument in `providers/tests/test_codex_chat_model.py`, and one object key-type diagnostic in `providers/tests/test_team_selection.py`. S08 changes dependency metadata and Vault evidence only, so these findings are outside its implementation surface. Final repository-check reconciliation remains owned by `W06.P14.S72`; S08 neither suppresses nor claims a clean whole-tree type gate.
### w01-p02-s08-final-implementation-gates | low | closed

Type: implementation evidence disposition. `uv lock --check` retains the 211-package exact graph; `uv pip check` reports all 188 installed packages compatible. The warnings-as-errors real TestClient request passes, and the installed-source discriminator reports three canonical accesses and zero old-alias accesses. `deptry src`, `ruff check src`, and `git diff --check` pass. The representative TestClient suite remains 28 passed; the broad result remains 197 passed and two differentially proven pre-existing failures. Whole-tree Ty retains the five separately queued unchanged-test diagnostics and is not reported as green. Both embedded-runtime-remediation and embedded-runtime-robustness Core feature checks complete all 19 checks with zero diagnostics after Core markdown and feature-index maintenance. S08 changes no application runtime or test source, keeps the no-legacy/no-deprecated contract, passed formal review, and is lifecycle-closed.

### w01-p02-s08-starlette-source-pin-formal-review | low | PASS

Type: formal dependency-correction review disposition. Commit `17095d27ca7e8727ec205155a7a209de5b58d0b5` has exact parent `45599dac9b4b3eddf32e0a7275b52af5d8ff6799`, changes exactly seven dependency/Vault paths, and passes `git diff --check`. Official PyPI provenance confirms Starlette 1.6.0 is the latest release and binds it to tag commit `4f250d6b814587e20c5365f0a5f0c4d42bcb929f`; the official upstream comparison confirms immutable merged correction `bbee894422c6cc1306327335ae385b901ccfec13`, its exact three `BlockingPortal` access corrections, and the documented 27-commit / 54-file / 2,586-addition / 357-deletion tree expansion. The reference accurately preserves that material MEDIUM interim dependency risk rather than describing the pin as a three-line package delta.

`tool.uv.sources`, the regenerated lock, locked export and installed `direct_url.json` all bind Starlette to the same requested revision and commit. `uv lock --check` retains 211 resolved packages; `uv pip check` reports all 188 installed distributions compatible. FastAPI 0.141.1 requires Starlette >=0.46.0 and Starlette 1.6.0 requires AnyIO >=3.6.2,<5, so AnyIO 4.15.1 remains within declared bounds. The release workflow synchronizes the locked freeze group and invokes `scripts/build_binary.py` through that interpreter; an independent wheel does not carry `tool.uv.sources`, and the documented wheel limitation is correctly bounded by the accepted Dashboard-embedded binary product contract.

Independent review reproduced a real warning-as-error TestClient GET through the locked freeze environment and found exactly three canonical `anyio.from_thread.BlockingPortal` accesses, zero deprecated `anyio.abc.BlockingPortal` accesses and exact `bbee8944` direct-source identity. The complete twelve direct-TestClient consumer modules reproduced 197 passes and the same two queued baseline failures in 183.64 seconds, with no deprecation warning. Additional warning-as-error coverage for repository modules directly importing changed Starlette application, routing, state and bridge surfaces passed 105 tests with one intentional deselection. This project-facing coverage, the immutable official source and upstream test provenance adequately mitigate the broader unreleased tree for the supported binary lane pending an official release; the MEDIUM provenance risk remains documented rather than erased.

The team-status projection and plan-approval fixture failures remain MEDIUM and open under their recorded S67 and S78/S13 owners; their registry-1.6.0 differential evidence is preserved. Whole-tree Ty's five unchanged-test diagnostics remain LOW/open under S72 and are not reported green. The real discriminator uses no filter, shim or downgrade; locked export/freeze consumption is current-only and introduces no legacy/deprecated support. Deptry, Ruff, dependency integrity, diff and both 19-check Core feature gates pass. No new finding surfaced. S08 is review-passed and ready for separate lifecycle closure; this review leaves it open.

### w01-p02-s08-lifecycle-closure | low | closed pending closure-record review

Type: lifecycle traceability. Formal PASS `333080e4a351b9450158c8b8375d9beb301a98a1` accepts implementation `17095d27ca7e8727ec205155a7a209de5b58d0b5`. The S08 Step Record preserves the exact source identity, 211-package lock, 188-distribution compatibility result, real warnings-as-errors TestClient GET, three canonical and zero deprecated accesses, 28-test representative run, 197-pass broad consumer run with two differentially proven baseline failures, 105-pass changed-Starlette-surface run, static/Core checks, support boundary and review chain.

Vaultspec Core closed only `W01.P02.S08`; plan status is 8 of 81 Steps complete and `W02.P03.S76` is next. ER22 and the S08-owned deprecation correction are closed. The unreleased Starlette tree remains MEDIUM and open pending an official release; independently pip-resolved wheels remain outside the Dashboard-embedded binary contract. The team-status projection failure remains MEDIUM/open under `W05.P13.S67`, the plan-approval fixture remains MEDIUM/open under `W02.P03.S78`/`W02.P03.S13`, and five unchanged Ty diagnostics remain LOW/open under `W06.P14.S72`. No filter, downgrade, compatibility shim, old runtime option, legacy/deprecated support claim, runtime source or test source was added during lifecycle closure.
### w01-p02-s08-core-lifecycle-closure-formal-review | low | PASS

Type: lifecycle closure review. Commit `c865f0ea47de681a214159e69c6d2eb64c6d27eb` has exact parent `333080e4a351b9450158c8b8375d9beb301a98a1` and changes exactly five Vault artifacts. Its plan delta closes only `W01.P02.S08`; independent row and Core status counts report 8 of 81 Steps complete with `W02.P03.S76` next. The execution record maps to S08 and preserves the complete `17095d27ca7e8727ec205155a7a209de5b58d0b5` implementation to `333080e4a351b9450158c8b8375d9beb301a98a1` PASS-review chain, exact Starlette source revision, locked dependency and installed-distribution counts, real warning-as-error TestClient proof, canonical/deprecated access discriminator, representative and broad regression results, changed-Starlette-surface coverage, static checks and supported-product boundary.

ER22 alone closes with S08. The unreleased Starlette tree remains MEDIUM/open pending an official release, and independently pip-resolved wheels remain outside the supported Dashboard-embedded binary contract. The team-status projection failure remains MEDIUM/open under `W05.P13.S67`, the plan-approval fixture remains MEDIUM/open under `W02.P03.S78`/`W02.P03.S13`, and the five unchanged Ty diagnostics remain LOW/open under `W06.P14.S72`. Historical evidence is retained, all five changed documents are valid UTF-8 without replacement or NUL characters, and the closure adds no filter, downgrade, shim, old runtime option, legacy/deprecated support claim, runtime source or test source. Both affected features pass all 19 Vaultspec Core checks with zero diagnostics. No new finding surfaced; the S08 lifecycle closure passes mandatory review.
### w04-p10-s47-cooperative-server-owner | high | closed

Type: runtime lifecycle ownership. The authenticated administrative stop previously closed admission and then used process-directed `SIGINT`; on Windows that did not establish a cooperative Uvicorn-owned transition. The production gateway entry point now owns the current Uvicorn server instance and injects its `should_exit` callback. The route refuses 503 before closing admission when that owner is absent or malformed, leaving admission OPEN; otherwise a real authenticated HTTP request observes 202 before the serving task exits, followed by `should_exit` and bounded Uvicorn completion. Formal PASS `2279eb52d529ee338661006779a0143095003ce7` accepts the correction. This closes S47 and the ER15 trigger defect without adding compatibility behavior. S49 separately owns the total shutdown deadline, stream drain, owned-child cleanup and forced escalation; S48 discovery remains unchanged.

### w04-p10-s49-total-shutdown-deadline | high | closed

Type: runtime lifecycle and boundedness. Gateway connection drain, active work, background tasks, owned worker/descendants, bridge delivery, clients, database and telemetry previously had separate or absent bounds. S49 starts one absolute monotonic deadline before Uvicorn drains open connections, closes admission before active-run drain and passes remaining time through every teardown owner. Parked real-socket SSE reaches lifespan in 1.25-1.32 seconds against a 3.0-second total. The bridge's confirmed 7.1849-second wall / 3.6920-second loop stall is corrected by joined cancellation and deadline-capped request/backoff; the real accepted-but-unanswered socket case completes below 0.6 seconds for a 0.5-second budget plus 0.1-second Windows scheduler tolerance, with loop gap below 0.1 seconds. Contained and uncontained real process tests complete in 1.47 and 2.30 seconds inside a 4.0-second deadline with zero surviving descendants. S47 supplies the separately committed server-owner trigger; S48 is unchanged. Final formal PASS `4b2e0a61` accepts the complete correction.

### w04-p10-s49-uncontained-cooperative-root-race | high | closed

Type: Windows process-tree lifecycle. The first new uncontained discriminator failed: after authenticated cooperative shutdown, the root exited before Windows `taskkill /T` enumerated its child and the child survived. The spawner now retains descendant process identities with creation-time reuse guards before requesting cooperative exit and reaps only those exact identities within the original absolute deadline. The exact contained/uncontained rerun passes two tests in 4.31 seconds, with the uncontained case at 2.30 seconds and no survivor. Formal PASS `4b2e0a61` accepts this correction together with the later assignment-before-authority fix.

### w02-p03-s14-bridge-terminal-only-in-memory | high | open under W02.P03.S14

Type: terminal delivery durability. When the gateway accepts the connection but never answers the event request, bounded bridge close returns false and retains the undelivered terminal event in its in-memory buffer. This proves no event is silently discarded by the close call, but process memory is not durable delivery, incorporation or settlement and is lost at worker exit. `W02.P03.S14` remains the correction owner for an independent durable retry/reconciliation path. S49 makes no settlement claim.

### w04-p10-s49-full-worker-probe-harness-deadlock | medium | resolved measurement-integrity

Type: verification harness. Two full A2A worker probes exceeded their 60-second readiness bounds under the saturated shared host. The first then blocked by reading stderr from a still-live child before cleanup and initially targeted the uv environment redirector. The owned sessions were terminated, exact scans found zero worker survivors and the invalid test was removed. The corrected base-interpreter stdlib worker is retained only as production-spawner seam evidence; it is not full A2A or frozen-worker proof. S50 retains that proof obligation.

### current-schema-restart-post-catalog-run-poll-hang | high | open under served-capability W04.P08.S56; verification W02.P03.S11

Type: runtime recovery and developer-time blocker. One instrumented production restart reached completed ACP catalog subprocesses and OpenAI `/v1/models` HTTP 200, then continued successful 200 polling of `/v1/runs/current-schema-restart` until the 90-second external deadline. Cleanup preceded output inspection and left zero gateway/catalog survivors. The last durable state was three runs (`current-schema-restart`, `same-assignment-restart`, `other-assignment-restart`) in `reconciling` and `restart-demand` in `running`, all without failure reason or condition. Product shutdown never began, so this is separate from S49 and cannot be attributed only to host saturation after catalog completed. The currently open correction owner is `2026-08-05-served-capability-contract-plan W04.P08.S56`; this remediation plan's open `W02.P03.S11` verifies abandoned-run reconciliation and integrates atomic election. Prioritize it immediately after S47/S49 review.

### w04-p10-s47-formal-fail-correction | medium | resolved

Type: lifecycle correctness, test integrity and traceability. Formal review `b80e843b` found a malformed non-callable owner could return 202 and close admission before a deferred `TypeError`; the test substituted a lambda instead of exercising production Uvicorn ownership; two comments retained the removed process-signal language; and the shared `api/app.py` ownership boundary plus feature index were incomplete. Correction `b83ad5ba` validates callable shape before admission changes. Absent and malformed owners both return 503 with admission demonstrably OPEN. The production serve path calls a named `_bind_server_shutdown_owner`, and a real Uvicorn HTTP test proves the 202 response reaches its client before the serving task exits, then observes `should_exit` and bounded completion. Current source describes only cooperative owner behavior. The S47 record assigns that construction/injection seam to S47 and reserves total deadlines, stream drain and escalation for S49. The corrected focused gate passes 15 tests in 35.79 seconds; Ruff and Ty pass. Formal rereview `2279eb52` independently passes 15 tests in 12.84 seconds, including the 0.61-second real Uvicorn case, and resolves all five findings.

### w04-p10-s47-lifecycle-closure | low | closed pending closure-record review

Type: lifecycle traceability. Vaultspec Core closed only `W04.P10.S47`; plan status is 9 of 81 Steps complete. The Step Record preserves implementation `24dab547`, formal FAIL `b80e843b`, correction `b83ad5ba` and formal PASS `2279eb52`, including the real Uvicorn HTTP 202-before-exit proof and absent/malformed-owner 503 with admission remaining OPEN.

S47 closes the ER15 cooperative-trigger defect only. ER15 remains HIGH/open for S49's one total deadline, real-socket stream drain, owned-child cleanup and bounded forced escalation. S48 retains discovery identity and liveness ownership. Historical findings and evidence remain in place, and lifecycle closure adds no runtime path, compatibility behavior, legacy route or deprecated mechanism.

### w04-p10-s49-worker-owner-shape | medium | closed

Type: lifecycle correctness. Final implementation review applied the same fail-closed shape rule to the worker: a non-callable `request_server_shutdown` now receives 503 instead of reaching invocation. Authenticated callable-owner and malformed-owner tests pass in the actual worker app module. Full frozen-worker proof remains S50.

### w04-p10-s49-active-bridge-flush-deadline | high | closed

Type: shutdown boundedness and in-memory state preservation. Final implementation review found that `WorkerBridge.close()` joined a cancelled in-progress deferred flush without consulting its absolute deadline, and cancellation during HTTP or retry backoff could leave the extracted batch outside the in-memory buffer. The pending-task join now uses only remaining time; both cancellation sites restore the batch before propagation. The shared shutdown gate passes 48 tests in 41.39 seconds, and the worker app/IPC gate passes 35 tests in 12.76 seconds. This corrects S49 boundedness but does not promote volatile buffering to durable delivery; S14 remains HIGH/open.

### s49-late-uncontained-descendant-correction | high | closed

Type: lifecycle correctness, process containment and shutdown boundedness. Formal FAIL `dcac3b27` proved the pre-request identity snapshot could not see a child created inside `/admin/shutdown` after the request began and orphaned when its root exited. Every gateway-spawned worker now requires OS containment independent of profile; assignment failure aborts and reaps the spawn. A live owned handle restored without retained authority is seated before cooperative shutdown into a temporary Job Object or existing isolated process group. If seating fails, no cooperative request is issued and tree escalation starts while the exact root remains live. Cleanup is cancellation-safe and releases both retained and temporary authorities.

The new real discriminator creates no child before shutdown, spawns its only 300-second child in the handler, returns 202 and lets the root exit. Both initially uncontained/then-seated and precontained variants complete inside the original four-second deadline with no root or child survivor; observed calls were 1.65 and 1.60 seconds. The combined containment/reap gate passes 16 tests in 18.75 seconds, including prior children, cancellation and handle-release paths. No host-wide scan or bare-pid action after root exit is used. Formal PASS `4b2e0a61` accepts the HIGH correction after the subsequent assignment correction.

The complete post-correction S49 focused gate passed 67 tests in 56.64 seconds; Ruff and Ty passed on every changed Python path.

Windows seating uses the exact retained Popen OS handle rather than reopening a numeric pid, so exit and pid reuse cannot redirect containment to an unrelated process. POSIX retains the isolated process-group authority established at spawn. The late-child variants plus containment utility coverage pass 15 tests in 27.60 seconds.

### s49-failed-assignment-exact-popen-reap | high | closed

Type: lifecycle correctness, process containment and admission safety. Formal FAIL `91c882fe` proved that a Windows Job assignment failure left `ProcessContainment` empty, so cleanup reported false success, waited 5.0086 seconds and raised `TimeoutExpired` while the exact root remained live. Cleanup now treats only successfully assigned containment as authority. Otherwise it retains the live `Popen` root as a psutil creation-time identity, suspends it while collecting scoped descendants, terminates those exact identities, waits the retained process handle and releases containment before re-raising the original assignment error. It does not scan the host, reopen a bare pid after exit or admit the failed worker.

The real Windows proof uses a closed Job assignment capability and an actual root with two 300-second descendants. The production `_await_worker_ready` seam propagates `ProcessContainmentError` in 0.59 seconds with root and descendants absent. The 24-test containment gate passes in 12.09 seconds and the complete S49 gate passes 68 tests in 50.17 seconds; Ruff and Ty pass. Formal PASS `4b2e0a61` accepts the HIGH correction.

### s49-assignment-proof-uv-redirector-hang | medium | resolved measurement-integrity

Type: verification harness and developer-time blocker. The first new assignment-failure proof used the uv Windows virtual-environment redirector as the retained worker `Popen`, so it measured the wrong process identity and exceeded 60 seconds. The owned pytest tree was interrupted after its bound, its workspace-scoped descendants were reaped and an exact scan found no survivor. The fixture now starts `sys._base_executable`, consistent with the existing real-process probes and the production root-identity contract. The corrected proof completes in 0.59 seconds. The invalid run supports no runtime pass claim.

### w04-p10-s49-core-lifecycle-closure | low | closed pending closure-record review

Type: lifecycle traceability. Formal PASS `4b2e0a61` accepts the complete S49 chain: implementation `8f79c919`, formal FAIL `dcac3b27`, correction `84ba2a2b`, formal FAIL `91c882fe`, correction `d8453cf0` and final PASS. Core closes only `W04.P10.S49`, ER15 and ER16. The record preserves one total deadline, parked SSE, bridge/worker cleanup, late-child and assignment-failure proofs, exact retained-handle/PID-reuse safety, both harness hangs and the final 68-pass gate.

Volatile terminal delivery remains HIGH/open under W02.P03.S14. The 90-second recovery polling hang remains HIGH/open under served-capability W04.P08.S56 with remediation W02.P03.S11 verification. Trace-only provider-owner commit `141147db` leaves W04.P11.S60 reopened. S48 and S50 remain separate. Closure adds no runtime, compatibility, legacy or deprecated behavior.
### w02-p03-s76-current-authority-declaration | low | implemented pending formal review

Type: state-ownership model declaration. S76 adds one frozen, slotted `RunWriteAuthority` value containing durable run revision, writer generation, typed action and action-specific receipt identity. Construction has no missing-value defaults and refuses negative revision, non-positive generation, non-enum action and empty, oversized or non-string receipt identity. The value carries no credential, checkpoint state or transcript content. Focused real-SQLite coverage proves 14 cases, including that current schema 0016 remains readable and writable before S77 installs persistence. Formal review remains required; S76 is not lifecycle-closed.

### w02-p03-s76-schema-installation-dependency | high | open under W02.P03.S77

Type: migration ordering and current-schema integrity. Required ownership columns cannot be mapped onto `ThreadModel` before their physical migration: doing so makes every mapped SELECT and existing `create_thread` insert fail against schema 0016. Nullable columns or defaults would accept missing authority and manufacture history, violating the current-only contract. S76 therefore keeps the strict authority declaration separate from ORM persistence. S77 must atomically install and map all four required fields, validate the resulting schema, and refuse populated pre-current or unknown stores. It may not backfill, translate, alias, default or retain rows without complete authority.
### w02-p03-s76-core-lifecycle-closure | low | closed pending closure-record review

Type: lifecycle traceability. Formal PASS `821409d1` accepts implementation `8551069913f393a55cf9e5fe3c1bd33e9e6ff907`. Vaultspec Core closes only `W02.P03.S76`; plan status is 11 of 81 Steps complete and `W02.P03.S77` is next. The Step Record retains the completed 131-pass implementation gate, independent 14-pass focused review, Ruff, Ty and diff evidence. Remediation and served-capability-contract feature checks each pass all 19 Core checks with zero diagnostics.

The physical persistence dependency remains HIGH/open under `W02.P03.S77`, including atomic installation and mapping of all four required fields and refusal of populated pre-current or unknown stores without nullable fields, defaults, backfill, translation, substitution or execution. The independent database command's post-`[100%]` pytest teardown hang remains MEDIUM/open under `resource-aware-test-execution` with its exact command, more-than-90-second wall, session `71187` interrupt and process-absence evidence preserved in the formal review. Closure adds no runtime, legacy, deprecated, compatibility, backfill, translation or default behavior.

### w02-p03-s77-current-authority-persistence | high | implemented pending formal review

Type: durable ownership and migration safety. S77 installs required revision, writer generation, action type and action receipt columns with no nullable representation or defaults, closed checks and a unique receipt index. The runtime migration preflight refuses populated pre-current, structurally incomplete, invalid or receipt-incoherent stores before Alembic executes any revision; 0017 independently refuses populated upgrade and downgrade. Fresh creation writes one pre-minted INGEST receipt identically to thread authority, the durable action and worker dispatch. All 258 direct repository test seeds and 13 direct ORM seeds now supply explicit test-only authority. Formal review remains required and the Step stays open.

### w02-p03-s77-preflight-implicit-transaction | high | resolved in implementation

Type: migration atomicity. The first preflight implementation inspected the database on Alembic's connection and left SQLAlchemy's implicit read transaction open. Alembic then ran inside that external transaction, and connection close rolled back its version row and transactional SQLite DDL. The 93-case diagnostic reached 100% with 82 passes and 11 compatibility failures in 106.99 seconds. Ending the read transaction before configuring Alembic restores migration ownership. A four-case discriminator passed in 15.95 seconds, including the production runner's byte/shape-preserving refusal of populated 0007, fresh head validation, orphan-receipt refusal and initial receipt equality. The optimized migration module passes six tests in 6.66 seconds. The compatibility module then emitted all 15 passing dots before its known teardown stall; session `62322` was interrupted and its exact command-line process was absent.

### w02-p03-s77-explicit-test-seed-surface | medium | resolved in implementation

Type: test contract and plan decomposition. The S77 row names migrations, but a migration-only commit would leave model/schema parity broken and every fresh `create_thread` insert unable to satisfy required authority. The buildable Step therefore also maps the model, makes repository authority mandatory, corrects creation receipt identity, validates seated stores read-only and changes every current test seed explicitly. A test-only factory reduces repetition without entering production or accepting missing authority.

### w02-p03-s77-dashboard-release-pin | medium | open under Dashboard release coordination

Type: consumer packaging. The A2A package derives head 0017 from its installed graph, while the Dashboard package lock still selects an earlier A2A commit. Dashboard already owns quiescence, bounded candidate migration, snapshot rollback and typed failure. Its later release assembly must pin the reviewed S77 generation and preserve populated pre-current refusal; it must not retry, backfill or invent authority. S77 requires no Dashboard source change.

### w02-p03-s77-schema-fingerprint-formal-fail | high | resolved pending formal rereview

Type: schema integrity and admission safety. Formal FAIL `da7cd035` proved that the initial validator trusted required CHECK names without comparing predicates and trusted the receipt-index name plus uniqueness without comparing its indexed columns. A forged same-name `CHECK (1)` schema admitted invalid future authority, and a same-name unique index over another column could admit duplicate receipts. The correction centralizes current column, normalized predicate and exact index-column fingerprints. Ordinary read-only compatibility rejects both real-SQLite forgeries in two tests completing in 2.39 seconds. Migration preflight rejects both forged empty current stores before Alembic and admits a valid populated current store in three tests completing in 3.19 seconds. Formal rereview remains required.

### w02-p03-s77-postgresql-fingerprint-evidence | medium | open

Type: dialect validation evidence. PostgreSQL remains a locked server dependency profile. The correction normalizes the catalog forms PostgreSQL uses for equivalent VARCHAR checks, including casts, `btrim`, redundant parentheses and `ARRAY`/`ANY`, and the deterministic rendered-expression proof passes. No locked PostgreSQL service or connection environment was available during this bounded correction, so real catalog introspection and a live future-migration admission proof remain open. The Dashboard SQLite product path has real-store proof.

### w02-p03-s77-sqlite-check-lexer-formal-rereview-fail | high | resolved pending formal rereview

Type: schema integrity and admission safety. Formal rereview FAIL `e52bd82e` proved that the first SQLite extractor could count a complete required `CONSTRAINT ... CHECK (...)` sequence hidden in raw `CREATE TABLE` comments. The correction replaces regex discovery with a fail-closed SQLite lexical scan shared by ordinary compatibility and SQLite migration preflight. It ignores block comments, line comments, string literals and quoted identifiers during discovery and parenthesis balancing, preserves literals inside actual predicates, and rejects unterminated lexemes, unbalanced predicates and duplicate constraint names. The 16-case lexical gate passes in 0.11 seconds; three real-SQLite comment/string forgeries are refused read-only in 11.60 seconds; five migration-preflight forgeries are refused in 7.12 seconds; canonical populated current migration admission passes in 1.12 seconds. The exact receipt-index correction remains intact, the PostgreSQL evidence gap remains MEDIUM/open, and formal rereview is still required.

### w02-p03-s77-correction-module-teardown | medium | open under resource-aware-test-execution

Type: test lifecycle and developer-time loss. The corrected nine-case migration module emitted nine passing nodes and `[100%]` at 30 seconds, then stalled after results. Session `96385` was interrupted immediately and no matching pytest process remained. The authoritative terminal correction gates are the completed three-case migration-preflight discriminator, two-case read-only compatibility discriminator and three-case schema-fingerprint unit gate. This is the same post-result teardown class already queued; it supports no completed-module pass claim.
