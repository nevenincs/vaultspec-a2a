---
tags:
  - "#research"
  - "#docs-vault-migration"
date: 2026-03-31
modified: '2026-03-31'
related:
  - "[[2026-03-31-docs-vault-curation-audit]]"
  - "[[2026-03-31-docs-vault-authority-retention-adr]]"
  - "[[2026-03-31-docs-vault-migration-plan]]"
---

# `docs-vault-migration` research: `current-state-and-retention-grounding`

## Topic

Migrate the legacy `docs/` tree into the live `.vault/` pipeline without
carrying forward stale, contradictory, or duplicate material.

## Audit Surface

- `.vault/`
- `docs/`
- `README.md`
- `src/vaultspec_a2a/README.md`
- Recent merged PRs in the layer-isolation roadmap, especially PRs #2, #3, #4,
  #9, #11, #15, and #16
- GitHub issue #19

## Rewrite Scope

Define what remains authoritative, what must migrate, what must be rewritten,
and what should be removed instead of preserved.

## Current State

- `.vault/` is the active pipeline trail. It contains current research, plans,
  ADRs, audits, and execution records for the layer-boundary and service-layer
  work that landed through PR #16.
- `docs/` is a legacy tree with 241 markdown files and 244 files total. It
  still holds 40 ADRs, 76 audits, 98 research notes, 21 plans, 4 core-layer
  handovers, and 3 marketing assets.
- GitHub issue #19 explicitly describes `docs/` as the legacy tree and `.vault/`
  as the authoritative pipeline destination for this cleanup.
- The feature history confirms the architecture direction is now containerized
  layered boundaries with no upward imports across layers, thin entry points,
  and a service layer consolidated in PR #16.

## Findings

### `.vault/` is mostly healthy but not yet clean

- Frontmatter compliance is broadly intact across existing `.vault/` markdown
  files.
- One malformed execution artifact existed in
  `2026-03-26-vowel-counter/dummy.md`. It was a raw placeholder with no
  frontmatter and no vault metadata.
- The `vowel-counter` feature itself is obsolete relative to the current
  repository; the utility was later deleted during the layer cleanup.

### `docs/` is not a safe source of truth

- `docs/README.md` claims there are no ADRs yet and uses an invalid date format.
  That statement is now false and materially misleading.
- `docs/core-layer/` handovers are transient branch handoff documents, not
  stable architecture records. They reference missing or superseded artifacts,
  including `docs/adrs/040-layer-boundary-enforcement.md`, which does not exist.
- Large parts of `docs/audits/`, `docs/research/`, and `docs/plans/` reference
  deleted or superseded surfaces such as `core/`, `cli/`, `doctor`, `verify`,
  `providers/probes`, `api/endpoints.py`, and `database/crud.py`.
- The root `README.md` still points readers to `docs/adrs/` and
  `docs/IDE_SETUP.md`, even though issue #19 defines `.vault/` as the active
  architecture trail.
- `src/vaultspec_a2a/README.md` still names `docs/adrs/040-layer-boundary-enforcement.md`
  as the binding ADR, which is stale and currently broken.

### The ADR set needs triage, not bulk deletion

- Live code, tests, config comments, and the root README still reference many
  ADR numbers from the legacy `docs/adrs/` corpus.
- The active codebase currently cites ADRs `001`, `002`, `003`, `004`, `006`,
  `007`, `008`, `009`, `010`, `011`, `012`, `013`, `014`, `015`, `017`, `018`,
  `019`, `020`, `021`, `022`, `023`, `024`, `028`, `029`, `031`, `032`, `035`,
  `038`, and `039`.
- This means the migration cannot treat most legacy ADRs as purely historical.
  Many are still binding by reference and must either be migrated and rewritten
  into `.vault/adr/` or be superseded by new `.vault/adr/` documents with code
  comments updated accordingly.

### There is semantic drift inside the ADR set itself

- ADR numbering is inconsistent. There are two `ADR-018` files, and the later
  duplicate was renumbered to `ADR-030` only inside the file body.
- ADR usage is inconsistent. Current code frequently cites `ADR-019` as a
  service-separation authority even though the legacy `ADR-019` document is
  about `TeamState` blackboard enrichment, while worker-process architecture is
  now formalized by `ADR-031`.
- `ADR-034` is explicitly superseded by `ADR-038`, but code comments still cite
  `ADR-034`.
- Some accepted ADRs still refer to outdated package roots or pre-layered
  structure, for example `ADR-009`.

## Retention Guidance

### Migrate first

- Any ADR still cited by live code or current top-level docs
- Any audit or research note directly needed to support a retained ADR that has
  no current `.vault/` replacement
- `docs/IDE_SETUP.md` only if it remains part of the active developer workflow

### Rewrite while migrating

- Legacy ADRs whose decision is still binding but whose examples, file paths, or
  topology descriptions drifted from `main`
- Code comments or README references that still point at `docs/adrs/` or at
  missing ADRs

### Remove instead of preserve

- `docs/README.md`
- `docs/core-layer/*.md` handovers once their remaining useful facts are
  captured in the migration audit
- Legacy plans, audits, and research notes that only describe deleted modules,
  abandoned topology, or branch-local execution state already represented in
  `.vault/exec/`
- Duplicate or contradicted ADR text once a single canonical `.vault/adr/`
  replacement exists

## Recommendation

Treat this feature as a documentation authority reset:

- `.vault/` becomes the sole home for architecture, research, planning, audit,
  and execution records.
- Only migrate legacy documents that remain current, unique, and useful to the
  present repository.
- Remove stale or contradictory records instead of keeping them in an "archive"
  that continues to confuse code comments and future work.
