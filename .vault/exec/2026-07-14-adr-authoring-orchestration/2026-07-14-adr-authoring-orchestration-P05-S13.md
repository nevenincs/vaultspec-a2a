---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S13'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
---

# Make graph_lifecycle the single construction site with rag-first discovery before editing: build the AuthoringSession factory and production submitter from run-start facts (engine origin via discovery or explicit config, run id, RunTokenStore) and pass proposal_submitter into compile_team_graph for research_adr presets, raising typed fail-closed construction errors (engine unavailable, identity missing, submitter unconfigured, role config invalid, credentials missing) surfaced as truthful run failure

## Scope

- `src/vaultspec_a2a/worker/graph_lifecycle.py`
- `src/vaultspec_a2a/authoring/`

## Description

Make `graph_lifecycle` the single construction site for the production authoring
submitter (ADR PW2). Commit `02565e4`.

Modified: `src/vaultspec_a2a/worker/graph_lifecycle.py`,
`src/vaultspec_a2a/worker/executor.py`.

- Thread the Executor's `RunTokenStore` into `GraphLifecycleManager` so the
  submitter reads per-role tokens from the same worker-scoped store (R7 lifecycle
  intact).
- `_build_proposal_submitter` resolves the engine origin via discovery and, for
  `research_adr` presets only, constructs the `DocumentProposalSubmitter` and
  passes `proposal_submitter=` into `compile_team_graph`. It FAILS CLOSED at build
  time — a typed `EngineUnavailableError` propagates as `GraphCompilationError`
  and a truthful run failure — when no engine is reachable, so a research_adr run
  that cannot author never starts vague. The compiler's existing fail-closed guard
  (`ConfigError` when `proposal_submitter` is None) is untouched, and non-document
  topologies pass `None` as before.
- The per-phase specs map each document phase to its writer node
  (`synthesis`/`adr_author`) and authoring role; thread id, feature, bearer, and
  document body are resolved per run from state + the store, so the cached graph
  is reused safely across runs.

## Outcome

Complete. `ruff`/`ty` clean; the worker suite is green (66 passed) with the new
`GraphLifecycleManager` signature and construction site. The Executor is the only
constructor of the manager and passes the token store. The whole wired stack is
proven live by S12's submitter tests and is exercised end to end by the P04.S10
finale.

## Notes

The construction site couples a research_adr compile to engine liveness by
design (PW2: a run that cannot author never starts). Non-research presets are
unaffected. The engine origin comes from discovery (`resolve_engine`); explicit
config is the documented alternative if discovery is unavailable.
