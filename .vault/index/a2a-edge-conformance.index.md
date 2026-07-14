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
  - '[[2026-07-14-a2a-edge-conformance-W01-P01-S03]]'
  - '[[2026-07-14-a2a-edge-conformance-W01-P01-S33]]'
  - '[[2026-07-14-a2a-edge-conformance-W01-P02-S04]]'
  - '[[2026-07-14-a2a-edge-conformance-W01-P02-S05]]'
  - '[[2026-07-14-a2a-edge-conformance-W01-P02-S06]]'
  - '[[2026-07-14-a2a-edge-conformance-W01-P15-S34]]'
  - '[[2026-07-14-a2a-edge-conformance-W01-P15-S35]]'
  - '[[2026-07-14-a2a-edge-conformance-W01-P15-S36]]'
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
- `2026-07-14-a2a-edge-conformance-W01-P01-S03` - Audit pytest marker partitioning (unit/core/middleware/service select identical sets today) and repair marker assignments so selections partition the suite
- `2026-07-14-a2a-edge-conformance-W01-P01-S33` - Audit the agent/tool provisioning mechanism with live evidence: how a session is constructed, the subprocess spawned, the chat-model adapter bound, and tools actually surfaced to the agent (ACP session wiring, subprocess management, chat-model adapter, provider factory), recording what is proven versus presumed
- `2026-07-14-a2a-edge-conformance-W01-P02-S04` - Review and commit the pending vaultspec housekeeping (managed .gitignore block, vault pre-commit hooks, vaultspec-rag and torch additions) as a standalone commit
- `2026-07-14-a2a-edge-conformance-W01-P02-S05` - Relocate runtime state (graph cache, logs, tmp, queues) to the machine-global A2A home, repoint the .vault/runtime reference rag-first-discovering any other stale path consumers, and discard the parked .vault-local-state-moved-20260703 directory (user decision 2026-07-14: discard, not restore). Land this before S01 if the IPC check trips over the stale path
- `2026-07-14-a2a-edge-conformance-W01-P02-S06` - Delete the empty orphan top-level packages (core, cli, tests, bin) and their stale caches after confirming zero inbound references via rag and grep
- `2026-07-14-a2a-edge-conformance-W01-P15-S34` - Review-merge feature/integration-testing-smoke-tests-api-veri-17 in full per the owner decision of 2026-07-14: run the full test baseline before and after, merge with a merge commit (squash and rebase are disabled), and review the diff against current architecture during the merge
- `2026-07-14-a2a-edge-conformance-W01-P15-S35` - Spot-check feature/entry-point-layer conftest and vowel-counter test diffs for novel coverage, harvesting anything of value into the step record before the branch is deleted
- `2026-07-14-a2a-edge-conformance-W01-P15-S36` - Execute the owner-authorized LOCAL cleanup of 2026-07-14 (destructive): remove the three merged worktrees and angry-jemison, drop all four pre-restructure stashes, delete feature/control-layer and feature/entry-point-layer locally, and remove the orphaned feature-ui-integration-wire-regen-28 directory

### plan

- `2026-07-14-a2a-edge-conformance-plan` - `a2a-edge-conformance` plan

### reference

- `2026-07-14-a2a-edge-conformance-deletion-manifest-reference` - `a2a-edge-conformance` reference: `UI and Google-A2A stub deletion manifest`
- `2026-07-14-a2a-edge-conformance-engine-wire-shapes-reference` - `a2a-edge-conformance` reference: `engine authoring wire shapes`
- `2026-07-14-a2a-edge-conformance-reference` - `a2a-edge-conformance` reference: `frozen dashboard edge contract, a2a side`

### research

- `2026-07-14-a2a-edge-conformance-research` - `a2a-edge-conformance` research: `repo functional-reality survey grounding the edge adoption`
