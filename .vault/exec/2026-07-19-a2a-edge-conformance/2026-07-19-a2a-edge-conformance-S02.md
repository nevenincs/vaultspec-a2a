---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S02'
related:
  - "[[2026-07-19-a2a-edge-conformance-plan]]"
---

# `a2a-edge-conformance` `S02` - Serve the bounded v1 collection read and prove reload discovery over live HTTP

## Scope

- `src/vaultspec_a2a/api/schemas/gateway.py`
- `src/vaultspec_a2a/api/routes/gateway.py`
- `src/vaultspec_a2a/api/tests/test_active_run_discovery_live.py`
- `src/vaultspec_a2a/control/run_discovery_service.py`
- `src/vaultspec_a2a/database/thread_repository.py`

## Description

- Add versioned active-run record and bounded collection response models.
- Serve `GET /v1/runs` with the sole `active` state, optional exact workspace and feature selectors, and a 1-to-100 result cap.
- Reject relative workspaces and invalid state or limit selectors before repository work.
- Skip malformed metadata, unknown persisted lifecycle values, and overlong legacy identities instead of failing response validation.
- Read a narrow projection through 100-row keyset pages with a hard 1,000-row scan budget; return `truncated=true` when a response cap or scan budget leaves candidates unseen.
- Bound raw durable metadata before parsing, tolerate JSON recursion failures, and resolve cached filesystem identity comparisons off the async request loop.
- Prove discovery, truncation, filtering, pathological metadata handling, scan-budget behavior, safe field disclosure, and the follow-up authoritative status lookup over a live TCP gateway booted through the production application lifespan.

## Outcome

The dashboard can recover a viewing binding after reload by discovering matching durable active runs and then requesting the existing authoritative per-run recovery snapshot. The discovery response carries only `api_version`, state, capped run identity records, and a truncation signal; it exposes no transcript, prompt, token, actor credential, topology, or raw metadata.

The first formal review required revision because the response cap still sat above an unbounded ORM materialization, deeply nested metadata could raise `RecursionError`, and the live test replaced production lifespan wiring. The revision closes all three: narrow keyset projection plus a hard scan budget, database-side metadata prefixing plus raw-size and recursion guards, and a subprocess proof of the normally booted installed gateway using isolated real SQLite and checkpointer files. A follow-up review caught and closed full-Text transfer before the raw-size guard; the query now materializes at most 16,385 metadata characters per row. The live proof also asserts that resident capability publication contains `GET /v1/runs`.

Validation passed after revision: Ruff lint and format checks; `ty` static checking; 51 combined discovery, schema, and five-verb acceptance tests; and 17 unaffected adjacent live gateway tests.

## Notes

The full adjacent gateway suite has one unrelated existing failure: the bundled preset now serves a `kimi` profile while `test_presets_list_is_truthful_and_resilient` still expects the prior four-profile set. The implementation did not modify that preset or expectation; the finding is carried to the review audit queue.
