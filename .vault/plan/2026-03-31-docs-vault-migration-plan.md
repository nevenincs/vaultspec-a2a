---
tags:
  - "#plan"
  - "#docs-vault-migration"
date: 2026-03-31
modified: '2026-07-15'
related:
  - "[[2026-03-31-docs-vault-migration-research]]"
  - "[[2026-03-31-docs-vault-curation-audit]]"
  - "[[2026-03-31-docs-vault-authority-retention-adr]]"
---

# `docs-vault-migration` plan: `legacy-docs-consolidation` | (**status:** `draft`)

## Topic

Consolidate legacy `docs/` material into a clean, authoritative `.vault/`
without carrying forward stale or contradictory information.

## Audit Surface

- `docs/`
- `.vault/`
- `README.md`
- `src/vaultspec_a2a/README.md`
- `.dockerignore`
- Code comments and tests that cite ADR numbers or `docs/adrs/` paths

## Rewrite Scope

Migrate current material, rewrite binding but drifted material, and remove
obsolete or duplicate material.

## Phase 0 — Immediate hygiene

- Keep the live `.vault/` tree frontmatter-clean.
- Resolve malformed placeholders and record them as retirement candidates rather
  than leaving broken files in the vault.
- Freeze a migration inventory before broad rewrites begin.

## Phase 1 — ADR authority pass

- Build a manifest of every legacy ADR that is still cited by code or current
  top-level docs.
- Prioritize migration of code-referenced ADRs first:
  `001`, `002`, `003`, `004`, `006`, `007`, `008`, `009`, `010`, `011`, `012`,
  `013`, `014`, `015`, `017`, `018`, `019`, `020`, `021`, `022`, `023`, `024`,
  `028`, `029`, `031`, `032`, `035`, `038`, and `039`.
- Resolve numbering and supersession drift:
  - keep one canonical `ADR-018`
  - treat `ADR-030` as the renumbered duplicate until a canonical vault form is
    established
  - retire `ADR-034` once all remaining references point at `ADR-038`
  - replace stale `ADR-019` service-separation references with the correct
    vault ADRs
- Migrate each retained ADR into `.vault/adr/` with current frontmatter,
  current repository topology, and explicit supersedes or amends notes in the
  body where needed.

## Phase 2 — README and code-reference repair

- Update `README.md` to point at `.vault/adr/` and any surviving workflow
  references.
- Update `src/vaultspec_a2a/README.md` to replace the missing `ADR-040`
  reference with the correct current vault ADR chain.
- Rewrite code comments and docstrings that still reference removed ADR files,
  wrong ADR numbers, or legacy `docs/adrs/` paths.

## Phase 3 — Legacy non-ADR triage

- Keep only research, audit, and plan documents that remain necessary to
  understand retained ADRs or current workflow.
- Delete branch handovers in `docs/core-layer/` after capturing any unique facts
  that are not already represented in `.vault/adr/`, `.vault/audit/`, or
  `.vault/exec/`.
- Remove legacy research, audits, and plans that only describe deleted modules,
  abandoned topology, or execution states already preserved in the vault or PR
  trail.

## Phase 4 — Reference and workflow documents

- Decide whether `docs/IDE_SETUP.md` remains an active workflow reference.
  - If yes, migrate it into `.vault/reference/` or another canonical non-legacy
    location.
  - If no, remove it with the rest of `docs/`.
- Move retained non-markdown assets out of `docs/marketing/` into a non-vault
  asset path, or delete them if they no longer support current workflow.

## Phase 5 — Final removal pass

- Remove the legacy `docs/` tree only after every retained document has a
  canonical destination and every live reference has been updated.
- Remove the `docs/` entry from `.dockerignore`.
- Re-run vault curation checks and targeted repository searches for stale
  `docs/` and `docs/adrs/` references.

## Acceptance Criteria

- `.vault/` has no malformed markdown records.
- No live code or README file points at `docs/adrs/` or a missing ADR file.
- Every retained decision has one canonical `.vault/adr/` home.
- Legacy handovers and contradictory docs are gone.
- `docs/` can be deleted without breaking developer navigation or architecture
  grounding.
