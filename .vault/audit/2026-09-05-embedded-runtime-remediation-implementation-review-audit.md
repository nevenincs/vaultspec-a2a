---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-05'
modified: '2026-09-05'
body_schema: 'body-v2'
body_hash: 'sha256:ee0cd843b0aab8436d9dd6c91d3c6cb9b181599384ee9cd55185d7f6d63656fe'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-09-05-embedded-runtime-remediation-qualification-inputs-reference]]"
  - "[[2026-09-05-embedded-runtime-robustness-audit]]"
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

Type: contract completeness and regression. Status: open; review-blocking for corrected `W01.P01.S02` at Dashboard `02101b52d15e31a23b9c5cb181c9f6e648b25261`. The correction resolves the three original HIGH subjects, but replacing the broker table removed its retry-rule column. Neither the amended authoritative edge ADR nor any current Dashboard ADR/reference now preserves the frozen current behavior that `run-start` permits exactly one retry after an ambiguous connection or protocol failure using the same run, reservation, and payload before authoritative status reconciliation; `run-cancel` forbids blind retry and reconciles status; and `clarification-respond` forbids blind retry while preserving request identity and reconciling the result. Live source still contains the specialized run-start replay/reconciliation path. The new three mutating capabilities have complete idempotency and reconciliation rules, but S02 owns the complete eleven-verb contract and cannot regress existing wire facts while adding four operations. Ownership: correct S02 by restoring the three existing mutation rules in the authoritative edge decision and its derived operation table, without weakening the new idempotency contract.

### s02-edge-adr-d2-marker | low | A literal plus sign corrupts the D2 decision marker

Type: documentation quality. Status: open; non-blocking by itself. Dashboard `02101b52...` leaves the line `+**D2 — Actors and tokens are provisioned by the engine at run start.**` after the new amendment. Core markdown validation accepts it as prose, but the literal plus breaks the ADR's established bold decision-marker form and makes D2 harder to scan and parse semantically. Ownership: remove the stray plus in the S02 documentation correction.

### s02-corrected-formal-rereview | high | FAIL - original defects resolved but retry-contract regression remains

Type: implementation review. Status: open. Re-review at A2A `df8645c723d16298252c831ea8982836bbb59aed` and Dashboard `02101b52d15e31a23b9c5cb181c9f6e648b25261` confirms the accepted edge ADR legitimately expands seven verbs to exactly eleven; the four additions have exact names and routes, bounded inputs and outputs, typed receipts/refusals/conflicts/errors, identity, idempotency, authentication, scope, budgets, retry and reconciliation rules; ADR and reference mutually link and agree; producer-first fixed per-target versioned archives and SHA-256 sidecars, version-only Dashboard fetch-verify-bundle, removal of source build/checkout/commit pinning, and final receipt/process/discovery agreement are explicit; and S50 matches. A focused assertion passes the eleven-row matrix, four route bindings, bounds, envelopes, provenance and mutual links. A2A Core validation is clean, only S01/S02 are closed, S03 remains untouched, and both repositories are clean. The preceding HIGH regression prevents a PASS until the existing mutation retry rules are restored.

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
