---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-19'
body_schema: 'body-v2'
body_hash: 'sha256:deeadfac235abe07a1452cf5a285d41c9d3ccdc8416a53d7e565acdc4f08bb83'
related:
  - "[[2026-09-05-embedded-runtime-remediation-adr]]"
  - "[[2026-08-05-served-capability-contract-state-truthfulness-adr]]"
  - "[[2026-09-05-embedded-runtime-remediation-research]]"
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-09-05-embedded-runtime-remediation-implementation-review-audit]]"
---
# `embedded-runtime-remediation` audit: `W02 P03 S76 run write authority review`

## Scope

Independent formal review of implementation commit `8551069913f393a55cf9e5fe3c1bd33e9e6ff907` against the accepted remediation ADR, state-truthfulness T6, remediation research, plan Step `W02.P03.S76`, execution record, rolling implementation audit, `RunWriteAuthority`, and its database tests. The review covered current-only semantics, runtime type checks, action-specific receipt identity, sensitive-state exclusion, and the schema-0016/S77 boundary.

Verdict: **PASS** for S76. No implementation defect was found. One separate medium test-runner hang surfaced and is queued below; it does not change the S76 model verdict or authorize lifecycle closure before the normal review and queue updates complete.

## Findings

### w02-p03-s76-current-write-authority | low | Strict complete declaration satisfies the S76 boundary

Type: state ownership model. Status: verified complete pending lifecycle closure. `RunWriteAuthority` is frozen and slotted and requires exactly four constructor values: non-negative integer run revision, positive integer writer generation, closed `ControlActionType`, and bounded nonblank string receipt identity. Boolean and non-integer numeric authority values are rejected at runtime. No missing-value default, nullable representation, alias, translation, or inferred authority exists.

The pair of `action_type` and `action_receipt_id` forms the action-specific receipt identity required by T6, while run revision and writer generation identify the election. The declaration contains no credential, token, checkpoint payload, graph state, transcript, or message content. Its field-set test prevents those authorities from being silently duplicated into this value.

### w02-p03-s76-schema-0016-boundary | low | Deferring physical persistence to S77 is required and buildable

Type: migration ordering and current-only schema integrity. Status: verified complete for S76; persistence remains high/open under `W02.P03.S77`. Schema 0016 does not contain the four ownership columns. S76 deliberately leaves `ThreadModel` unchanged and declares the strict value beside the ORM mapping. This keeps the current installed schema readable and writable without nullable columns or defaults that would fabricate authority for existing rows. S77 is the exact next owner for atomic physical columns, ORM mapping, upgrade validation, and refusal of populated pre-current or unknown-ownership stores without backfill, substitution, translation, or execution.

Focused real-SQLite coverage constructs current model metadata, proves the four future columns absent, inserts through the real `create_thread` service, and reads the row back. Deferral therefore preserves a buildable Step boundary and does not hide compatibility behavior.

### database-gate-post-result-hang | medium | Pytest emitted all 131 case results but did not terminate

Type: test infrastructure lifecycle and developer-time blocker. Status: open; owner `resource-aware-test-execution` follow-up in `src/vaultspec_a2a/testing`. The exact independent command was `uv run --no-sync pytest src/vaultspec_a2a/database/tests/test_run_write_authority_model.py src/vaultspec_a2a/database/tests/test_schema_parity.py src/vaultspec_a2a/database/tests/test_database.py -q`. Its last emitted line was `...........................................................              [100%]`. It then produced no summary or process exit for more than 60 seconds after that line and more than 90 seconds total wall time.

The reviewer sent one Ctrl-C character to retained unified execution session `71187`; the exact session returned exit code 1 after 0.021 seconds, returned no further session identifier, and is therefore absent. The command exposed no separately retained child identity to the reviewer. Exact owned-session absence is evidenced by the terminal result carrying exit code 1 and no session identifier; the focused SQLite fixture also disposes its engine. Do not convert the emitted case lines into a completed 131-pass claim for this independent run. Preserve the implementation author's earlier completed 131-pass evidence separately. Diagnose pytest session finalization, resource-aware lease release, and process-exit ownership without weakening or bypassing machine-global exclusion.

## Recommendations

Accept the S76 implementation for lifecycle closure after this review is recorded. Execute S77 next to install the complete current-only persistence boundary atomically. Prioritize the newly queued pytest post-result hang with the existing resource-aware test infrastructure work because it consumes development time even when assertions complete.

Completed review gates:

- focused S76 model module with repository addopts disabled: 14 passed in 0.26 seconds, 7.69 seconds wall;
- Ruff check and format: pass for both changed Python files;
- ty: pass for both changed Python files;
- implementation diff whitespace: clean;
- feature-scoped Vaultspec Core: all 19 checks passed before this review audit was scaffolded.
