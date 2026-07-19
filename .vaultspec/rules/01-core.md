---
name: 01-core
---

# Repository engineering rules

## Scope and integration

- Work only within the requested feature or approved plan Step. Ask before a material scope expansion.
- Read the surrounding implementation, configuration, and governing decisions before editing. Follow established naming, typing, architecture, formatting, and dependency conventions.
- Preserve concurrent and unrelated work. Never revert, overwrite, stage, or commit changes outside the active scope.
- Verify libraries and tools from project metadata, imports, neighboring code, or authoritative documentation before using them.
- Add comments only when they explain a non-obvious invariant or design reason.

## Quality gates

- Implement the requested behavior completely, then run checks proportionate to the changed surface.
- Fix underlying lint, format, type, dependency, and test failures; never hide them with suppressions or disabled checks.
- Report the outcome, verification, remaining risks, and modified scope concisely.

## Test integrity

- Tests must import the production code they exercise directly. Never copy, shadow, mirror, or reimplement business logic in a test.
- Never use fakes, mocks, stubs, patches, monkeypatches, skips, or expected-failure markers as shortcuts to a passing run.
- Never accept tautological assertions or expected values copied from a failing implementation.
- Prefer real-behavior tests using actual subprocesses, filesystems, databases, services, and protocol boundaries when those boundaries matter.
- Keep diagnostics useful: retain actionable logging and trace output when failures would otherwise be opaque.
