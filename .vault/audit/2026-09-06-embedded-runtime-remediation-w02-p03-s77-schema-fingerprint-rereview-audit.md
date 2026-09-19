---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-19'
body_schema: 'body-v2'
body_hash: 'sha256:36218ce35013eca0bf48e675226be76385e0daf7bf7351868fbd8fb642dd6b38'
related:
  - "[[2026-09-05-embedded-runtime-remediation-adr]]"
  - "[[2026-08-05-served-capability-contract-state-truthfulness-adr]]"
  - "[[2026-09-05-embedded-runtime-remediation-research]]"
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-09-06-embedded-runtime-remediation-w02-p03-s77-current-schema-review-audit]]"
---
# `embedded-runtime-remediation` audit: `W02 P03 S77 schema fingerprint rereview`

## Scope

Independent formal rereview of correction `9ec2396d2b46d550d875626b10d7d5346676093b` across its exact 11-path diff and the S77 chain: implementation `7586f2ee584b11ad0a4df9f3852cc0c99f29d4fa`, formal FAIL `da7cd035`, the remediation ADR/research/plan, state-truthfulness T6, execution record, and rolling audit. Review covered both prior HIGH findings, ordinary read-only compatibility, current and future migration preflight, SQLite predicate extraction, exact index columns, live versus frozen enum vocabulary, PostgreSQL normalization claims, and exclusion of legacy, defaults, backfill, translation, aliases, and fallback execution.

Verdict: **FAIL**. The receipt-index HIGH is closed and migration preflight now validates exact inspector-returned predicates and index columns for installed authority schemas. Ordinary SQLite compatibility still accepts required predicate text embedded in SQL comments as if it were a real named constraint, so the CHECK-integrity HIGH remains open and blocking. `W02.P03.S77` must remain open.

## Findings

### s77-sqlite-check-lexer | high | comments can forge the required CHECK fingerprint

Type: schema integrity and future-write admission. Status: open and blocking `W02.P03.S77`. `extract_named_check_predicates` applies `_NAMED_CHECK.finditer` across raw `CREATE TABLE` text without tracking SQL comments or whether a match begins inside a quoted literal. Its balanced-parenthesis loop starts only after the regex match, so comment-contained text is promoted to an apparent constraint. A bounded real-SQLite discriminator replaced every canonical authority constraint with an actual `CONSTRAINT forged_N CHECK (1)` and preserved each required name and predicate only inside `/* CONSTRAINT required_name CHECK (required_predicate) */`. Production `_validate_write_authority` accepted the forged schema, after which SQLite committed `run_revision=-1`, `writer_generation=0`, `writer_action_type='unknown-action'`, and a blank receipt. Exact output was `COMMENT_FORGED_CHECKS_ACCEPTED` then `COMMENT_FORGED_INVALID_WRITE_COMMITTED`; exit 0 in 6.06 seconds. The correction's same-name `CHECK (1)` test does not cover comment or string-literal lexical context. This is a concrete current SQLite false acceptance, not a theoretical parser concern.

### s77-receipt-index-identity | low | exact receipt-index columns are now verified

Type: corrected schema integrity. Status: verified closed. Ordinary compatibility reads each SQLite index's ordered columns through a parameterized `pragma_index_info` query and requires the exact one-column tuple `writer_action_receipt_id` plus uniqueness and the required name. Migration preflight passes inspector index records to the same matcher, retaining `column_names`. Real-SQLite read-only and migration-preflight cases reject a same-name unique index over `threads.id`; the schema dump remains unchanged. No fallback accepts name-only identity.

### s77-migration-preflight-and-current-vocabulary | low | installed schemas are structurally gated before migration

Type: current-only migration behavior. Status: verified subject to the compatibility blocker. Preflight recognizes 0017 or a descendant through the packaged revision graph, validates installed authority structure even when `threads` is empty, validates populated authority rows and same-thread/same-action receipts, rolls back the inspection transaction, and then permits Alembic. Empty pre-0017 stores can install 0017, forged empty 0017 stores are refused without mutation, and a valid populated 0017 store remains eligible for future migration execution. The current fingerprint and ORM derive action values from the one live `ControlActionType`; frozen revision 0017 retains its authored vocabulary. A future vocabulary change without its matching migration will therefore fail the canonical schema tests instead of being silently accepted. No nullable authority, default, legacy row handling, backfill, translation, alias, or execution-time substitution was added.

### s77-postgresql-catalog-proof | medium | PostgreSQL normalization lacks locked live evidence

Type: dialect evidence. Status: open. PostgreSQL migration preflight normalizes common inspector forms: text and character-varying casts, `btrim`, redundant parentheses, and `ARRAY`/`ANY`. The deterministic rendered-expression unit case passes, but no locked PostgreSQL service/catalog introspection or live future-migration admission was run. PostgreSQL may render equivalent stored expressions in additional cast or operator forms, so the review accepts only the deterministic normalization proof and makes no live portability claim. Close with the locked server dependency profile against a real PostgreSQL catalog, covering canonical populated current admission, forged predicate refusal, exact index columns, and future-head migration behavior, or retain an explicitly dialect-correct open gate.

### resource-aware-test-execution | medium | focused compatibility cases still hang after results

Type: teardown lifecycle and developer-time loss. Status: open under the existing resource-aware test owner. The exact command `uv run --frozen pytest src/vaultspec_a2a/database/tests/test_compatibility.py::TestCompatibleStoresValidateWithoutMutation::test_head_store_validates_and_mutates_nothing src/vaultspec_a2a/database/tests/test_compatibility.py::TestIncompatibleStoresFailLoud::test_same_named_permissive_checks_are_refused_read_only src/vaultspec_a2a/database/tests/test_compatibility.py::TestIncompatibleStoresFailLoud::test_same_named_wrong_column_receipt_index_is_refused_read_only -o addopts='' -q` emitted `... [100%]` and then remained live at the 30.006-second bound. Session `50170` was interrupted with Ctrl-C through its retained exec session and ended exit 1. A machine process query restricted to Python/uv processes containing the exact first node identity returned `OWNED_COMPATIBILITY_PYTHON_UV_PROCESSES=0`. The module was not rerun. This repeats the already queued post-result hang and continues to consume review time.

## Recommendations

Keep `W02.P03.S77` open. Replace the SQLite regex scan with a lexical extraction that ignores line comments, block comments, quoted strings, and quoted identifiers while locating real named constraints, or use another SQLite-specific mechanism that proves the actual enforced predicates. Add full read-only compatibility and migration-preflight adversarial cases where canonical constraint text exists only in block comments, line comments, and string literals; prove each is rejected without mutation and invalid future writes remain impossible.

Retain the PostgreSQL catalog finding until locked live evidence establishes the normalizer against actual inspector output. Continue the separately owned teardown-hang work as a priority.

Bounded rereview evidence: schema fingerprint unit tests 3 passed in 0.09 seconds; forged-schema migration preflight and valid populated-current tests 3 passed in 3.31 seconds; Ruff, Ty, `git show --check`, and exact diff inspection passed. The compatibility assertions reached `[100%]` but their process result is not claimed as a completed pass because teardown hung.
