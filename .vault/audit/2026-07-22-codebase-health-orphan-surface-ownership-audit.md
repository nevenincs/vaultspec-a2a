---
tags:
  - '#audit'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# `codebase-health` audit: `cross-repository ownership of the workspace exports`

## Scope

Whether `GitManager`, `MergeStrategy`, `WorktreeInfo`, `WorkspaceError`,
`MergeConflictError`, and the module-level Git mutex have any consumer in this service or
in the dashboard repository, so a later Step can remove what nothing owns. Both trees were
searched read-only. The sweep also surfaced entrypoint drift in the dashboard's view of
this service, recorded here because the cross-repository search is what exposed it.

## Findings

### workspace-exports-are-unowned-in-both-repositories | medium | five of six symbols have no consumer anywhere

Within this service, `GitManager`, `MergeStrategy`, and `WorktreeInfo` are referenced only
by the package facade that re-exports them and by their own unit tests. `WorkspaceError`
and `MergeConflictError` are additionally re-exported through the thread error facade and
exercised by its tests, but no production caller raises or catches either. The three
worktree operations the manager provides - create, remove, and merge - have no production
call site at all.

The one live symbol is the module-level Git mutex, imported by the ACP filesystem handler
to serialize agent writes. It is genuine production state and must survive any removal of
the surface around it.

In the dashboard repository none of the six is consumed. Two apparent matches are name
collisions rather than ownership: `WorktreeInfo` is a Rust struct that repository declares
itself in its Git ingest crate, and `WorkspaceError` matches a substring of a TypeScript
error-classification helper in the frontend. Neither is capable of consuming a Python
export, because the dashboard reaches this service across an HTTP edge and never imports
its modules.

### dashboard-declares-a-gateway-entrypoint-that-does-not-exist | high | both the console script and the module reference are wrong

The dashboard's product lifecycle declares the gateway entrypoint with console script
`vaultspec-a2a-gateway` and reference `vaultspec_a2a.desktop.gateway:main`. Neither
resolves. Every capsule manifest built from the current tree declares the gateway as
console script `vaultspec-a2a` with reference `vaultspec_a2a.cli.main:main`, and the
module path the dashboard names does not exist in this service at all. A dashboard
bundling these capsules cannot spawn the gateway on any of the four targets.

### dashboard-contract-fixtures-encode-a-nonexistent-mcp-reference | high | the contract test cannot catch the drift it exists to catch

Four dashboard test fixtures - its product build, product authority, cohort, and a2a
contract check - assert the standalone MCP entrypoint reference is `vaultspec_a2a.mcp:main`.
That module does not exist; the real reference is
`vaultspec_a2a.protocols.mcp.__main__:main`, as every capsule manifest records. Because the
fixtures encode the wrong expectation, the dashboard's own contract test passes against a
fabricated contract and is structurally unable to detect the mismatch. The console script
name in those same fixtures is correct, which is why the discrepancy has stayed invisible.

## Recommendations

Remove the unowned workspace surface in the Step that follows, keeping the Git mutex. The
evidence supports removal in both repositories, and the mutex should move to a module whose
name states its purpose rather than being extracted from a manager nothing calls.

Correct the dashboard's gateway entrypoint declaration in both fields, and correct the four
contract fixtures to the real MCP reference. Neither change belongs to this repository, and
both are recorded here so the dashboard's own decision record can carry them.

Derive the dashboard's expected entrypoints from a capsule manifest rather than restating
them in fixtures. A contract test whose expectation is hand-copied from the other side of
the boundary asserts only that the copy is self-consistent, which is what allowed two wrong
references to survive alongside one correct console script.
