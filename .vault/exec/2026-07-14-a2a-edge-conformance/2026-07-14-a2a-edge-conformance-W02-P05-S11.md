---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S11'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Implement the .vault/** deny policy at the ACP fs write RPC handler returning a structured forbidden_actor-style denial that names the authoring tools, leaving reads untouched

## Scope

- `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`

## Description

- Re-read the post-merge `_acp_rpc_handlers.py` per the W01 review (the -17 merge added a subprocess-terminal-timeout cap): confirm `on_fs_write_text_file` is the SOLE fs-mutation RPC handler (no delete/create-dir siblings exist in the rpc_map; reads go through `on_fs_read_text_file`).
- Read the wire-shapes reference §2 for the exact denial shape: the engine's `forbidden_actor` is an HTTP-200 VALUE with `data.status = "denied"`, `data.denial_kind = "forbidden_actor"` (snake_case), and `data.eligibility.reason`; the reference is explicit that the ACP fs-write denial mirrors this 200-value pattern, never a transport error.
- Add `_targets_vault()` (case-insensitive `.vault` component check on the already-resolved sandbox path) and `_vault_write_denial()` (the value-typed forbidden_actor response naming propose_changeset/append_draft/replace_draft).
- Insert the deny check in `on_fs_write_text_file` immediately after `sandbox_path()` and before the write; leave `on_fs_read_text_file` untouched so reads stay permitted (dashboard D4).

## Outcome

Committed with S12 as `07f8c9c`. `ruff` and `ty` clean. The denial is a JSON-RPC `result` (value), not an `error`, carrying `status: denied`, `denial_kind: forbidden_actor`, and an `eligibility` block that steers the agent to the authoring tools. Detection reuses `sandbox_path`'s `resolve()`+`is_relative_to` (which already collapses `..` traversal and symlinks and rejects sandbox escape) and adds `casefold()` matching for the case-insensitive Windows/macOS filesystems.

## Notes

The deny check denies ANY `.vault` path component (case-insensitive), not just a workspace-root `.vault`, for defense-in-depth. Because `sandbox_path` runs first and confines to the agent cwd, a symlink or `..` route that escapes the sandbox is already rejected as a ValueError before the vault check; a symlink or `..` route that resolves back UNDER the cwd into `.vault` is caught by the component check on the resolved path. Behavioural note for W03: whether the claude-agent-acp client surfaces a value-typed `result` denial to the agent as a steer (vs treating it as write success) is the architect's chosen contract per the wire-shapes reference; the adversarial suite (S12) proves the handler's behaviour, and the end-to-end steer is observed in the W03.P08 solo-coder proof.
