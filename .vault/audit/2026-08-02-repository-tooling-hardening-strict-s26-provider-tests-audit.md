---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:8b00cf662d7ff9e2fdacbd39b2a74bbe35023cefe978de01f8a9389954019a5c'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---
# `repository-tooling-hardening` audit: `S26 provider and service test typing`

## Scope

Review the S26 test-only repair across the provider test domain, its explicit service probes, and the shared registration changes in `conftest.py`. The acceptance bar is strict static cleanliness with real runtime construction, no test doubles or skip-based evasion, and a default-deselected service lane that fails clearly when its named prerequisite is unavailable. Parent plan: `2026-07-19-repository-tooling-hardening-plan`, step `W06.P12.S26`.

## Findings

### test-assertion-strength | low | resolved before review closure

The MCP identity and egress assertions had become raw substring checks while untyped JSON parsing was removed. The implementer restored `TypeAdapter[JsonObject]` parsing with runtime object narrowing, so the tests again verify the emitted closed JSON structure rather than formatting. Revalidated with Basedpyright, Ty, Ruff, format, and 42 focused tests; no follow-up remains. `src/vaultspec_a2a/providers/tests/test_acp_mcp_egress_axis.py`, `src/vaultspec_a2a/providers/tests/test_mcp_duplicate_identity.py`.

### loopback-service-proof | medium | open validation boundary

The engine-backed authoring stdio bridge correctly fails under the explicit `loopback-stack` prerequisite because no healthy service-discovery record is available. It does not skip or xfail, so test selection is honest; nevertheless, this exact provider-to-engine path remains unverified until a healthy loopback stack is provisioned and the named service lane passes. `src/vaultspec_a2a/providers/tests/test_authoring_stdio_bridge.py`.

### strict-test-contracts | low | resolved

The reviewed provider-test partitions have no open static, formatting, forbidden-pattern, or default/service lane defect in their stated evidence boundaries. The MCP partition reports Basedpyright zero, Ty/Ruff/format clean, 206 default tests, four explicit service tests, and a 42-test final recheck. The ACP-runtime partition reports Basedpyright zero, Ty/Ruff/format clean, 134 default tests with six service deselections, and four available service tests. External Python 3.13 `importlib.metadata` deprecation warnings do not originate in the changed test code.

### acp-v1-terminal-wire | medium | open contract drift

`test_terminal_containment.py` still asserts the legacy terminal payload and lifetime: a top-level `exitCode`, scalar `exitStatus`, and a kill operation that removes the terminal identity. That contradicts the accepted ACP v1 wire decision, whose exit statuses are objects and whose killed terminal remains addressable until release. This is an S26 test-contract defect: it can reward obsolete behaviour and block the required production migration. `src/vaultspec_a2a/providers/tests/test_terminal_containment.py:225-245`; `2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-adr`.


### dashboard-engine-lost-ack | low | open validation boundary

The strict cleanup of the lost-ack relay, shared prerequisite registry, and live gateway helper has no review defect: scoped Basedpyright, Ty, Ruff, format, and prerequisite tests pass, and the relay forwards real traffic without manufacturing application responses. The actual dashboard-engine lost-ack proof remains unexecuted because `VAULTSPEC_ENGINE_SERVE_CMD` is absent; the named prerequisite intentionally skips by default and fails pre-collection when declared. Provision the engine command and rerun the named service probe before treating the cross-repository runtime contract as proven. `src/vaultspec_a2a/service_tests/test_engine_broker_lost_ack_live.py`.

### clarification-loop-engine-proof | low | open validation boundary

The clarification-loop service test now decodes its real HTTP and SSE payloads through fail-closed structural readers and retains the production preset, run-status, SSE, answer, and resumed-graph assertions. Focused static gates are clean and independent review found no shortcut. Both runtime cases remain unproven because no reachable engine discovery record exists after the production-style retry probe. Provision that named engine prerequisite and rerun this module before claiming real-process clarification evidence. `src/vaultspec_a2a/service_tests/test_clarification_loop_stitched.py`.

### compose-stream-auth-proof | low | open validation boundary

The stream-followup test now fails closed at each real compose HTTP/SSE read boundary and focused static gates plus independent review are clean. Its compose-backed runtime path is unverified because `POST /v1/runs` returns 401 in `ServiceStack.create_thread` before the changed reader or any stream assertion executes. Diagnose the stack authentication contract in its owner before using this test as stream/resume evidence; do not weaken the test or bypass authentication. `src/vaultspec_a2a/service_tests/harness.py:692`; `src/vaultspec_a2a/service_tests/test_stream_followup.py`.

### compose-permission-auth-proof | low | open validation boundary

The permissions/resume test now narrows every real service payload at its boundary while retaining approval, denial, invalid-option, stale-response, and supervisor paths. Focused static gates and independent review are clean. The selected compose run again fails with 401 from `ServiceStack.create_thread` before its first changed reader; this corroborates the existing shared harness-auth boundary rather than a file-local regression. Repair and prove the run-start authentication path in its owner before certifying these permission scenarios. `src/vaultspec_a2a/service_tests/harness.py:692`; `src/vaultspec_a2a/service_tests/test_permissions_resume.py`.
## Recommendations

- Provision a healthy loopback service-discovery record, then run the named engine-backed stdio service lane and append the outcome to this audit before declaring S26 fully runtime-proven.
- Correct the terminal containment contract under a dedicated Terra change that applies the accepted ACP v1 request, response, and lifetime decision to production and real wire probes.
- Preserve the direct structural assertions and the explicit service-marker policy in subsequent test repairs; do not replace either with textual assertions or skip-based fallbacks.
- Include all S26 changed provider-test files in the post-merge strict census before checking `W06.P12.S26` complete.
