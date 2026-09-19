---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-19'
body_schema: 'body-v2'
body_hash: 'sha256:167365a433040645cbe97cf68d1c38bab48eca6d3ceeba5986c62c1028cb6e28'
related:
  - "[[2026-09-05-embedded-runtime-remediation-adr]]"
  - "[[2026-08-05-served-capability-contract-state-truthfulness-adr]]"
  - "[[2026-09-05-embedded-runtime-remediation-research]]"
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
  - "[[2026-09-06-embedded-runtime-remediation-w02-p03-s77-schema-fingerprint-rereview-audit]]"
---
# `embedded-runtime-remediation` audit: `W02 P03 S77 lexer correction rereview`

## Scope

Independent formal rereview of correction `48c661c2148105dc1b89c2b2e412b9744468759d` across its exact nine-path diff and the complete S77 chain: implementation `7586f2ee584b11ad0a4df9f3852cc0c99f29d4fa`, initial formal FAIL `da7cd035`, fingerprint correction `9ec2396d2b46d550d875626b10d7d5346676093b`, lexer FAIL `e52bd82e`, the governing ADR/research/plan, state-truthfulness T6, execution record, and rolling audits. Review covered SQLite lexical context, quoted identifiers, real parenthesis balance, literal preservation, malformed and duplicate declarations, ordinary read-only compatibility, migration preflight, exact receipt-index identity, current versus frozen action vocabulary, PostgreSQL evidence limits, and the prohibition on legacy/default/backfill/translation/alias/deprecated accommodation.

Verdict: **PASS** for the S77 SQLite product contract. The correction closes the remaining blocking CHECK-integrity finding, keeps the exact-index correction intact, and introduces no new critical, high, medium, or low implementation defect. The locked live PostgreSQL catalog proof and the existing post-result pytest teardown hang remain separately open MEDIUM findings. This audit does not close the Step.

## Findings

### s77-sqlite-check-lexer | low | lexical extraction closes comment and literal forgery

Type: corrected schema integrity. Status: verified closed. The extractor now tokenizes SQLite DDL sufficiently for this boundary: it skips block comments, line comments, string literals, and double-quoted, backtick-quoted, or bracket-quoted identifiers during discovery; recognizes bare or quoted constraint names; balances parentheses only outside those lexical regions; preserves the original predicate slice, including literals, for exact normalization; and returns an empty result on unterminated quotes/comments, unbalanced predicates, or duplicate declarations. The prior block-comment exploit is rejected. Independent real-SQLite block-comment, line-comment, and string-literal forgeries are each rejected with their schema catalog unchanged. Canonical DDL and a real schema with double-quoted required names are accepted read-only. A separate discriminator with parentheses and comment tokens inside quoted identifiers and literals returned `REAL_STRUCTURE_BALANCE_AND_LITERAL_RETENTION=PASS`; duplicate and malformed declarations returned `DUPLICATE_AND_MALFORMED_FAIL_CLOSED=PASS`.

### s77-shared-validator-boundary | low | compatibility and SQLite preflight consume one fail-closed parser

Type: validation architecture. Status: verified. Ordinary compatibility passes raw read-only `sqlite_master` DDL through `extract_named_check_predicates` and then the exact current predicate matcher. SQLite migration preflight uses the same extraction path before Alembic execution; non-SQLite migration preflight retains dialect inspection. Five forged current schemas, comprising permissive checks, a wrong-column receipt index, and check text hidden in block comments, line comments, or string literals, are refused. A valid populated current store remains admissible for future packaged migrations. Compatibility opens SQLite with `mode=ro` and performs only `SELECT` and pragma reads; the real-store probes compare the schema catalog before and after validation.

### s77-receipt-index-and-authority-contract | low | prior exact-index correction remains closed

Type: durable authority identity. Status: verified. Both validation paths require the named receipt index to be unique over the exact ordered tuple `writer_action_receipt_id`; name-only or wrong-column indexes fail. Required columns remain non-null with no defaults. The current model/fingerprint derives one action vocabulary from live `ControlActionType`, while revision 0017 keeps its frozen authored DDL. Fresh creation retains one identical receipt across thread authority, same-thread INGEST action, and dispatch. No credential, checkpoint state, transcript content, legacy admission, backfill, translation, alias, inferred default, deprecated path, or fallback execution is introduced.

### s77-postgresql-catalog-proof | medium | locked live dialect evidence remains open

Type: dialect evidence. Status: open and unchanged. The non-SQLite preflight uses inspector-returned predicates and deterministic PostgreSQL normalization for known cast, `btrim`, parentheses, and `ARRAY`/`ANY` forms. No locked PostgreSQL catalog or live future-migration proof was available, so this PASS makes no live PostgreSQL portability claim. Close the finding with the locked server dependency profile against a real PostgreSQL catalog, covering canonical populated-current admission, forged predicate refusal, exact index columns, and future-head migration behavior, or retain the dialect-correct open gate.

### resource-aware-test-execution | medium | known post-result teardown hangs remain open

Type: test lifecycle and developer-time loss. Status: open under the existing resource-aware test owner. This rereview did not run either known hanging module as a whole. The bounded six-case migration discriminator completed normally. Prior sessions `62322`, `96385`, and `50170` remain the authoritative evidence for compatibility/database commands that emitted passing results or `[100%]` and then failed to terminate. Their queue ownership and process-absence records remain unchanged.

## Recommendations

Accept correction `48c661c2148105dc1b89c2b2e412b9744468759d` as closing both S77 blocking schema-integrity findings. Keep the PostgreSQL live-catalog evidence and pytest teardown lifecycle work open under their existing owners. S77 may proceed to lifecycle closure after this formal PASS is incorporated, without adding compatibility, legacy, defaults, backfill, translation, aliases, or deprecated behavior.

Bounded rereview evidence: lexical and fingerprint suite 16 passed in 0.21 seconds; five forged migration-preflight cases plus valid populated-current admission 6 passed in 36.76 seconds; independent five-store compatibility probe reported all three forgeries rejected read-only and canonical/quoted schemas accepted read-only; structure/literal/malformed discriminator passed in 3.78 seconds; Ruff, Ty, `git show --check`, and exact diff inspection passed. Vaultspec Core validates the feature corpus.
