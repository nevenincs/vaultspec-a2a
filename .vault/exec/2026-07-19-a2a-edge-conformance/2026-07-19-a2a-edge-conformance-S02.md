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

## Description

- Add versioned active-run record and bounded collection response models.
- Serve `GET /v1/runs` with the sole `active` state, optional exact workspace and feature selectors, and a 1-to-100 result cap.
- Reject relative workspaces and invalid state or limit selectors before repository work.
- Skip malformed metadata, unknown persisted lifecycle values, and overlong legacy identities instead of failing response validation.
- Prove discovery, truncation, filtering, safe field disclosure, and the follow-up authoritative status lookup over a live TCP gateway.

## Outcome

The dashboard can recover a viewing binding after reload by discovering matching durable active runs and then requesting the existing authoritative per-run recovery snapshot. The discovery response carries only `api_version`, state, capped run identity records, and a truncation signal; it exposes no transcript, prompt, token, actor credential, topology, or raw metadata.

Validation passed: Ruff lint and format checks, `ty` static checking, 2 new live contract tests, 17 unaffected gateway live tests, 47 schema tests, 2 five-verb acceptance regressions, and the stale-resident doctor route test.

## Notes

The full adjacent gateway suite has one unrelated existing failure: the bundled preset now serves a `kimi` profile while `test_presets_list_is_truthful_and_resilient` still expects the prior four-profile set. The implementation did not modify that preset or expectation; the finding is carried to the review audit queue.
