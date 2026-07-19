---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S01'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---

# Define explicit base, server, RAG, tooling, and all profiles with bounded Core and RAG upgrades

## Scope

- `pyproject.toml`
- `uv.lock`

## Description

- Make the default environment the dependency-free base profile.
- Preserve the server and RAG extras while bounding RAG to the compatible 0.3 line.
- Define tooling and all dependency groups, retain the dev compatibility alias, and include the existing docs group in all.
- Bound Vaultspec Core to the compatible 0.1 line and remove its floating branch source.
- Regenerate the project lock from published package releases.

## Outcome

`uv lock` resolved `vaultspec-core` 0.1.48 and `vaultspec-rag` 0.3.2. Frozen dry-runs passed for base, server, RAG, tooling, and all profiles. Isolated project-lock executions reported Core 0.1.48 and RAG 0.3.2. The formal review passed with no critical, high, medium, or low findings.

## Notes

The pre-existing docs dependency group and the `packaging` test dependency were retained. No verification was skipped and no persistent failure occurred.
