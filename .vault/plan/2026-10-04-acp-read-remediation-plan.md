---
tags:
  - '#plan'
  - '#acp-read-remediation'
date: '2026-10-04'
tier: L1
related:
  - '[[2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-adr]]'
  - '[[2026-09-21-workspace-root-authority-compose-provider-boundary-adr]]'
modified: '2026-10-04'
body_schema: body-v2
body_hash: 'sha256:15729f7a5a310f1563923ad7c28330d9c0bcb5bf8d36c9a29d83752ec51da577'
---

# `acp-read-remediation` plan

Sequential validation repair and complete ACP filesystem read remediation.

## Description

Approved 2026-10-04
Authorization: the user requested uninstalling the commit hook and fixing all
current validation failures and remaining ACP byte-limit, line-pagination,
and session-ownership issues one at a time. The repository hook was removed
with `python -m dev.repo.hooks remove` and absence verified.

S01 repairs concrete type/lint/test failures without changing unrelated
concurrent feature scope. These are routine corrections with no new costly
decision. S02 implements the existing accepted ACP v1 client-wire decision
for filesystem reads: session validation, one-based line selection, line
limits, removal of legacy offsets, and an independent UTF-8 byte cap. The
Compose workspace-boundary ADR continues to govern confined, anchored I/O.
S03 completes integrated verification, review, and queue updates.

The old ACP migration plan remains the owner of terminal work. This plan
does not authorize unrelated terminal redesign or closing that larger plan.
Preserve all concurrent edits; isolate commits to authored changes and use
hunk staging where files are shared.

## Steps

- [x] `S01` - Resolve current validation failures in real engine peers and worker admission tests; `src/vaultspec_a2a/authoring/tests, src/vaultspec_a2a/worker/tests`.
- [x] `S02` - Implement ACP v1 filesystem session and line semantics with an independent UTF-8 byte cap; `src/vaultspec_a2a/providers/_acp_fs_read.py, src/vaultspec_a2a/providers/_acp_rpc_handlers.py, src/vaultspec_a2a/providers/_acp_types.py, src/vaultspec_a2a/providers/_acp_session.py, src/vaultspec_a2a/providers/tests, src/vaultspec_a2a/control/infra_config.py, src/vaultspec_a2a/service_tests/test_compose_provider_service_state_isolation.py`.
- [x] `S03` - Complete integrated verification and reconcile the rolling audit queue; `.vault/audit, .vault/exec, .vault/plan, src/vaultspec_a2a/providers/tests`.

## Parallelization

Execute S01, S02, and S03 sequentially, as requested. No parallel workers.

## Verification

Run locked Ruff lint/format and full configured Ty checks. For S01, execute
the real loopback and worker tests whose types change. For S02, prove exact
ACP request handling, current-session ownership, line ranges, invalid input,
removal of offset payload acceptance, and UTF-8 byte caps over both ordinary
and descriptor-anchored backends with real files and pipe traffic. Run the
nearest existing tests and strict Basedpyright on the changed surfaces.
Review the final implementation and append every finding with severity,
type, status, and ownership to the rolling audit. All Steps require passing
checks, ledger rows, owning progress updates, and scoped commits.
