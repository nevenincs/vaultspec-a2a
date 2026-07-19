---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S12'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---

# Run clone-to-CI acceptance, formal review, finding classification, audit queue updates, and execution summaries

## Scope

- `.vault/audit`
- `.vault/exec`

## Description

- Exercise Core setup twice in a fresh clone and prove bounded Git-ignore and
  Prek convergence without tracked drift.
- Exercise RAG setup twice, verify version authority, and prove dependency-mode
  enrollment preserves the hardened hook configuration.
- Run code, test, package, documentation, workflow, Compose, and host diagnostic
  acceptance surfaces.
- Correct every critical and high formal-review finding, then repeat focused and
  clean-clone validation.
- Classify residual findings in the rolling audit and assign their owning queue.
- Scaffold and reconcile the L3 Phase summaries and feature index.

## Outcome

Core 0.1.48 and RAG 0.3.2 converge reproducibly from the project lock. Two
successive Core and RAG setup runs preserve `prek.toml`, create no legacy hook
configuration, and leave tracked files unchanged. The canonical code checks,
package build, documentation tests and strict Sphinx build, workflow lint,
workflow parsing, Compose configuration, and Windows diagnostics pass.

The full unit selection executed 2,141 tests: 2,126 passed and 15 exposed
pre-existing or concurrently owned product-contract failures. Those failures
remain visible and are assigned to the codebase-health and owning feature audit
queues. Formal review found no unresolved critical or high defect after the
correction pass.

## Notes

An initial compatibility wrapper could overwrite concurrent edits during forced
Core adoption. Formal review classified that design as critical; it was removed
and replaced with disposable-clone adoption, byte verification, exclusive
runtime-state creation, and non-destructive live sync. Clean-clone acceptance
later caught a PowerShell quoting error in the RAG authority check before
closure. Linux Docker execution was blocked by the local Docker Desktop engine
returning HTTP 500, although CLI discovery and every resolved Compose
configuration passed. No data loss occurred.
