---
tags:
  - "#adr"
  - "#vowel-counter"
date: 2026-03-26
related:
  - "[[2026-03-31-docs-vault-migration-research]]"
  - "[[2026-03-26-vowel-counter-implementation-plan]]"
  - "[[2026-03-26-vowel-counter-implementation-create-file-exec]]"
---

# `vowel-counter` adr: `historical-scratch-artifact-retention` | (**status:** `accepted`)

## Problem Statement

The vault contains a historical `vowel-counter` implementation plan and exec
records, but no same-feature ADR. Validation now flags the feature as
architecturally incomplete.

## Considerations

- The underlying utility was deleted later as dead code.
- The remaining vault records are useful only as historical trace.
- Creating a large retrospective design trail would add noise rather than
  improve current development clarity.

## Constraints

- The retained decision should be explicit that the feature is obsolete.
- The ADR should regularize the vault without reviving removed code.

## Decision

Retain the `vowel-counter` vault artifacts only as historical execution trace.
They are not active architecture and should not guide current implementation
work.

## Consequences

- The vault keeps a coherent decision trail for the archived feature.
- Future curation can delete the entire feature as a single obsolete unit if
  the team chooses stricter pruning.
