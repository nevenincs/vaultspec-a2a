---
tags:
  - '#plan'
  - '#security-cloud-remediation'
date: '2026-10-06'
tier: L1
related:
  - '[[2026-10-04-workspace-root-authority-desktop-native-admission-adr]]'
  - '[[2026-10-05-desktop-native-isolation-linux-namespace-backend-adr]]'
  - '[[2026-09-23-project-bound-state-adr]]'
  - '[[2026-10-01-tool-permission-model-adr]]'
  - '[[2026-07-16-authoring-contract-adr]]'
  - '[[2026-10-01-provider-binary-policy-adr]]'
modified: '2026-10-06'
body_schema: body-v2
body_hash: 'sha256:05f253c6e2f10e050b14568e830de358c6cdffb95d348a0b20dfac4e3ba0cad7'
---

# `security-cloud-remediation` plan

## Description

Approved 2026-10-06. The user explicitly requested delegated remediation of all six medium findings from the latest Cloud scan and personal implementation by the supervising agent of the two high findings. Scan `wfr_a27d78305fddc82937095bc549f47029af3090ad05bb73de70a75f3f2881c9f6`, revision `21b6f92ec53c32c1cb3a35f07ca2fb5912201d71`, supplies the initial evidence. Validate each finding against current code before changing it.

Reuse accepted native admission and Linux backend decisions for credential and terminal boundaries, project-bound state for filesystem storage, tool-permission-model for run-owned permission state and native write mediation, and authoring-contract for protected document writes. These are repairs to settled boundaries; do not introduce new provider eligibility, schema architecture or platform support. Escalate a distinct costly choice only if investigation demonstrates it is required. Workers read their governing records and callers before implementation. Existing unrelated plans remain unchanged.

The user's subsequent explicit instruction "fix the leak" on 2026-10-06 authorizes S09, the adjacent ambient Z.ai credential disclosure recorded in the audit. The supervisor owns its implementation under the existing provider credential boundary; it does not wait on the unresolved medium-worker model selection.

The user's 2026-10-06 correction that Codex should not fail authorizes S10 to resolve the recorded Codex verification prerequisite. Reuse accepted provider-binary-policy D2: establish a real turn on the resolved binary, refresh its recorded version and next-minor range, and align the CI pin and boundary controls. The supervisor owns this scoped proof refresh. Semantic code discovery remains unavailable because managed Qdrant is missing; named admission, factory, version and cited live-test modules supply bounded source grounding. No new architecture decision is needed.

The user additionally requested removing release-specific version numbers from tests to avoid recurring maintenance. S10 therefore derives admission controls from the declared proof, compares live persisted identity with the actual resolved binary version, and makes synthetic probe/database fixtures independent of Codex releases.

The user requested fixing failed CI after the authorized push. S11 addresses Full Validation run 37436892926: build-only desktop._linux_runtime_assets is unreachable from installed entry points. Move capsule staging into repository build tooling and update its real build/test consumers under the existing Linux isolation decision. Preserve the runtime boundary and zero-findings gate. Commit and push the correction under the continuing publication authorization, then inspect replacement CI.

The same CI-fix authorization covers S12 after replacement run 37443284479 passed all lint checks and failed dependency auditing: Mako 1.4.1 is affected by GHSA-5639-2j2p-m4mx, fixed upstream in 1.4.2. Update only the transitive lock entry under existing dependency policy; validate the live audit and Alembic migration compatibility. No new dependency strategy or advisory suppression is introduced.

S13 continues the authorized CI repair after run 37444176601 passed lint, dependency audit and vault checks but failed the storage-anchor harness gate. Use the existing registered credential accessor with an explicit process environment for ambient Claude subscription auth, preserving exclusion of file/settings values; consolidate the duplicated Codex login-source home resolver under its existing external-tool-home authority. No new suppression or exception is introduced; moving the existing justified Codex source-home exception consolidates the same allowed read.

## Steps

- [x] `S01` - Scope Claude OAuth to its selected root process and prove cross-provider non-interference; `workspace/environment.py, providers/factory.py and focused credential tests`.
- [x] `S02` - Refuse ACP terminal creation without validated workspace-bound native isolation; `providers/_acp_rpc_terminal_handlers.py, capability negotiation and terminal tests`.
- [ ] `S03` - Reject linked state ancestors and SQLite or authoring journal leaves; `control/state_layout.py, config.py, database/session.py, authoring/_tool_calls.py and tests`.
- [ ] `S04` - Bind permission identities and resolutions to their owning thread; `graph/nodes/_worker_permissions.py, database/permission_repository.py, control/_event_application.py and tests`.
- [ ] `S05` - Reject linked desktop app-home aliases into protected capsule paths; `desktop/profile.py and tests`.
- [ ] `S06` - Redact ACP stderr before every log and retention sink; `providers/_acp_stderr.py and tests`.
- [ ] `S07` - Enforce vault write prohibition for Claude native writes; `providers/_claude_tool_policy.py, required mediation seams and tests`.
- [ ] `S08` - Validate Codex credential refresh before publishing operator auth; `providers/_codex_auth.py, _codex_config_home.py and tests`.
- [x] `S09` - Remove ambient Z.ai credentials and gateway overrides from shared child environments while preserving selected Z.ai auth; `workspace/environment.py, provider credential and version-probe seams, focused environment/auth and MCP tests`.
- [x] `S10` - Refresh Codex binary proof after a real completed turn and restore factory verification; `providers/lane_admission.py, binary admission and version tests, provider and graph live identity tests, worker identity tests, .github/workflows/test.yml`.
- [x] `S11` - Move build-only Linux isolation staging out of shipped runtime and restore CI reachability; `desktop/_linux_runtime_assets.py, scripts/build_linux_isolation.py, desktop and provider native isolation test imports`.
- [x] `S12` - Update vulnerable transitive Mako lock to the patched release and verify CI dependency audit; `uv.lock and focused migration compatibility checks`.
- [x] `S13` - Route Claude ambient auth through its registered process-only accessor and share Codex credential-home resolution; `providers/factory.py, _codex_config_home.py, codex_chat_model.py and auth/home tests`.

## Parallelization

S01 and S02 belong to the supervisor. S03 (state and journal paths), S04 (permission ownership), S05 (desktop path separation), S06 (stderr redaction), S07 (native vault writes), and S08 (Codex credential refresh) may be delegated with disjoint source/test ownership. S03 and S05 serialize any shared filesystem helper changes. S07 coordinates with the supervisor before changing ACP session or RPC handlers. Workers never edit shared plan, audit, ledger or index files and never stage or commit; the supervisor serializes those operations and owns integrated checks and final review. The requested worker model requires clarification because sol 5.1 is unavailable. Security investigation and review agents remain read-only.

## Verification

Exercise original triggers, an alternate malicious input and legitimate behavior through real production boundaries with real filesystem, database or subprocess tests. No test doubles, skips or weakened assertions. Run focused locked-environment pytest, Ruff format/lint and type checks; reuse unchanged evidence. Review the integrated actual diff, classify every finding by severity/type/status, record all findings in the rolling audit, then log and close verified Steps through Core and commit each cohesive Step. Do not mark Cloud findings closed or start new scans.
