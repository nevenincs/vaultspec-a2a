---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-05'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:2986be7c1f78c2dcce2ccc775d81c57a8fb6d345359ac583150b1897aa5a0ca3'
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
### p01-s11-rag-data-plane-version-drift | medium | resolved pending W01.P02.S06 formal review

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
### p01-s11-cold-catalog-shutdown-timeout | medium | open

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

### w01-p02-s06-isolated-rag-pinning-evidence | medium | corrected pending formal review

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

### w01-p02-s06-shared-rag-token-disclosure | high | resolved pending formal re-review

Type: security and evidence handling. Commit `9d56e23e40e46e9cb754cfb3512365d96d524948` persists the live shared RAG service token verbatim in `.vault/audit/2026-08-02-provider-model-catalog-implementation-review-audit.md:220` and `.vault/audit/2026-09-05-embedded-runtime-remediation-implementation-review-audit.md:463,839`. The token is credential material, not a safe durable fingerprint. This blocks S06 closure even though the test did not stop or otherwise mutate the shared daemon. Remove the raw value from all current documents, retain only a one-way digest/equality result, and rotate the exposed token through the operator-owned RAG lifecycle before re-review. Do not rewrite historical commits or make the S06 test control the shared daemon.

### w01-p02-s06-private-service-cleanup-incomplete | medium | resolved pending formal re-review

Type: test resource lifecycle and degraded cleanup. `_run_rag_cli` at `src/vaultspec_a2a/providers/tests/test_harness_mcp_pinning.py:96-122` bounds a control subprocess and kills that subprocess on timeout. During context cleanup at lines 182-198, however, a timed-out or cancelled `server stop` can leave the already detached private service alive because no terminal owned-process fallback or post-stop absence check runs. The normal-path stop passed, but S06 explicitly owns bounded isolated cleanup and must remain review-blocked until cancellation/stop degradation cannot leak its daemon. Use the private service record's exact ownership identity for a bounded fallback, shield cleanup from caller cancellation within a total deadline, verify the owned process/port is gone, and add a discriminator that exercises cancellation or failed stop without touching any shared service.

### w01-p02-s06-isolated-rag-pinning-formal-review | high | FAIL

Type: formal implementation review disposition. The four-path commit has the intended test/audit scope and `git diff --check` passes. `uv.lock` selects exactly one RAG version and the helper applies that exact `vaultspec-rag[mcp]` requirement to both a private local-only service and the production-registry `vaultspec-search-mcp` stdio entry point. Status, data and Qdrant roots are test-owned; the published version and loopback port are checked before the MCP call. The real non-vacuous discriminator names the pinned non-workspace and excludes the valid launch workspace. Independent review reran it once (`1 passed` in 55.66 seconds), the entire module (`33 passed` in 62.88 seconds), Ruff format/check and Ty; all pass. Full remediation Core reports 19 clean checks. No legacy/deprecated product surface was added, ER20 alone is marked resolved pending review, and the separate cold catalog/Uvicorn finding remains open under S07/S49.

The plaintext shared credential is a HIGH security defect, and degraded cleanup is a MEDIUM resource-lifecycle defect in S06 itself. S06 does not pass formal review and must remain open pending both corrections and re-review.

### w01-p02-s06-review-corrections | high | corrected pending formal re-review

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
