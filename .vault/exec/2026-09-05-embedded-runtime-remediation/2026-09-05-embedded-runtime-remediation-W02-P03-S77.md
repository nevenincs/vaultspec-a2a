---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:aca0259144bfb4b9a9ef24e158a8bac06949a50073efbb1b842dae0a2d873304'
step_id: 'S77'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---

# Add the current ownership and receipt schema with upgrade validation; refuse pre-current or unknown-ownership rows as incompatible without backfill, translation, migration-time substitution or execution

## Scope

- `src/vaultspec_a2a/database/migrations`

## Changes

- `M` `.vault/audit/2026-09-05-embedded-runtime-remediation-implementation-review-audit.md`
- `M` `.vault/audit/2026-09-05-embedded-runtime-robustness-audit.md`
- `M` `.vault/research/2026-09-05-embedded-runtime-remediation-research.md`
- `M` `src/vaultspec_a2a/api/tests/test_acceptance_five_verb.py`
- `M` `src/vaultspec_a2a/api/tests/test_active_run_discovery_live.py`
- `M` `src/vaultspec_a2a/api/tests/test_catalog_restart_redispatch.py`
- `M` `src/vaultspec_a2a/api/tests/test_clarification_loop_live.py`
- `M` `src/vaultspec_a2a/api/tests/test_endpoints.py`
- `M` `src/vaultspec_a2a/api/tests/test_gateway_live.py`
- `M` `src/vaultspec_a2a/api/tests/test_internal.py`
- `M` `src/vaultspec_a2a/api/tests/test_progress_allowlist.py`
- `M` `src/vaultspec_a2a/api/tests/test_projection.py`
- `M` `src/vaultspec_a2a/api/tests/test_team_status_descriptor.py`
- `M` `src/vaultspec_a2a/api/tests/test_thread_deletion_saga.py`
- `M` `src/vaultspec_a2a/api/tests/test_thread_state_service.py`
- `M` `src/vaultspec_a2a/api/tests/test_thread_stream.py`
- `M` `src/vaultspec_a2a/control/cleanup/tests/test_cleanup_containment.py`
- `M` `src/vaultspec_a2a/control/repositories/tests/test_deletion_saga.py`
- `M` `src/vaultspec_a2a/control/tests/test_authoring_completion_check.py`
- `M` `src/vaultspec_a2a/control/tests/test_deleting_thread_visibility.py`
- `M` `src/vaultspec_a2a/control/tests/test_direct_control_leases.py`
- `M` `src/vaultspec_a2a/control/tests/test_direct_control_recovery.py`
- `M` `src/vaultspec_a2a/control/tests/test_dispatch_failure_transitions.py`
- `M` `src/vaultspec_a2a/control/tests/test_event_handlers.py`
- `M` `src/vaultspec_a2a/control/tests/test_list_threads_service_live.py`
- `M` `src/vaultspec_a2a/control/tests/test_permission_leases.py`
- `M` `src/vaultspec_a2a/control/tests/test_permission_rejection_journal.py`
- `M` `src/vaultspec_a2a/control/tests/test_reconciling_abandonment.py`
- `M` `src/vaultspec_a2a/control/tests/test_redispatch_failure_ladder.py`
- `M` `src/vaultspec_a2a/control/tests/test_repair_transition_map_parity.py`
- `M` `src/vaultspec_a2a/control/tests/test_stored_workspace_root_agreement.py`
- `M` `src/vaultspec_a2a/control/tests/test_terminal_sequence_capture.py`
- `M` `src/vaultspec_a2a/control/tests/test_thread_deletion_saga.py`
- `M` `src/vaultspec_a2a/control/tests/test_thread_service_tokens.py`
- `M` `src/vaultspec_a2a/control/tests/test_verdict_loop_live.py`
- `M` `src/vaultspec_a2a/control/tests/test_verdict_subscriber.py`
- `M` `src/vaultspec_a2a/control/tests/test_verdict_subscriber_live.py`
- `M` `src/vaultspec_a2a/control/thread_service.py`
- `M` `src/vaultspec_a2a/database/compatibility.py`
- `M` `src/vaultspec_a2a/database/migrate.py`
- `M` `src/vaultspec_a2a/database/migrations/env.py`
- `M` `src/vaultspec_a2a/database/models.py`
- `M` `src/vaultspec_a2a/database/tests/test_admin.py`
- `M` `src/vaultspec_a2a/database/tests/test_compatibility.py`
- `M` `src/vaultspec_a2a/database/tests/test_control_action_lease_composability.py`
- `M` `src/vaultspec_a2a/database/tests/test_control_action_leases.py`
- `M` `src/vaultspec_a2a/database/tests/test_cost_tracking.py`
- `M` `src/vaultspec_a2a/database/tests/test_database.py`
- `M` `src/vaultspec_a2a/database/tests/test_migrations.py`
- `M` `src/vaultspec_a2a/database/tests/test_permission_audit_log.py`
- `M` `src/vaultspec_a2a/database/tests/test_reconciliation.py`
- `M` `src/vaultspec_a2a/database/tests/test_reconciliation_batching.py`
- `M` `src/vaultspec_a2a/database/tests/test_reconciliation_epoch_reboot.py`
- `M` `src/vaultspec_a2a/database/tests/test_repair_journal_retention.py`
- `M` `src/vaultspec_a2a/database/tests/test_run_write_authority_model.py`
- `M` `src/vaultspec_a2a/database/tests/test_schema_integrity.py`
- `M` `src/vaultspec_a2a/database/tests/test_task_queue_repository.py`
- `M` `src/vaultspec_a2a/database/tests/test_wal_maintenance.py`
- `M` `src/vaultspec_a2a/database/tests/test_workspace_identity_seam.py`
- `M` `src/vaultspec_a2a/database/thread_repository.py`
- `M` `src/vaultspec_a2a/graph/tests/nodes/test_vault_reader.py`
- `M` `src/vaultspec_a2a/graph/tests/nodes/test_vault_write_isolation.py`
- `M` `src/vaultspec_a2a/graph/tests/nodes/test_worker_integration.py`
- `M` `src/vaultspec_a2a/graph/tests/test_task_queue.py`
- `M` `src/vaultspec_a2a/providers/tests/test_deterministic_scripts.py`
- `A` `src/vaultspec_a2a/database/migrations/versions/0017_thread_write_authority.py`
- `A` `src/vaultspec_a2a/database/tests/test_thread_write_authority_migration.py`
- `A` `src/vaultspec_a2a/tests/_write_authority.py`
- `M` `.vault/index/embedded-runtime-remediation.index.md`
- `A` `.vault/exec/2026-09-05-embedded-runtime-remediation/2026-09-05-embedded-runtime-remediation-W02-P03-S77.md`
- `verify:` `python AST explicit-authority scan` -> `pass` (259 `create_thread` calls and 13 direct `ThreadModel` seeds; zero omissions)
- `verify:` `pytest` four-case migration/compatibility/creation discriminator -> `pass` (4 tests in 15.95 seconds)
- `verify:` `pytest src/vaultspec_a2a/database/tests/test_thread_write_authority_migration.py -q` -> `pass` (6 tests in 6.66 seconds)
- `verify:` `pytest src/vaultspec_a2a/database/tests/test_run_write_authority_model.py -q` -> `pass` (15 tests in 0.17 seconds)
- `verify:` `pytest src/vaultspec_a2a/database/tests/test_compatibility.py -q` -> `fail` (15 nodes reached 100%; post-result teardown stalled and was interrupted)
- `verify:` `ruff check` on all changed Python paths -> `pass`
- `verify:` `ty check` on production and focused test paths -> `pass`
- `M` `src/vaultspec_a2a/database/compatibility.py`
- `M` `src/vaultspec_a2a/database/migrations/env.py`
- `M` `src/vaultspec_a2a/database/models.py`
- `A` `src/vaultspec_a2a/database/write_authority_schema.py`
- `A` `src/vaultspec_a2a/database/tests/_write_authority_schema_cases.py`
- `M` `src/vaultspec_a2a/database/tests/test_compatibility.py`
- `M` `src/vaultspec_a2a/database/tests/test_thread_write_authority_migration.py`
- `A` `src/vaultspec_a2a/database/tests/test_write_authority_schema.py`
- `verify:` `pytest` exact forged-schema migration-preflight discriminator -> `pass` (3 tests in 3.19 seconds)
- `verify:` `pytest` exact forged-schema read-only compatibility discriminator -> `pass` (2 tests in 2.39 seconds)
- `verify:` `pytest` canonical read-only compatibility discriminator -> `pass` (1 test in 1.14 seconds)
- `verify:` `pytest src/vaultspec_a2a/database/tests/test_write_authority_schema.py -q` -> `pass` (3 tests in 0.07 seconds)
- `M` `src/vaultspec_a2a/database/write_authority_schema.py`
- `M` `src/vaultspec_a2a/database/migrations/env.py`
- `M` `src/vaultspec_a2a/database/tests/_write_authority_schema_cases.py`
- `M` `src/vaultspec_a2a/database/tests/test_write_authority_schema.py`
- `M` `src/vaultspec_a2a/database/tests/test_compatibility.py`
- `M` `src/vaultspec_a2a/database/tests/test_thread_write_authority_migration.py`
- `verify:` `pytest src/vaultspec_a2a/database/tests/test_write_authority_schema.py -q` -> `pass` (16 tests in 0.11 seconds)
- `verify:` exact real-SQLite comment/string compatibility discriminator -> `pass` (3 tests in 11.60 seconds)
- `verify:` exact forged-schema migration-preflight discriminator -> `pass` (5 tests in 7.12 seconds)
- `verify:` exact populated-current migration discriminator -> `pass` (1 test in 1.12 seconds)
- `verify:` complete implementation/review chain `7586f2ee` -> `da7cd035` FAIL -> `9ec2396d` -> `e52bd82e` FAIL -> `48c661c2` -> `9ca08596` PASS
- `verify:` independent lexer and fingerprint gate -> `pass` (16 tests in 0.21 seconds)
- `verify:` independent forged-preflight and populated-current gate -> `pass` (6 tests in 36.76 seconds)
- `verify:` S77 lifecycle state -> `pass` (Core closed only `W02.P03.S77`; 12 of 81 Steps complete; `W02.P03.S09` next)
- `verify:` remediation and served-capability-contract Core feature checks -> `pass` (19 checks each; zero diagnostics)

## Notes

The compatibility rerun reached all 15 passing nodes and 100% before the separately queued pytest teardown stall. Session `62322` was interrupted immediately; its exact command-line process was absent. The completed four-case discriminator is the terminal pytest pass for S77.

Formal rereview `e52bd82e` found that the initial balanced extractor could count required constraint text hidden in SQLite comments. The correction lexes SQLite table DDL, excludes comments, literals and quoted identifiers from discovery and balancing, preserves actual predicate literals, and fails closed on malformed or duplicate declarations. S77 remains open for another formal rereview; the live PostgreSQL catalog evidence and test teardown findings remain open.

Formal PASS `9ca08596` accepts correction `48c661c2` and the complete S77 chain. Both HIGH schema-integrity findings are closed. Live PostgreSQL catalog and future-migration evidence remains MEDIUM/open under the locked PostgreSQL server-profile evidence follow-up. The post-result pytest teardown hang remains MEDIUM/open under `resource-aware-test-execution` in `src/vaultspec_a2a/testing`, with sessions `62322`, `96385`, and `50170` retained as evidence. Lifecycle closure adds no runtime behavior or legacy, deprecated, default, backfill, translation, alias, fallback, or compatibility path.
