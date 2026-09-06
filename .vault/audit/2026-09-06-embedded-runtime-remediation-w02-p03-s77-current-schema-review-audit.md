---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:ab6149257dfad4a4d64ca019b87db171e133fa67a4184cdae4ba979ea3b5b18c'
related:
  - "[[2026-09-05-embedded-runtime-remediation-adr]]"
  - "[[2026-08-05-served-capability-contract-state-truthfulness-adr]]"
  - "[[2026-09-05-embedded-runtime-remediation-research]]"
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-09-05-embedded-runtime-remediation-W02-P03-S77]]"
  - "[[2026-09-05-embedded-runtime-remediation-implementation-review-audit]]"
---
# `embedded-runtime-remediation` audit: `W02 P03 S77 current ownership schema review`

## Scope

Independent formal review of implementation commit `7586f2ee584b11ad0a4df9f3852cc0c99f29d4fa` against remediation Step `W02.P03.S77`, state-truthfulness T6, the remediation ADR and research, the S77 execution record, and the rolling audits. The exact commit contains 70 paths, not the previously reported 65: seven production paths, two new test/support paths, 56 mechanical test-seed paths, and five Vault paths. Review covered empty-only 0017 upgrade and downgrade, refusal of populated older stores before Alembic mutation, implicit read-transaction rollback, future migration admission, frozen migration versus live enum vocabulary, ORM/schema parity, ordinary read-only compatibility, strict repository creation, exact shared receipt identity, and credential/checkpoint/transcript exclusion.

Verdict: **FAIL**. The migration and creation behavior passes its focused tests, but current-schema admission trusts constraint and index names without proving what they enforce. A forged schema can therefore pass ordinary compatibility and admit invalid future authority writes. `W02.P03.S77` must remain open.

## Findings

### s77-check-predicate-identity | high | named checks can conceal non-enforcing constraints

Type: schema integrity and future-write admission. Status: open and blocking `W02.P03.S77`. `compatibility._validate_write_authority` lowercases the `threads` DDL and checks only that four constraint-name substrings occur. The current-only Alembic preflight likewise retains only names from `get_check_constraints`; it does not compare each predicate. The preflight performs no structural validation at all while `threads` is empty. Consequently, an empty database stamped 0017 with the exact authority columns, index, and constraint names but predicates replaced by `CHECK (1)` passes ordinary read-only compatibility. A bounded real-SQLite discriminator then committed `run_revision=-1`, `writer_generation=0`, `writer_action_type='unknown-action'`, and a blank receipt. Its exact output was `COMPATIBILITY_ACCEPTED_PERMISSIVE_NAMED_CHECKS` followed by `INVALID_FUTURE_WRITE_COMMITTED`; exit 0 in 5.02 seconds. The requested control case, deleting one required constraint name while preserving its predicate, was rejected with `MISSING_NAMED_CHECK_REJECTED`; exit 0 in 7.03 seconds. Name presence therefore detects absence but does not prove enforcement.

### s77-receipt-index-identity | high | named unique index is not tied to the receipt column

Type: schema integrity and receipt uniqueness. Status: open and blocking `W02.P03.S77`. Ordinary compatibility reads only index name and uniqueness from `PRAGMA index_list`; migration preflight similarly discards the `column_names` returned by SQLAlchemy inspection. A unique index named `ux_threads_writer_action_receipt_id` over another column satisfies both tests while leaving `writer_action_receipt_id` non-unique. That structure can admit multiple threads with one action-specific receipt and defeats the durable receipt identity required by T6. Existing coverage proves a missing named index is rejected and the real 0017 index enforces uniqueness, but does not exercise a same-name wrong-column index.

### s77-current-only-migration-and-creation | low | focused current behavior is otherwise verified

Type: verified implementation behavior. Status: verified, subject to the two blocking structural findings. Revision 0017 installs four required, non-null, no-default columns with frozen predicates and the unique receipt index only for an empty `threads` table; populated upgrade and downgrade refuse. The programmatic runner rejects a populated pre-0017 store before any revision and rolls back its implicit inspection transaction before Alembic begins. The live ORM vocabulary matches the frozen 0017 action vocabulary at this commit. The only production repository caller passes strict `RunWriteAuthority`; one pre-minted receipt is identical across thread authority, the same-thread INGEST control action, and `DispatchRequest`. Authority contains no credential, checkpoint state, or transcript content. A fresh AST scan found 260 `create_thread` calls and zero missing `write_authority` keywords. No S77 path adds a nullable authority field, default, backfill, translation, alias, or deprecated/legacy execution behavior.

### resource-aware-test-execution | medium | known post-result compatibility teardown stall remains open

Type: test lifecycle and developer-time loss. Status: previously queued and still open. The S77 execution record preserves that the 15-case compatibility module emitted all passing nodes and `[100%]`, then stalled during teardown in session `62322` and was interrupted with its exact command-line process absent. This independent review did not rerun that known hanging module. The previously recorded 131-case database post-result hang remains open under the same owner. These hangs do not excuse the schema-integrity failure and remain priority remediation because they consume review time after assertions finish.

## Recommendations

Keep `W02.P03.S77` open. Make ordinary read-only compatibility and current-only migration preflight prove the normalized predicate attached to each required check, and prove that the named unique index targets exactly `writer_action_receipt_id`. Apply structural validation to empty and populated current-head stores before admitting runtime or later migration execution. Add real-SQLite adversarial tests for a missing check, a same-name permissive check, and a same-name wrong-column unique index. Each case must fail without mutation, while the canonical 0017 schema must reject invalid authority and duplicate receipt writes at the database boundary.

Focused review evidence: migration module 6 passed in 11.12 seconds; strict authority model 15 passed in 0.19 seconds; exact creation receipt and secret-exclusion case 1 passed in 1.28 seconds; bounded Ruff and Ty checks passed; `git show --check` passed. The known hanging broad compatibility module was not repeated.
