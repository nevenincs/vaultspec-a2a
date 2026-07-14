---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S14'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Prove with live tests that a full mock-tape run performs zero .vault/ writes while the queue and worker loop still function

## Scope

- `src/vaultspec_a2a/graph/tests/`
- `src/vaultspec_a2a/service_tests/`

## Description

Proved, as an observed negative rather than a no-write-path argument, that the database-backed task queue functions while the run writes nothing to a vault. Two independent proofs were produced.

Committed live test. A new test at `src/vaultspec_a2a/graph/tests/nodes/test_vault_write_isolation.py` runs a continuous filesystem watcher (a background thread sampling mtime and size for every file under a temp workspace vault at a 5ms interval, accumulating every create, modify, and delete observed for the duration) across a full exercise of the database-backed queue over real file-backed aiosqlite. While the watcher runs it: mounts the vault (the mount node reads a real `.vault/adr` document and injects the current-plus-horizon queue view sourced from the database), advances the queue through the mark-complete tool (the in_progress row transitions to completed and the cursor advances to the next pending row), and re-mounts to confirm the advanced, still-database-sourced view. The assertion is that the watcher observed zero vault write events. Reads never change mtime or size, so the read-only mount produces no events. The test passes.

Full-stack observed negative. A native probe (Docker is unavailable in this environment, so the pinned VidaiMock v0.1.3 binary is run directly, matching the S02 precedent) boots the real gateway and auto-spawned worker against an isolated temp project root, with a vault watcher started before the stack comes up and stopped after teardown. It drives a `mock-success-single` thread to terminal through the real gateway to worker to graph to VidaiMock to checkpoint path, then exercises the database queue against the gateway's own SQLite database (seed plus mark-complete). Captured result: `thread_status: completed`, `queue_advanced: True` (`did_complete=True next=T-2`), `vault_write_events: []`, verdict OBSERVED-NEGATIVE ZERO-VAULT-WRITE PASS.

- Created: `src/vaultspec_a2a/graph/tests/nodes/test_vault_write_isolation.py`

## Outcome

Both proofs are green. The database-backed queue injects and advances, the worker loop reaches a terminal thread state end-to-end through the real stack, and a live filesystem watcher observed zero vault writes across the whole run — the observed-negative the wave-01 review required, not a no-write-path argument. The plan checkbox is held open until the executor-opus-w01 diff review passes.

## Notes

Docker is unavailable in this environment, so the canonical docker-compose service suite could not run; the pinned, sha256-verified VidaiMock v0.1.3 binary was run natively instead (the same artifact the compose stack pulls, not a double), exactly as the S02 verification-gate step did. The full-stack probe and its evidence live in the session scratchpad; the committed regression coverage is the graph-level isolation test, which needs no external services and runs in the default profile. The thread-create API carries no workspace-root or active-feature field, so the mock-tape run itself does not enter the vault-mount or queue-injection path; the probe therefore exercises the database queue directly against the gateway database to demonstrate the queue functioning under the live stack while the watcher confirms the vault stays untouched. The isolation test covers the mount-injection and mark-complete code paths that the S13 change introduced.
