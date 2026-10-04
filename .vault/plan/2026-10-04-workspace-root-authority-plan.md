---
tags:
  - '#plan'
  - '#workspace-root-authority'
date: '2026-10-04'
tier: L1
related:
  - '[[2026-10-04-workspace-root-authority-desktop-workspace-boundary-adr]]'
  - '[[2026-09-21-workspace-root-authority-compose-provider-boundary-adr]]'
modified: '2026-10-04'
body_schema: body-v2
body_hash: 'sha256:f9f2a0c28ceae370940d94065c54663615784ef93bb6dfad383ef7f1e5893b81'
---

# `workspace-root-authority` plan

## Description

Approved 2026-10-04
Authorization: the user requested tackling all remaining known issues after the desktop workspace-root fix. Scope is the three open follow-ups in `2026-10-04-workspace-root-authority-audit`: callback check/open races, native child filesystem authority, and concurrent ACP read verification. The accepted managed-root and Compose callback constraints govern S01. Native process isolation needs a separate decision if desktop launch behavior changes; dependent implementation waits for that decision and a viable platform boundary. ACP remediation is concurrently owned by `2026-10-04-acp-read-remediation-plan`; verify its results and coordinate shared handler edits without overwriting them.

Preserve concurrent work. The parent owns scoped implementation and verification. Scoped commits must exclude others' changes; defer a commit when shared changes cannot be safely isolated and record the exception.

## Steps

- [x] `S01` - Replace pathname callback opens with cross-platform handle-anchored regular-file I/O and real replacement proofs; `src/vaultspec_a2a/desktop/_filesystem_authority.py, src/vaultspec_a2a/providers/_acp_rpc_handlers.py, src/vaultspec_a2a/providers/tests/test_desktop_workspace_boundary.py`.
- [ ] `S02` - Establish and verify native desktop process authority separation, retaining legitimate provider and terminal behavior; `src/vaultspec_a2a/providers/_subprocess.py, src/vaultspec_a2a/desktop, .vault/adr, focused real process tests`.
- [ ] `S03` - Verify the concurrent ACP repair and complete integrated review and audit queue updates; `src/vaultspec_a2a/providers/tests, .vault/audit/2026-10-04-workspace-root-authority-audit.md, .vault/exec, .vault/plan`.

## Parallelization

Execute source changes sequentially. The security-fix workflow requires a read-only independent investigation and one fresh candidate review. The concurrent ACP owner retains its protocol implementation.

## Verification

Run syntax/import, Ruff lint/format, Ty and strict Basedpyright checks before malicious triggers. Use real filesystem trees and concurrent directory or leaf replacement with admitted read/write controls. Preserve ACP line ranges, byte caps, sessions and vault-write denials. Prove native provider and terminal/tool descendants cannot read private synthetic state by absolute path while legitimate provider, IPC, authentication and project behavior remain intact. Missing platform or product evidence leaves its Step open and is recorded in the rolling audit. Complete integrated review, severity/type classification, queue updates, and Core checks before reporting completion.
