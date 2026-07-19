---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S01'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Curate the service-lifecycle supersession chain so the product lifecycle and tooling decisions have non-conflicting authority

## Scope

- `.vault/adr`
- `.vault/index`

## Description

- Ground the lifecycle decision cluster with semantic Vaultspec RAG discovery,
  whole-record reads, and exact source searches.
- Restore the service-lifecycle record as accepted and remove its invalid
  whole-document supersession edge.
- Assign named host-process lifecycle to the dev-process registry and limit
  repository tooling to the delegating `just` command surface.
- Align the desktop compatibility statement with the same authority split.
- Regenerate the service-lifecycle feature index and verify the decision graph.
- Resolve the reviewer's initial high-severity authority conflict and obtain a
  clean independent review.

## Outcome

The decision chain now has one owner per concern. The service-lifecycle record
governs Compose and product topology. The dev-process registry governs named
host processes. Repository tooling delegates commands without owning product or
process lifecycle.

The invalid supersession edge is absent, and only the legacy control-layer
record remains superseded by repository tooling. The service-lifecycle ADR and
its generated index both report `accepted`.

## Notes

The first review returned `REVISION REQUIRED` because the desktop ADR retained
the foreground shim and two statements misattributed development refinement to
repository tooling. The corrected diff received `PASS` with no remaining
findings at any severity.

No production code changed. Global Vault repair was not run because concurrent
desktop work owns unrelated warnings and dirty files.
