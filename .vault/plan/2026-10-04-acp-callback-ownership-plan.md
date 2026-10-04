---
tags:
  - '#plan'
  - '#acp-callback-ownership'
date: '2026-10-04'
tier: L1
related:
  - '[[2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-adr]]'
  - '[[2026-09-21-workspace-root-authority-compose-provider-boundary-adr]]'
modified: '2026-10-04'
body_schema: body-v2
body_hash: 'sha256:8d6f2b8ccd4a8c420c03a8aad687efadb8b866747b26c4f62a6fdf9350d7875a'
---

# `acp-callback-ownership` plan

Sequential filesystem-write and terminal session authority remediation.

## Description

Approved 2026-10-04
Authorization: the user requested all issue fixes sequentially and explicitly
asked to continue after the read remediation. This pass implements the accepted
ACP v1 client-wire decision for the remaining filesystem-write and terminal
session ownership finding, retaining existing workspace and cleanup policies.
The previous read-remediation plan is complete and its behavior remains covered.
No new costly decision is needed. Native-tool enforcement and terminal output
retention retain their earlier plan ownership; this pass does not redesign them.

## Steps

- [x] `S01` - Enforce active session identity before filesystem writes and preserve read ownership through one shared guard; `src/vaultspec_a2a/providers/_acp_client_requests.py, src/vaultspec_a2a/providers/_acp_fs_read.py, src/vaultspec_a2a/providers/_acp_rpc_handlers.py, src/vaultspec_a2a/providers/tests, src/vaultspec_a2a/service_tests/test_compose_provider_service_state_isolation.py`.
- [x] `S02` - Enforce terminal session ownership on creation and every addressing callback while preserving internal teardown; `src/vaultspec_a2a/providers/_acp_rpc_terminal_handlers.py, src/vaultspec_a2a/providers/_acp_teardown.py, src/vaultspec_a2a/providers/tests, src/vaultspec_a2a/desktop_tests/test_owned_process_tree.py`.
- [x] `S03` - Reconcile integrated review evidence and the rolling audit ownership queue; `.vault/audit, .vault/exec, .vault/plan`.

## Parallelization

Execute S01, S02, and S03 sequentially with one implementation owner. Read-only
security investigation and candidate review support the owning security skill.
Preserve concurrent subprocess, desktop admission, and provider eligibility work.

## Verification

Reproduce foreign/missing/malformed session writes and terminal access with real
files and subprocesses, then prove they fail before side effects after the fix.
Retain legitimate writes, vault-write denials, capability dispatch, unknown
terminal refusals, release idempotence, cancellation cleanup, and process-tree
reaping. Verify real pipe traffic and the installed SDK transport. Run full
Ruff lint/format and Ty, scoped Basedpyright, nearest provider tests, native Linux
secure callbacks, and Docker boundary probes when affected. Review each cohesive
implementation, classify/persist every finding, log Steps, and commit only own
changes. Keep the commit hook uninstalled as requested.
