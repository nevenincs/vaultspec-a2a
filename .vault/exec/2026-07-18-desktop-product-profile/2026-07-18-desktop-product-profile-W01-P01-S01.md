---
tags:
  - '#exec'
  - '#desktop-product-profile'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S01'
related:
  - "[[2026-07-18-desktop-product-profile-plan]]"
---

# Split install metadata into a Torch- and RAG-free desktop runtime closure plus explicit optional capability groups

## Scope

- `pyproject.toml`

## Description

- Remove PostgreSQL checkpoint, driver, and OTLP exporter packages from the default desktop dependency closure.
- Publish those server-only packages through the `server` extra.
- Publish Torch and `vaultspec-rag` through the separately installed `rag` extra.
- Scope the explicit CUDA Torch source to the `rag` extra.
- Remove the obsolete RAG-installer ownership marker now that product metadata owns the optional Torch declaration.
- Retain the existing local-only `dev` dependency group.

## Outcome

The default published runtime metadata is free of Torch, RAG, PostgreSQL, and
the OTLP gRPC exporter. `vaultspec-a2a[server]` restores the PostgreSQL and
exporter capability, while `vaultspec-a2a[rag]` restores the heavyweight RAG
capability. For uv-managed project and locked capsule resolution, selecting the
`rag` extra also activates the CUDA Torch source override.

TOML parsing and structural assertions passed. Non-writing uv validation passed
for full lock resolution, lock consistency, the default desktop install, the
`server` extra, and the `rag` extra. Exported install-graph inspection confirmed
that none of the six optional package families leaks into the desktop base and
that each extra restores its declared capability packages.

## Notes

`uv.lock` regeneration belongs to `W01.P01.S02` and was not performed by this
step. S01 metadata normally leaves the lock temporarily stale until S02; a
concurrent S02 lock update was already present during final validation. All
non-writing commands preserved its SHA-256 digest
`2B24821FEBF1EDE3792E1A7B9F469729C641E018DA6A64C97B6EB5E42346D330`.

No certification test was added because installed-metadata coverage belongs to
`W01.P01.S05`. The plan row remains open for independent review.

The CUDA index is uv project-source metadata; it is not published in wheel
`Requires-Dist` metadata. Ordinary wheel consumers must provide an appropriate
Torch index themselves. The desktop capsule therefore consumes the uv-managed
lock rather than relying on wheel metadata to carry that source override.
