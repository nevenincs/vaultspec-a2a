---
tags:
  - '#audit'
  - '#security-cloud-remediation'
date: '2026-10-06'
modified: '2026-10-06'
body_schema: 'body-v2'
body_hash: 'sha256:d980d0176a3c1ee5c5299cc383e0d5a7cd6db1fc2d72a45d4056fc6a69e947eb'
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

### terminal-review | low | S02 closes unisolated terminal creation without losing isolated operation

Type: verification and review record. Status: resolved. Independent fresh read-only review traced negotiation, dispatch, creation, shared spawn and Linux namespace acquisition and found no concrete bypass or production regression. Missing authority, cross-workspace authority and replaced filesystem identity refuse; namespace-controlled project writes still succeed while private-state reads fail with ENOENT. The real installed SDK verifies initialize withholds terminal and a direct terminal/create still refuses. Large-output isolated controls verify zero, small and oversized requested caps, including the production server clamp.

Windows focused terminal/security/native-refusal/output/ownership/lifecycle suite initially had 212 passes and one invalid-environment error-order regression. Restoring environment validation before isolation preserves the prior error. Focused security plus new refusal tests then passed 47/47; retained-output tests after final setup adjustment passed 19/19. Explicit SDK and containment service controls passed 2/2. Other original passing results remain applicable. Ruff lint/format and ty passed on all ten changed terminal Python files. A separate Linux environment created with uv sync --locked --python 3.13 --group tooling passed the actual namespace test with the capsule-builder static bubblewrap helper, including final stale-authority and large-output controls. An older Linux environment failed import before tests and was replaced with the locked environment; it supplies no proof. Review verdict PASS for S02; no target eligibility was changed.

### terminal-test-setup | low | Lifecycle controls must start below the newly refused admission boundary

Type: test compatibility. Status: fixed. Existing unisolated output/ownership/cleanup tests created terminals through terminal/create. Their setup now retains real processes using the production spawn and output-capture helpers; they continue exercising real handlers and cleanup without a test bypass of admission. Admission itself is exercised by explicit unisolated refusal, SDK negotiation/refusal and real isolated Linux controls. No mocks, skips or fallback execution added.

### medium-model-selection | low | Requested worker model is unavailable

Type: execution prerequisite. Status: pending user input. The user requested sol 5.1 at xhigh; that model is absent from the agent runtime. An asynchronous question offers gpt-5.6-sol, gpt-6.1-sol or gpt-6-sol at xhigh. No medium remediation worker has been launched under a substituted model. S03-S08 remain open; their source files are untouched.

### ambient-zai-resolution | high | Z.ai ambient credentials isolated to the selected lane

Type: credential disclosure. Status: fixed in S09, superseding the deferred ambient-zai entry. The shared scrubber now removes ANTHROPIC_AUTH_TOKEN, ANTHROPIC_BASE_URL, ZAI_AUTH_TOKEN, ZAI_API_KEY, ZAI_BASE_URL and ZAI_ANTHROPIC_BASE_URL case-insensitively. Existing Settings selection and explicit Z.ai factory overlay preserve selected credentials; absent or blank selected tokens cannot inherit ambient credentials. Real child controls cover Claude, Codex, Kimi, MCP and terminal bases. No provider eligibility was expanded.

### version-probe-credentials | high | Version subprocess bypassed the credential scrubber

Type: credential disclosure. Status: discovered and fixed in S09. Independent bounded investigation found binary_version.py supplied environment=None to both launch preparation paths. Both now receive the scrubbed environment. A real executable refuses ambient credential aliases, requires a safe inherited option and reports its version; the control passes on Windows and Linux. Native isolation retains deliberately selected provider auth without restoring removed aliases.

### zai-contract-drift | low | Tests and comments asserted global Z.ai inheritance

Type: test and documentation contract drift. Status: fixed in S09. Workspace tests now require absence and include all aliases; factory and ACP comments describe explicit selected-provider reinjection. MCP real probe controls include the six aliases and Claude OAuth.

### zai-review | low | S09 implementation review and verification

Type: verification and review record. Status: resolved. Fresh read-only candidate review found no concrete surviving bypass or regression across shared environment, selected Z.ai overlay, catalog, MCP, terminal, version cache and native launch paths. Supervisor verification supplies the checks deliberately not run by the reviewer: Windows combined environment/workspace/Z.ai/version/factory/Claude/settings tests yielded 131 passes and one unrelated baseline failure recorded below; focused Z.ai factory tests passed 6; real MCP security probes passed 3. Linux locked-environment Z.ai controls and isolated version-cache authority control passed 16. Ruff lint, format and ty passed on all seven changed Python files; git diff --check passed. Original pre-fix real-child controls failed, establishing the trigger. Review verdict PASS for S09 with the unrelated environment limitation retained. Cloud finding state unchanged.

### codex-installed-proof-range | low | Installed Codex version blocks an unrelated factory control

Type: verification environment prerequisite. Status: open follow-up. test_factory_applies_exact_codex_model_scoped_controls fails BINARY_OUT_OF_PROOF_RANGE with installed Codex 0.160.0. A detached clean worktree at pre-S09 commit 64fb0ea2 reproduces the same failure using the locked Windows environment. Baseline and patched version probes both report 0.160.0. Restore a binary within existing completed-turn proof coverage, or establish new proof through the authorized eligibility workflow, before using this factory control as passing evidence. No test or eligibility rule was weakened.

## Recommendations

Complete each original finding with real trigger and legitimate-control proof, then independent patch review and recorded verification. Reconcile terminal availability with the native-admission decision before changing its default-development exception. Do not claim platform certification from Windows refusal tests.
