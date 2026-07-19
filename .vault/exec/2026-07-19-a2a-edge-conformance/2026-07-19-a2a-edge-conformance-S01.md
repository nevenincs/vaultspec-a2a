---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S01'
related:
  - "[[2026-07-19-a2a-edge-conformance-plan]]"
---
# `a2a-edge-conformance` `S01` - Add the durable active-run discovery projection and metadata filters

## Scope

- `src/vaultspec_a2a/database/thread_repository.py`
- `src/vaultspec_a2a/control/run_discovery_service.py`

## Description

- Add a dedicated non-terminal repository read ordered newest first without changing startup reconciliation ordering.
- Project only durable run identity, lifecycle status, and feature tag.
- Parse persisted metadata defensively and exclude malformed records.
- Normalize workspace identities before exact matching and apply exact feature matching.
- Enforce a 100-result service ceiling and return a truncation signal when additional matches exist.

## Outcome

The read-side service can rediscover active runs globally or by workspace and feature while preserving the authoritative per-run recovery boundary. No schema, migration, actor persistence, or write path changed.

Validation passed: Ruff lint and format checks, `ty` static checking, and a real file-backed SQLite probe covering newest-first ordering, active/terminal partitioning, workspace and feature filters, malformed metadata, and truncation.

## Notes

Actor filtering remains intentionally unavailable because the current contract persists no stable non-secret actor identity and actor tokens are runtime-only.
