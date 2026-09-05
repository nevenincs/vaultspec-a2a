---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-05'
modified: '2026-09-05'
body_schema: 'body-v2'
body_hash: 'sha256:4b10c5b684309b737bead3c1a54211ae39767dbe95134ff8b5f1a21dc326d103'
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

## Recommendations

- Keep the captured A2A and Dashboard identities distinct until the Dashboard component lock, release manifest, discovery generation, and running process agree.
- Establish the durable message capacity before running A10; do not reuse an unrelated stream or IPC buffer as `Q`.
- Make the freeze recipe collect explicit runtime modules and data or exclude every test namespace, then inspect the built archive as part of the release lifecycle discriminator.

- For `qualification-capture-provenance`, add a bounded capture recipe or immutable evidence file that reproduces every frozen value with project-locked tools and names both repository revisions and clean states.
- For `dashboard-pretest-deadlines-incomplete`, freeze every current broker, lifecycle, discovery, and drain deadline while keeping the 30-second and 120-second freshness predicates tied to their distinct consumers.
- For `database-pool-backend-conflation`, split SQLite timeout/pooling facts from the PostgreSQL QueuePool 5-plus-10 configuration.
- For `in-process-mode-posture-unspecified`, list the deterministic and mock execution keys, current arming state, conditional requirements, and exclusion from external work evidence.
