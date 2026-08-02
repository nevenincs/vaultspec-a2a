---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:5ee45b5fdfe67edfa254c927968ad756e297ebd5a9903f8dc62987491add3946'
related: []
---
# `repository-tooling-hardening` audit: `Deterministic and mock provider contract review`

## Scope

Independent read-only P25-F review of `src/vaultspec_a2a/providers/deterministic_chat_model.py` and `src/vaultspec_a2a/providers/mock_chat_model.py`. The review covered the removal of custom `Any` constructors and private Pydantic state, excluded runtime attachment fields, `MockChatModel` model and tape-route precedence, callback non-use, strict JSON ingress and egress, message-role encoding, SSE parsing, tool-call chunk narrowing, error propagation, and deterministic role output.

Both runtime attachments are ordinary excluded Pydantic fields and no custom initializer remains. Explicit `model_name` and `base_url` survive when no configured VidaiMock base is present; an explicit `MOCK_API_BASE` correctly owns the deployment route and derives it from the agent identifier. No path reads or invokes `permission_callback`. Every outbound message, override, and aggregate request passes the recursive JSON boundary before `httpx` receives it; every SSE record is validated before extraction. Human, assistant, system, tool, and `ChatMessage` values have intentional roles, unsupported messages fail closed, and malformed SSE records are discarded while transport/status errors propagate. Deterministic role content remains solely a function of the resolved agent role, feature tag, and topic.

Validation: focused Basedpyright reported 0 errors/warnings/notes; Ty, Ruff check, Ruff format check, and `git diff --check` passed. The direct provider suite passed 15 tests. The mandatory deterministic research-to-ADR service lane was attempted but truthfully skipped because this workspace has no reachable loopback engine, A2A gateway, and worker; it is therefore unverified here, not reported as passing. One existing Python 3.13 `importlib.metadata` deprecation warning remained.

## Findings

No material production defect was found in the two-file P25-F scope.

### deterministic-mock-boundary-regression-coverage | low | New strict wire behaviors lack direct regression probes

Status: open; deferred to `W06.P12.S26`, whose approved scope owns provider and service tests. The existing 15 focused tests preserve deterministic role output and isolated chunk helpers, but they do not drive the new Pydantic initialization precedence, excluded attachment serialization, unsupported-message refusal, JSON override rejection, real SSE text-plus-tool emission, malformed-SSE continuation, or HTTP error propagation. The service proof could not run in the current environment. These are externally meaningful boundary behaviors, so a later permissive refactor could regress them without a focused failure even though the source currently enforces each invariant.

### real-worker-service-evidence | low | Initial service-evidence gap is resolved by a fresh real-stack completion

Status: resolved. Fresh root reproduction ran `src/vaultspec_a2a/service_tests/test_real_worker_run_completion.py` under the service marker and passed one real worker completion in 23.31 seconds. That current stack evidence supersedes the earlier unavailable-stack qualification in this audit; no source changed. It does not remove the separate S26 regression-coverage finding, which concerns direct model-wire behavior rather than basic real-worker completion.

## Recommendations

In `W06.P12.S26`, add real behavior tests using the actual model construction and an actual loopback HTTP/SSE server: cover explicit versus agent and configured-base routing, excluded runtime attachment serialization, each supported message role plus refusal of unsupported message classes, non-JSON request rejection, text and tool chunk emission, malformed-record continuation, and propagated HTTP failure. Re-run the deterministic research-to-ADR service lane on a reachable stack and retain the result as separate end-to-end evidence.

The mandatory real-worker service proof is now satisfied. Retain the remaining S26 recommendation for direct strict-wire regressions; an additional research-to-ADR topology run remains useful evidence but is not needed to correct the resolved service-evidence finding.
