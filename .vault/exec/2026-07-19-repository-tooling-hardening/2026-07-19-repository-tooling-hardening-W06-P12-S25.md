---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:daf79147402df4a2a7b33c307ee95dbeedca5c69c557ceb0f448cdf14b479e02'
step_id: 'S25'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---
# Repair strict types in the provider and ACP production domains.

## Scope

- `src/vaultspec_a2a/providers`
- `src/vaultspec_a2a/desktop/profile.py`
- `src/vaultspec_a2a/desktop/tests/test_profile.py`
- `src/vaultspec_a2a/desktop_tests/test_profile_paths.py`
- `src/vaultspec_a2a/cli/tests/test_desktop_serve.py`
- `src/vaultspec_a2a/desktop_tests/test_owned_process_tree.py`

## Description

- Hardened Gemini credential ingress and cross-process refresh transactions.
- Defined canonical provider JSON, MCP, Codex, project-projection, deterministic, mock, profile, and ACP wire contracts.
- Removed false private cross-module factory interfaces and migrated consumers directly to canonical helpers.
- Repaired every implementation-review finding before accepting each production tranche.
- Ran independent audits for every implementation pass and recorded deferred test-domain and protocol compatibility work.

## Outcome

The authoritative non-test provider census reports 0 Basedpyright errors and 0 warnings across every production provider module. Ty passes across the same census. Focused real behavior evidence covers filesystem credentials and cross-process locks, MCP handshake and ownership projection, Codex subprocess/config delivery, deterministic real-worker completion, profile persistence/readiness, ACP containment, and real Claude and Kimi handshakes.

## Notes

Provider test static debt remains assigned to S26, including friend-test private-use configuration and untyped legacy fixtures. The ACP terminal/filesystem wire compatibility drift requires an ADR-backed S26 decision; it was deliberately not recast as type success. Some combined large-suite invocations timed out, so their evidence is unverified; bounded constituent lanes passed and are recorded in their audits.
