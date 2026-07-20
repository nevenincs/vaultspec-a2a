---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S02'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---

# Add locked setup, sync, upgrade, status, and service recipes for Core and RAG

## Scope

- `just/dev/deps.just`
- `just/dev/vault.just`
- `just/dev/rag.just`

## Description

- Added explicit lock-backed base, server, RAG, tooling, all, and lock-check
  dependency recipes.
- Added Core enrollment, sync, upgrade, doctor, and status recipes that execute
  from the tooling group and preserve Core ownership of generated state.
- Added RAG enrollment, index, status, service, logs, and explicit warmup recipes
  that execute from the RAG extra without implicit model or Qdrant provisioning.
- Selected profile-root working directories and native PowerShell execution for
  direct module use on Windows.

## Outcome

All three modules parse and pass `just --fmt --check`. Core install and sync
previews, RAG install preview, RAG index discovery, and lock validation pass
against Core 0.1.48 and RAG 0.3.2. Mutating downloads, upgrades, and service
starts remain explicit recipes.

## Notes

Review found and corrected two issues before close: RAG 0.3.2 does not expose a
public `--mode` install flag, and standalone Just modules initially selected Git
Bash on Windows. The final recipes use the detected project dependency mode and
an explicit native PowerShell shell. No persistent finding remains.
