---
tags:
  - '#exec'
  - '#multi-provider-execution'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S11'
related:
  - "[[2026-07-15-multi-provider-execution-plan]]"
---

# Reuse _subprocess.py's protocol-agnostic process lifecycle helpers (spawn/kill-tree) for Codex subprocess management

## Scope

- `src/vaultspec_a2a/providers/_subprocess.py`
- `src/vaultspec_a2a/providers/codex_chat_model.py`

## Description

- Spawn `codex app-server` through the existing `spawn_acp_process` helper from `providers/_subprocess.py` with `use_exec=False`, so the Windows `.cmd` shim resolves and the whole process tree stays reapable.
- Reap the process tree through the existing `kill_process_tree` helper, closing stdin, killing the tree, and cancelling the reader task.
- Always close the client in the `_astream` `finally` block so the subprocess is torn down on both the success and error paths.

## Outcome

Codex subprocess management reuses the protocol-agnostic lifecycle helpers with no new spawn or kill code. The live-turn test teardown logs confirm the tree is reaped on completion.

## Notes

The `_subprocess.py` helpers are named for their ACP origin but are protocol-agnostic; reusing them for a non-ACP JSON-RPC child is exactly their intended second consumer per the reference document. No changes to `_subprocess.py` were required.
