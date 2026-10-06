---
tags:
  - '#audit'
  - '#security-cloud-remediation'
date: '2026-10-06'
modified: '2026-10-06'
body_schema: 'body-v2'
body_hash: 'sha256:2e3e1695243160449f8afe4a32844599e8496a6041de16f5363c5fa8ea91bed1'
related:
  - "[[2026-10-06-security-cloud-remediation-plan]]"
---

# `security-cloud-remediation` audit: `Cloud findings and remediation review`

## Scope

October 6 Cloud scan `wfr_a27d78305fddc82937095bc549f47029af3090ad05bb73de70a75f3f2881c9f6` on `21b6f92`; current implementation and fixes under the related plan. Discovery used Core search and an all-feature ADR listing; code semantic search was unavailable because its Qdrant service is not installed, so bounded source searches and direct named modules were used.

## Findings

### claude-oauth | high | Shared environment leaks Claude OAuth across lanes

Type: credential disclosure. Status: confirmed, S01 implementing. `workspace/environment.py:119` retains the token globally; real production scrubber reproduction with a synthetic token fails the absence assertion. Independent investigator confirms Codex, ACP, MCP and terminal consumers. Preserve selected Claude ambient subscription and configured OAuth channels while stripping the common base.

### terminal-authority | high | Unisolated ACP terminals retain host filesystem authority

Type: authorization boundary. Status: confirmed, S02 pending. `_acp_rpc_terminal_handlers.py:203` accepts interpreter scripts and checks cwd only. Existing namespace authority is propagated when present, but absent authority executes with ambient host permissions. `test_native_launch_context.py` already covers isolated private-state denial and project I/O on Linux. Closure requires refusing unisolated terminal creation and withholding its advertised capability. This narrows the prior default-development exception, leaving ordinary provider launch compatibility separate.

### state-links | medium | Linked paths redirect state and journal writes

Type: filesystem integrity. Status: reported, S03 pending. Cloud finding `csf_14852935f75969f4e3276aed` targets state_layout/config, database/session and authoring/_tool_calls. Validate current paths and use real redirected-file controls.

### permission-identity | medium | Permission request IDs and effects cross thread ownership

Type: authorization isolation. Status: reported, S04 pending. Cloud finding `csf_cd9725ff6e54f8b7f5ee6482` targets worker permission hashing, request repository and event application.

### desktop-alias | medium | Linked app-home ancestors defeat capsule separation

Type: filesystem integrity. Status: reported, S05 pending. Cloud finding `csf_cf837ce03e604ff0a702ce43` targets desktop/profile path validation before state changes.

### stderr-secrets | medium | ACP debug logs retain unredacted stderr

Type: credential disclosure. Status: reported, S06 pending. Cloud finding `csf_e367d57d99237808b5d2484b` targets `_acp_stderr.py` logging before redaction.

### native-vault-write | medium | Native Claude write tools bypass protected vault policy

Type: authorization bypass. Status: reported, S07 pending. Cloud finding `csf_13f1c19a0a823694fd1338b7` targets Claude tool policy and permission mediation.

### codex-refresh | medium | Child-controlled auth JSON replaces operator credentials

Type: credential integrity. Status: reported, S08 pending. Cloud finding `csf_85229fd808cc6d427cf6e175` targets `_codex_auth.py` refresh validation and publication.

### ambient-zai | high | Adjacent Z.ai credential survives the common environment

Type: credential disclosure. Status: discovered, deferred pending bounded investigation. Independent pre-patch review notes `ANTHROPIC_AUTH_TOKEN` is not scrubbed and existing tests assert pass-through. The Claude-specific fix does not close this sibling credential family. Owner: follow-up within the credential boundary; verify Z.ai explicit reinjection and compatibility before editing.

### claude-oauth-review | low | S01 candidate closes the reported credential path

Type: verification and review record. Status: resolved. Independent fresh read-only review found no concrete bypass or regression in the five-file OAuth patch. The original synthetic-token absence assertion failed before the fix; real-child tests now confirm absence for Codex, Kimi, Z.ai, MCP and terminal environments and preserve Claude ambient subscription/configured OAuth behavior. `uv run --no-sync python -m pytest src/vaultspec_a2a/workspace/tests/test_environment.py src/vaultspec_a2a/workspace/tests/test_workspace.py src/vaultspec_a2a/providers/tests/test_claude_auth_channel.py -q`: 51 passed. Ruff check, Ruff format --check and ty check on those tests plus environment.py and factory.py passed. Windows Python locked environment. Review verdict PASS for S01. Optional subscription catalog control would extend second-seam coverage; no demonstrated defect. Cloud state remains unchanged.

### claude-live-test-selection | low | Live setup fixtures relied on global OAuth inheritance

Type: test compatibility. Status: fixed in S01 follow-up. Final caller inspection found test_acp_catalog_live.py and test_acp_authoring_bridge.py constructing a raw common environment while assuming Claude OAuth survived. They now use the same explicit claude_auth_env selector as served Claude roots. Focused Ruff lint/format and ty passed; actual live catalog and authoring-bridge service tests passed (4 tests). No production scope expansion or new credential channel.

## Recommendations

Complete each original finding with real trigger and legitimate-control proof, then independent patch review and recorded verification. Reconcile terminal availability with the native-admission decision before changing its default-development exception. Do not claim platform certification from Windows refusal tests.
