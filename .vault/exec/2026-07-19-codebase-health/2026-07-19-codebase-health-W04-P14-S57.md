---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S57'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Prove runtime and dashboard ownership or non-ownership for the workspace exports

## Scope

- `src/vaultspec_a2a/workspace/git_manager.py, src/vaultspec_a2a/thread/errors.py, src/vaultspec_a2a/thread/__init__.py, ../../vaultspec-dashboard-worktrees/main, .vault/audit`

## Description

- Search this service for consumers of each of the six symbols, excluding the
  declaring module, its package facade, and its own tests.
- Search the dashboard repository for the same symbols, excluding build output
  and vendored dependencies.
- Test each apparent dashboard match rather than counting it, since the dashboard
  reaches this service across an HTTP edge and cannot import its modules.
- Record the result as an audit with a severity per finding.

## Outcome

Five of the six symbols are unowned in both repositories. The manager, the merge strategy,
and the worktree descriptor are referenced only by the package facade and their own tests;
the two error types are additionally re-exported through the thread error facade but no
production code raises or catches either. The three worktree operations have no production
caller at all.

The module-level Git mutex is the exception and is genuinely live, imported by the ACP
filesystem handler to serialize agent writes. Any removal of the surrounding surface must
preserve it, which the following Step already anticipates by moving it to a module named
for its purpose.

Both dashboard matches proved to be name collisions rather than ownership. The worktree
descriptor is a Rust struct that repository declares itself; the workspace error is a
substring of a TypeScript classification helper. Counting them would have blocked a
removal that the evidence supports.

## Notes

The cross-repository sweep surfaced two defects outside this Step's subject, and they are
recorded in the audit because the search is what exposed them. The dashboard declares the
gateway entrypoint with both a console script and a module reference that resolve to
nothing, and four of its contract fixtures encode a standalone MCP reference to a module
that does not exist. The console script in those fixtures is correct, which is why the
mismatch survived: the contract test asserts against a hand-copied expectation rather than
against a capsule manifest, so it is structurally unable to detect the drift it exists to
catch.

Neither belongs to this repository and neither is fixed here. Both are named in the audit
with the correct values, taken from the manifests of the four capsules built from the
current tree.

This Step proves ownership and removes nothing. The removals it licenses are separate Steps
and are left open.
