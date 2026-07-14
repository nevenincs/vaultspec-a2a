---
generated: true
tags:
  - '#index'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
related:
  - '[[2026-07-14-a2a-edge-conformance-W01-P01-S01]]'
  - '[[2026-07-14-a2a-edge-conformance-W01-P01-S02]]'
  - '[[2026-07-14-a2a-edge-conformance-W01-P01-S33]]'
  - '[[2026-07-14-a2a-edge-conformance-W01-P02-S04]]'
  - '[[2026-07-14-a2a-edge-conformance-W01-P02-S05]]'
  - '[[2026-07-14-a2a-edge-conformance-adr]]'
  - '[[2026-07-14-a2a-edge-conformance-deletion-manifest-reference]]'
  - '[[2026-07-14-a2a-edge-conformance-engine-wire-shapes-reference]]'
  - '[[2026-07-14-a2a-edge-conformance-plan]]'
  - '[[2026-07-14-a2a-edge-conformance-reference]]'
  - '[[2026-07-14-a2a-edge-conformance-research]]'
  - '[[2026-07-14-a2a-edge-conformance-worktree-reconciliation-audit]]'
---

# `a2a-edge-conformance` feature index

Auto-generated index of all documents tagged with `#a2a-edge-conformance`.

## Documents

### adr

- `2026-07-14-a2a-edge-conformance-adr` - `a2a-edge-conformance` adr: `adopting the dashboard edge contract under a salvage-and-verify posture` | (**status:** `accepted`)

### audit

- `2026-07-14-a2a-edge-conformance-worktree-reconciliation-audit` - `a2a-edge-conformance` audit: `worktree and branch reconciliation`

### exec

- `2026-07-14-a2a-edge-conformance-W01-P01-S01` - Boot gateway and worker together and prove live IPC dispatch (worker_connected true, a message round-trips), fixing whatever blocks it
- `2026-07-14-a2a-edge-conformance-W01-P01-S02` - Execute one full agent turn end-to-end on a mock-tape preset and capture the evidence in the step record
- `2026-07-14-a2a-edge-conformance-W01-P01-S33` - Audit the agent/tool provisioning mechanism with live evidence: how a session is constructed, the subprocess spawned, the chat-model adapter bound, and tools actually surfaced to the agent (ACP session wiring, subprocess management, chat-model adapter, provider factory), recording what is proven versus presumed
- `2026-07-14-a2a-edge-conformance-W01-P02-S04` - Review and commit the pending vaultspec housekeeping (managed .gitignore block, vault pre-commit hooks, vaultspec-rag and torch additions) as a standalone commit
- `2026-07-14-a2a-edge-conformance-W01-P02-S05` - Relocate runtime state (graph cache, logs, tmp, queues) to the machine-global A2A home, repoint the .vault/runtime reference rag-first-discovering any other stale path consumers, and discard the parked .vault-local-state-moved-20260703 directory (user decision 2026-07-14: discard, not restore). Land this before S01 if the IPC check trips over the stale path

### plan

- `2026-07-14-a2a-edge-conformance-plan` - `a2a-edge-conformance` plan

### reference

- `2026-07-14-a2a-edge-conformance-deletion-manifest-reference` - `a2a-edge-conformance` reference: `UI and Google-A2A stub deletion manifest`
- `2026-07-14-a2a-edge-conformance-engine-wire-shapes-reference` - `a2a-edge-conformance` reference: `engine authoring wire shapes`
- `2026-07-14-a2a-edge-conformance-reference` - `a2a-edge-conformance` reference: `frozen dashboard edge contract, a2a side`

### research

- `2026-07-14-a2a-edge-conformance-research` - `a2a-edge-conformance` research: `repo functional-reality survey grounding the edge adoption`
