---
tags:
  - '#exec'
  - '#stream-resumption'
date: '2026-10-01'
modified: '2026-10-01'
body_schema: 'body-v2'
body_hash: 'sha256:5e19d35c81614a0c4c804354817017cf919b6745c9a0221f3f64994250344a2d'
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

## Notes

- `S01` Also fixed a pre-existing defect the dual-backend proof exposed: PostgreSQL 16 reflects trim() in a CHECK as TRIM(BOTH FROM ...), which the schema fingerprint did not fold, so no incremental migration past 0017 could run on Postgres.
- `S04` Path correction: the restart-continuity proof lives in api/tests, inside the covering gate, not in the Docker-gated service tier; `api/_replay_writer_seat.py` keeps the edit to the conflict-prone relay module to a few lines. The relay context was merged by hand with the prune-registry change of architecture-review P06.S42.
