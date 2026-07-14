---
tags:
  - "#audit"
  - "#docs-vault-migration"
date: 2026-03-31
modified: '2026-03-31'
related:
  - "[[2026-03-31-docs-vault-migration-research]]"
  - "[[2026-03-31-docs-vault-authority-retention-adr]]"
  - "[[2026-03-31-docs-vault-migration-plan]]"
---

# `docs-vault-migration` audit: `curation-baseline`

## Scope

Audit the live `.vault/` tree and the legacy `docs/` tree to establish a clean
baseline for issue #19.

## Critical Findings

- `README.md` still presents `docs/adrs/` as the binding ADR location.
- `src/vaultspec_a2a/README.md` points at a missing
  `docs/adrs/040-layer-boundary-enforcement.md`.
- Legacy handover documents in `docs/core-layer/` still direct work through
  deleted or superseded modules and a missing ADR.

## High Findings

- `docs/README.md` is obsolete. It claims the project has no ADRs yet and
  indexes a pre-pipeline documentation model that no longer matches the repo.
- The legacy ADR corpus cannot be copied verbatim. Live code still cites many
  ADR numbers, but the ADR set contains numbering drift, superseded decisions,
  and outdated topology language.
- `docs/audits/`, `docs/research/`, and `docs/plans/` contain widespread
  references to deleted surfaces such as `core/`, `cli/`, `doctor`, `verify`,
  `providers/probes`, `api/endpoints.py`, and `database/crud.py`.

## Medium Findings

- `.vault/exec/2026-03-26-vowel-counter/dummy.md` was a malformed placeholder
  file. It has been normalized, but the feature remains a candidate for
  retirement during migration because the underlying code was later removed.
- `docs/marketing/` contains binary assets that do not belong in the pipeline
  vault. They need relocation or deletion, not markdown migration.
- `docs/IDE_SETUP.md` needs an explicit decision: retain as active developer
  reference or drop if the workflow is no longer supported.

## Triage Outcome

### Keep and migrate

- Code-referenced ADRs
- Still-valid operator or workflow references that remain part of day-to-day
  development

### Rewrite during migration

- ADRs that remain binding but have stale paths, outdated topology language, or
  supersession drift
- README and package-architecture references to legacy ADR locations

### Remove

- Legacy handovers
- Redundant branch-local plans and audits already superseded by `.vault/exec/`
  and merged PR history
- Contradictory or duplicate ADR text once a canonical vault ADR exists
