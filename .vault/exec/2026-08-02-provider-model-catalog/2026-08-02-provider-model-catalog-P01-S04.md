---
tags:
  - '#exec'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:3ae5000e633f999d280ac8a0d090f1d10df661feb190a1ad9d99c6fe840d54f9'
step_id: 'S04'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---
# Implement Kimi configured-lane model and thinking-control discovery against the installed CLI contract

## Scope

- `src/vaultspec_a2a/providers/kimi_catalog.py`
- `src/vaultspec_a2a/providers/tests/test_kimi_catalog.py`

## Description

- Discover configured model aliases through fixed prompt-free `kimi provider list --json` execution.
- Normalize CLI aliases, safe display metadata, capabilities, and advertised thinking efforts without retaining provider records.
- Bind thinking controls to their originating model and include hidden provider and wire-target drift in catalog revision identity.
- Bound aggregate stdout and stderr, drain both concurrently, and independently reap process resources on success, failure, timeout, and cancellation.
- Prove normalization and installed-runtime behavior without a completion or network call.

## Outcome

Implemented Kimi configured-lane discovery with truthful `AVAILABLE` and `UNAVAILABLE` states and deliberately `UNKNOWN` authentication. Seven direct tests and seven service tests pass. The service lane proves configured and unconfigured installed-CLI enumeration, dual-stream output above pipe capacity, shared-budget exhaustion, timeout, cancellation, static command failure, and process-tree reaping. Ruff, Basedpyright, and ty pass on the owned files.

Independent review initially reported one medium test-integrity gap for missing real-process dual-stream, aggregate-budget, and timeout proofs. Those proofs were added and closure re-review returned PASS with no remaining S04 implementation findings.

## Notes

The installed CLI recognizes `KIMI_MODEL_API_KEY` and `KIMI_MODEL_BASE_URL` for its temporary configured lane, while the existing factory and readiness code use the older `KIMI_API_KEY` and `KIMI_BASE_URL` contract. This medium integration drift is recorded open in the rolling audit and assigned to S06; it was not widened into S04. Prompt-free catalog enumeration does not establish completed-turn admission.
