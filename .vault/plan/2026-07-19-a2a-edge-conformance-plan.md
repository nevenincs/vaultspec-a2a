---
tags:
  - '#plan'
  - '#a2a-edge-conformance'
date: '2026-07-19'
modified: '2026-07-19'
tier: L1
related:
  - '[[2026-07-14-a2a-edge-conformance-adr]]'
  - '[[2026-07-19-a2a-edge-conformance-active-run-discovery-research]]'
---


# `a2a-edge-conformance` plan

Add the dashboard-requested bounded active-run discovery read to the versioned gateway.

## Description

This L1 successor executes the accepted edge-conformance decision after the dashboard's additive contract event. It reuses durable thread lifecycle and metadata truth, exposes only the minimal discovery projection needed to recover a viewing binding, and leaves the authoritative transcript/recovery state on the existing per-run status read.

## Steps

- [x] `S01` - Add the durable active-run discovery projection and metadata filters; `src/vaultspec_a2a/database/thread_repository.py, src/vaultspec_a2a/control/run_discovery_service.py`.
- [ ] `S02` - Serve the bounded v1 collection read and prove reload discovery over live HTTP; `src/vaultspec_a2a/api/schemas/gateway.py, src/vaultspec_a2a/api/routes/gateway.py, src/vaultspec_a2a/api/tests/test_active_run_discovery_live.py`.
## Parallelization

The Steps are sequential: `S02` consumes the repository/service projection delivered by `S01`. No sub-agent parallelism is useful for this two-seam change.

## Verification

- The collection read returns only durable non-terminal runs and orders them newest first.
- Exact workspace and feature filters select the intended run while terminal, foreign-workspace, malformed-metadata, and non-matching-feature rows are excluded.
- The response is versioned and capped, contains only `run_id`, `status`, and `feature_tag` per record, and reports truncation without exposing actor tokens, prompts, transcript content, or raw metadata.
- A real SQLite database and live TCP gateway prove the reload-discovery request and subsequent per-run status lookup without mocks, fakes, stubs, monkeypatches, skips, or xfails.
- Focused tests, lint, type checking, Vaultspec validation, and the mandatory code review pass all succeed; every review finding is appended to the audit queue.
