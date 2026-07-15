---
tags:
  - "#adr"
  - "#docs-vault-migration"
date: 2026-03-31
modified: '2026-07-15'
related:
  - "[[2026-03-31-docs-vault-migration-research]]"
  - "[[2026-03-31-docs-vault-curation-audit]]"
  - "[[2026-03-31-docs-vault-migration-plan]]"
---

# `docs-vault-migration` adr: `vault-authority-and-retention-policy` | (**status:** `proposed`)

## Problem Statement

The repository currently has two parallel documentation systems:

- `.vault/` holds the active vaultspec pipeline trail and the recent layered
  architecture work that landed through PR #16.
- `docs/` holds the legacy ADR, audit, research, plan, handover, and marketing
  tree.

Blindly copying `docs/` into `.vault/` would preserve stale topology, duplicate
decisions, missing references, and superseded execution notes. Blindly deleting
`docs/` would break live ADR references in code and remove still-binding design
decisions without replacement.

## Considerations

- GitHub issue #19 requires `docs/` to be triaged, not preserved wholesale.
- The current codebase still cites many ADR numbers from the legacy `docs/adrs/`
  corpus, so authority must be re-established before `docs/` can disappear.
- The current repository direction is the layered, containerized, service-based
  architecture captured by the recent `.vault/` trail and merged PR sequence.
- The vault should stay useful for present-day development. Historical noise
  that contradicts `main` should not survive just because it once existed.

## Decision

- `.vault/` becomes the single authoritative home for architecture decisions,
  research, plans, audits, and execution records.
- A legacy markdown document migrates only if it is both current to `main` and
  still useful to ongoing development.
- Legacy ADRs that are still cited by code must be migrated or superseded
  before `docs/` is removed.
- Superseded, contradictory, duplicate, or branch-local documents do not get an
  "active archive" inside `.vault/`. They are removed once the canonical vault
  replacement exists.
- Non-markdown binary assets do not move into `.vault/`. If retained, they move
  to a non-vault asset location.
- Operator-facing markdown that remains current may migrate into
  `.vault/reference/` if it directly supports the developer workflow; otherwise
  it should be relocated outside `docs/`.

## Consequences

### Positive

- Future work has one authoritative documentation trail.
- Code comments and top-level docs can reference real, current vault ADRs
  instead of a stale parallel tree.
- The vault stays nimble because obsolete execution history and contradictory
  design text are removed rather than preserved by habit.

### Costs

- The migration must include a reference-repair pass across code comments,
  README files, and package architecture notes.
- Several legacy ADRs will need rewrite, not just relocation, because they are
  still cited but no longer accurately describe the current repository.

### Answer to the Open Question

Obsolete ADRs and decisions should not remain in the active vault when they
contradict the current repository or a newer accepted decision. Keep only the
current canonical decision, and record supersession in that canonical document
or in the migration audit when a historical breadcrumb is still necessary.
