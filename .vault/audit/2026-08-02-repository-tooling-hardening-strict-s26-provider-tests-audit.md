---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:8a96ea94a9b786161c3d0dd4be9a64983411caf9b9ff289ef4081490784b4c1c'
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

## Recommendations

- Provision a healthy loopback service-discovery record, then run the named engine-backed stdio service lane and append the outcome to this audit before declaring S26 fully runtime-proven.
- Correct the terminal containment contract under a dedicated Terra change that applies the accepted ACP v1 request, response, and lifetime decision to production and real wire probes.
- Preserve the direct structural assertions and the explicit service-marker policy in subsequent test repairs; do not replace either with textual assertions or skip-based fallbacks.
- Include all S26 changed provider-test files in the post-merge strict census before checking `W06.P12.S26` complete.
