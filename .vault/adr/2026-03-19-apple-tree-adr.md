---
tags:
  - "#adr"
  - "#apple-tree"
date: 2026-03-19
related:
  - "[[2026-03-31-docs-vault-migration-research]]"
  - "[[2026-03-19-apple-tree-phase-1-plan]]"
---

# `apple-tree` adr: `historical-scratch-artifact-retention` | (**status:** `accepted`)

## Problem Statement

The vault contains a small historical scratch feature plan for `apple-tree`
without a same-feature ADR. This leaves the feature formally incomplete under
vault validation even though the work is intentionally trivial and isolated.

## Considerations

- The plan describes self-contained throwaway work under `temp/`.
- There is no meaningful architectural dependency on the production codebase.
- The current vault cleanup goal is formal consistency without expanding stale
  artifacts into a large retrospective trail.

## Constraints

- The retained record must stay minimal.
- The ADR must not invent broader architectural significance than the feature
  actually had.

## Decision

Retain the `apple-tree` plan as a historical scratch artifact and treat it as
non-authoritative for current repository architecture. No follow-on execution is
required and no additional documentation is needed beyond this retention ADR.

## Consequences

- Vault feature governance remains internally consistent.
- The artifact stays discoverable without implying ongoing product relevance.
