---
tags:
  - '#exec'
  - '#stream-resumption'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:d24f88cdba61da08989f6ad499fe0efe1393285f5327a0d0a3fa5722c8f42f5f'
related:
  - "[[2026-10-01-stream-resumption-plan]]"
---

# `stream-resumption` ledger

## Changes

- `S01` `M` `src/vaultspec_a2a/database/models.py`
- `S01` `A` `src/vaultspec_a2a/database/migrations/versions/0023_run_event_log.py`
- `S01` `M` `src/vaultspec_a2a/database/__init__.py`
- `S01` `M` `src/vaultspec_a2a/database/admin.py`
- `S01` `M` `src/vaultspec_a2a/database/write_authority_schema.py`
- `S01` `M` `src/vaultspec_a2a/database/tests/_backends.py`
- `S01` `A` `src/vaultspec_a2a/database/tests/test_run_event_log_schema.py`
- `S01` `M` `src/vaultspec_a2a/database/tests/test_thread_write_authority_migration.py`
- `S01` `verify:` `pytest src/vaultspec_a2a/database --require-prerequisite=postgres` -> `pass`
- `S01` `by:` `vaultspec-high-executor`
- `S02` `A` `src/vaultspec_a2a/database/run_event_repository.py`
- `S02` `M` `src/vaultspec_a2a/database/__init__.py`
- `S02` `M` `src/vaultspec_a2a/database/tests/_backends.py`
- `S02` `A` `src/vaultspec_a2a/database/tests/test_run_event_repository.py`
- `S02` `verify:` `pytest src/vaultspec_a2a/database --require-prerequisite=postgres` -> `pass`
- `S02` `by:` `vaultspec-high-executor`
- `S03` `M` `src/vaultspec_a2a/streaming/subscribers.py`
- `S03` `M` `src/vaultspec_a2a/streaming/aggregator.py`
- `S03` `M` `src/vaultspec_a2a/streaming/emitters.py`
- `S03` `M` `src/vaultspec_a2a/streaming/__init__.py`
- `S03` `A` `src/vaultspec_a2a/streaming/tests/test_run_sequence_allocation.py`
- `S03` `verify:` `pytest database streaming api --require-prerequisite=postgres` -> `pass`
- `S03` `by:` `vaultspec-high-executor`
- `S04` `A` `src/vaultspec_a2a/streaming/run_event_writer.py`
- `S04` `M` `src/vaultspec_a2a/streaming/subscribers.py`
- `S04` `M` `src/vaultspec_a2a/streaming/aggregator.py`
- `S04` `M` `src/vaultspec_a2a/streaming/__init__.py`
- `S04` `A` `src/vaultspec_a2a/api/_replay_writer_seat.py`
- `S04` `M` `src/vaultspec_a2a/api/internal.py`
- `S04` `M` `src/vaultspec_a2a/control/infra_config.py`
- `S04` `M` `.env.example`
- `S04` `A` `src/vaultspec_a2a/streaming/tests/test_run_event_writer.py`
- `S04` `A` `src/vaultspec_a2a/api/tests/test_stream_sequence_restart.py`
- `S04` `verify:` `pytest database streaming api control --require-prerequisite=postgres` -> `pass`
- `S04` `by:` `vaultspec-high-executor`
- `S05` `M` `src/vaultspec_a2a/streaming/sse_frames.py`
- `S05` `M` `src/vaultspec_a2a/api/thread_stream.py`
- `S05` `M` `src/vaultspec_a2a/streaming/tests/test_sse_frames.py`
- `S05` `A` `src/vaultspec_a2a/api/tests/_sse_reader.py`
- `S05` `A` `src/vaultspec_a2a/api/tests/test_stream_resume_id.py`
- `S05` `verify:` `pytest src/vaultspec_a2a/database src/vaultspec_a2a/streaming src/vaultspec_a2a/api --require-prerequisite=postgres` -> `pass`
- `S05` `by:` `vaultspec-high-executor`
- `S06` `M` `src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py`
- `S06` `M` `src/vaultspec_a2a/api/thread_stream.py`
- `S06` `M` `openapi.json`
- `S06` `A` `src/vaultspec_a2a/api/tests/test_stream_resume_cursor.py`
- `S06` `verify:` `pytest src/vaultspec_a2a/database src/vaultspec_a2a/streaming src/vaultspec_a2a/api --require-prerequisite=postgres` -> `pass`
- `S06` `by:` `vaultspec-high-executor`
- `S07` `M` `src/vaultspec_a2a/api/thread_stream.py`
- `S07` `M` `src/vaultspec_a2a/api/_replay_writer_seat.py`
- `S07` `M` `src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py`
- `S07` `A` `src/vaultspec_a2a/api/tests/test_stream_resume_replay.py`
- `S07` `A` `src/vaultspec_a2a/api/tests/test_stream_session_scope.py`
- `S07` `verify:` `pytest src/vaultspec_a2a/database src/vaultspec_a2a/streaming src/vaultspec_a2a/api --require-prerequisite=postgres` -> `pass`
- `S07` `by:` `vaultspec-high-executor`
- `S08` `M` `src/vaultspec_a2a/api/thread_stream.py`
- `S08` `M` `src/vaultspec_a2a/streaming/sse_frames.py`
- `S08` `A` `src/vaultspec_a2a/api/tests/test_stream_resume_gap.py`
- `S08` `verify:` `pytest src/vaultspec_a2a/database src/vaultspec_a2a/streaming src/vaultspec_a2a/api --require-prerequisite=postgres` -> `pass`
- `S08` `by:` `vaultspec-high-executor`
- `S09` `M` `src/vaultspec_a2a/api/schemas/gateway.py`
- `S09` `M` `src/vaultspec_a2a/api/routes/_gateway_read_endpoints.py`
- `S09` `M` `openapi.json`
- `S09` `A` `src/vaultspec_a2a/api/tests/test_run_status_stream_resumable.py`
- `S09` `verify:` `pytest src/vaultspec_a2a/database src/vaultspec_a2a/streaming src/vaultspec_a2a/api --require-prerequisite=postgres` -> `pass`
- `S09` `by:` `vaultspec-high-executor`
- `S10` `A` `src/vaultspec_a2a/database/run_event_retention.py`
- `S10` `M` `src/vaultspec_a2a/database/run_event_repository.py`
- `S10` `M` `src/vaultspec_a2a/control/infra_config.py`
- `S10` `M` `src/vaultspec_a2a/api/app.py`
- `S10` `A` `src/vaultspec_a2a/database/tests/test_run_event_retention.py`
- `S10` `A` `src/vaultspec_a2a/api/tests/test_replay_retention_sweep_runs.py`
- `S10` `verify:` `pytest src/vaultspec_a2a/database src/vaultspec_a2a/streaming src/vaultspec_a2a/api --require-prerequisite=postgres` -> `pass`
- `S10` `by:` `vaultspec-high-executor`
- `S11` `A` `.vault/reference/2026-10-01-stream-resumption-dashboard-contract-event-reference.md`
- `S11` `verify:` `vaultspec-core vault check all` -> `pass`
- `S10` `M` `.env.example`
- `S10` `verify:` `pytest src/vaultspec_a2a/control/tests/test_env_example_coverage.py` -> `pass`

## Notes

- `S01` Also fixed a pre-existing defect the dual-backend proof exposed: PostgreSQL 16 reflects trim() in a CHECK as TRIM(BOTH FROM ...), which the schema fingerprint did not fold, so no incremental migration past 0017 could run on Postgres.
- `S04` Path correction: the restart-continuity proof lives in api/tests, inside the covering gate, not in the Docker-gated service tier; `api/_replay_writer_seat.py` keeps the edit to the conflict-prone relay module to a few lines. The relay context was merged by hand with the prune-registry change of architecture-review P06.S42.
- `S06` An unparseable cursor is refused as `resume_cursor_foreign_run` rather than ignored, because ignoring would serve a live-only stream to a client that believes it resumed.
- `S10` Plan-close review correction: the retention bound S10 added had no operator line; the env-example coverage gate failed on the integrated tree.
