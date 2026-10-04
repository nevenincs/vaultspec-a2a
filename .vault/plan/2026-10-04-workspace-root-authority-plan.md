---
tags:
  - '#plan'
  - '#workspace-root-authority'
date: '2026-10-04'
tier: L1
related:
  - '[[2026-10-04-workspace-root-authority-desktop-workspace-boundary-adr]]'
  - '[[2026-09-21-workspace-root-authority-compose-provider-boundary-adr]]'
  - '[[2026-10-04-workspace-root-authority-desktop-native-admission-adr]]'
modified: '2026-10-04'
body_schema: body-v2
body_hash: 'sha256:46d1dafcac51f58c46dec9066dda4a8487268b694c92a0abfe4e39515056e8c2'
---

# `workspace-root-authority` plan

## Description

Approved 2026-10-04
Authorization: the user requested tackling all remaining known issues after the desktop workspace-root fix, and repeatedly instructed continuation after the native fail-closed option was presented. Scope is the three follow-ups in `2026-10-04-workspace-root-authority-audit`: callback check/open races, native child filesystem authority, and concurrent ACP read verification. The accepted managed-root and Compose callback constraints govern S01. The accepted `2026-10-04-workspace-root-authority-desktop-native-admission-adr` governs S02: native desktop execution is unavailable until a proven OS isolation backend exists. This is an explicit compatibility restriction; health, lifecycle, queries, cancellation, development and Compose remain usable. ACP remediation is concurrently owned by `2026-10-04-acp-read-remediation-plan`; verify its results without overwriting shared changes.

Preserve concurrent work. The parent owns scoped implementation and verification. Scoped commits must exclude others' changes; defer a commit when shared changes cannot be safely isolated and record the exception.

## Steps

- [x] `S01` - Replace pathname callback opens with cross-platform handle-anchored regular-file I/O and real replacement proofs; `src/vaultspec_a2a/desktop/_filesystem_authority.py, src/vaultspec_a2a/providers/_acp_rpc_handlers.py, src/vaultspec_a2a/providers/tests/test_desktop_workspace_boundary.py`.
- [x] `S02` - Refuse native desktop launches until an OS isolation backend is verified, with honest readiness and refusal before execution admission; `src/vaultspec_a2a/control/provider_execution.py, src/vaultspec_a2a/providers/_subprocess.py, src/vaultspec_a2a/providers/provider_readiness.py, src/vaultspec_a2a/providers/binary_version.py, src/vaultspec_a2a/control/health.py, src/vaultspec_a2a/api/routes/_gateway_run_start.py, src/vaultspec_a2a/api/schemas/gateway_readiness.py, src/vaultspec_a2a/providers/tests/test_desktop_native_execution.py, src/vaultspec_a2a/desktop_tests/test_readiness_model.py, src/vaultspec_a2a/desktop_tests/test_run_admission.py, .vault/adr`.
- [x] `S03` - Verify the concurrent ACP repair and complete integrated review and audit queue updates; `src/vaultspec_a2a/providers/tests, .vault/audit/2026-10-04-workspace-root-authority-audit.md, .vault/exec, .vault/plan`.

## Parallelization

Execute source changes sequentially. The security-fix workflow requires a read-only independent investigation and one fresh candidate review. The concurrent ACP owner retains its protocol implementation.

## Verification

Run syntax/import, Ruff lint/format, Ty and strict Basedpyright checks before malicious triggers. Use real filesystem trees and concurrent directory or leaf replacement with admitted read/write controls. Preserve ACP line ranges, byte caps, sessions and vault-write denials. Prove armed desktop native provider, terminal and MCP commands are refused before child acquisition and private synthetic-state access, including alternate spawn modes and configured launchers. Readiness and admission must describe the restriction without reserving capacity or accepting actor credentials. Prove unarmed native process controls and existing Compose identity behavior remain functional. Desktop native sandbox certification is not claimed: future re-enablement requires private-state denial plus authentication, IPC, project behavior and a completed real provider turn for each supported target. Complete integrated review, severity/type classification, queue updates, and Core checks before reporting completion.
