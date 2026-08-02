---
tags:
  - '#exec'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:ef3723ea223a0cffbbd54b2e528f3c25a71b39f6c3a50b7d92a75d058f0c84c1'
step_id: 'S05'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---
# Implement authenticated OpenAI-compatible model discovery with unsupported metadata explicitly absent

## Scope

- `src/vaultspec_a2a/providers/openai_catalog.py`
- `src/vaultspec_a2a/providers/tests/test_openai_catalog.py`
- `.vault/reference/2026-08-02-provider-model-catalog-reference.md`

## Description

- Add caller-bound OpenAI-compatible model discovery that performs one authenticated `GET /models` request and never invokes a model.
- Derive only the same-origin models endpoint, require HTTPS except loopback, refuse redirects, and emit static redacted failures.
- Require one exact HTTP 200 complete-list response and refuse partial content, HTTP or JSON pagination signals, malformed discriminators, oversized bodies, excessive models, unsafe identifiers, credentials, and timeouts.
- Normalize only sorted opaque provider model identifiers; keep descriptions, capabilities, controls, reasoning levels, ownership, and creation metadata absent.
- Prove structured authentication, bounds, pagination refusal, and network cleanup with real local TCP behavior.
- Correct the OpenAI model-list schema and intentional projection boundary in the feature reference.

## Outcome

The focused lane passes twenty-six direct and real-HTTP tests. Coverage includes exact path and bearer transmission, authenticated success, 401 unauthenticated evidence, 403 unknown evidence, unsupported metadata absence, deterministic ordering, response/model/identifier/key bounds, exact-200 enforcement, redirect and pagination refusal, static redaction, finite timeout validation, and behavioral TCP closure on timeout and cancellation. Ruff, Basedpyright, and ty pass on the owned files.

Reference audit surfaced one high partial-content defect and medium pagination/discriminator and non-finite-timeout defects. Independent review then found one high non-ASCII credential exception leak and one medium discarded-schema validation gap. Every finding was remediated, directly covered, and recorded with the SDK-only collision and reference wording drift in the S05 audit. Independent closure re-review returned PASS with no remaining S05 findings.

## Notes

No external provider endpoint, paid request, response, thread, or completion was invoked. P01.S06 must register only independently verified execution-mode endpoints. Catalog authentication remains distinct from later completed-turn admission. Peer worktree changes were neither staged nor altered.
