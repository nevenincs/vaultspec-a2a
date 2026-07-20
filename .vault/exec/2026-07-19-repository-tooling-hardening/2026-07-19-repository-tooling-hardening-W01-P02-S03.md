---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S03'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---

# Route workspace provisioning and agent RAG acquisition through deliberate locked versions with real subprocess tests

## Scope

- `src/vaultspec_a2a/cli/provision.py`
- `src/vaultspec_a2a/providers/_acp_mcp.py`
- `tests`

## Description

- Prefer the active Python environment's declared Core module over ambient
  console scripts and unpinned acquisition.
- Preserve console-script and `uvx` compatibility only for standalone
  installations without Core in their active environment.
- Pin agent RAG MCP acquisition to the locked `vaultspec-rag[mcp]==0.3.2`
  capability.
- Exercise both selected commands through real subprocess tests and remove the
  prior conditional skip from project-environment Core installation coverage.
- Run the targeted test suite, Ruff lint and format checks, Ty, and formal code
  review.

## Outcome

Workspace provisioning now executes Core 0.1.48 from the project environment,
independent of a conflicting executable on `PATH`. Non-desktop agent harnesses
acquire the exact RAG 0.3.2 MCP extra from any run workspace. The targeted suite
passed 48 tests; Ruff and Ty passed for every touched implementation and test
module. Formal review passed with no critical or high findings.

## Notes

The first format check identified two touched test modules and was resolved with
the configured formatter. Formal review also classified inherited fake-model
and shared-registry-mutation tests as medium code-health debt for S09; S03's new
tests use direct production imports and real subprocesses. No data loss,
scaffolds, skipped tests, or unresolved S03 implementation failures remain.
