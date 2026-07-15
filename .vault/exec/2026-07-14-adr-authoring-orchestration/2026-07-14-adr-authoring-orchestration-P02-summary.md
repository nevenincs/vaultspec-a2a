---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
---

# `adr-authoring-orchestration` `P02` summary

P02 built the full set of phase-machine primitives and wired them into the `research_adr` topology. S03 added state schema; S04 added the Send-based fan-out; S05 added the generalized phase-gate node; S06 composed all three into the first end-to-end structural run of the research-to-ADR shape, parking at the first human gate with a correct `document_approval_request` payload. Full default suite (1373 tests) is green at the close of the phase.

- Modified: `src/vaultspec_a2a/thread/state.py`
- Modified: `src/vaultspec_a2a/thread/tests/test_state.py`
- Created: `src/vaultspec_a2a/graph/nodes/diverge.py`
- Modified: `src/vaultspec_a2a/graph/nodes/__init__.py`
- Created: `src/vaultspec_a2a/graph/nodes/phase_gate.py`
- Modified: `src/vaultspec_a2a/graph/compiler.py`
- Modified: `src/vaultspec_a2a/team/team_config.py`
- Created: `src/vaultspec_a2a/graph/tests/nodes/test_diverge.py`
- Created: `src/vaultspec_a2a/graph/nodes/tests/test_phase_gate.py`
- Created: `src/vaultspec_a2a/graph/tests/test_research_adr.py`

## Description

S03 extended `TeamState` with three fields: `research_findings` (accumulates per-thread findings from the diverge stage via an append-only reducer in arrival order with no dedup), `gate_phase` (the most recently gated document phase, last-write-wins), and `gate_verdict` (the reviewer's verdict: `approved`, `rejected`, or `request_changes`). All fields are JSON-serializable primitives, preserving the SQLite checkpointer constraint. The schema test was extended to cover the new annotation keys; new reducer unit tests cover ordered append, parallel-branch accumulation, empty-update passthrough, and non-mutation of the prior list.

S04 introduced the Send-based diverge stage as three reusable primitives: a dispatch node that returns `Command(goto=[Send(researcher, state), ...])` — one per research thread, carrying the full current state so every branch sees the shared context; a researcher branch node that runs a `ResearchFindingProducer` and appends the single result to `research_findings` without touching the message channel; and a `_wire_diverge_stage` compiler helper that adds the dispatch node, all researcher nodes, and static edges from each researcher into the synthesis join node. A `ResearchFindingProducer` Protocol seam keeps branch nodes decoupled from model wiring. Real-graph tests over a `StateGraph` with `InMemorySaver` (no mocks) prove dispatch emits the correct `Send` count, each branch appends exactly one finding, the full accumulation is observable at the join, and the namer is deterministic.

S05 generalized the existing `create_plan_approval_node` pattern into `create_phase_gate_node`, a factory parameterized by document phase, a `DocumentProposalSubmitter` Protocol, and approved/revision routing targets. The submit runs deterministically before `interrupt()` on every pass — including replays — because the submitter is idempotent by contract (same proposal id yields a no-op). The interrupt payload is `{"type": "document_approval_request", "phase", "proposal_id", "feature"}`; the resume payload is `{"verdict", "notes"}`. Routing uses `Command.goto`: approved records `gate_phase` / `gate_verdict` and advances; rejected and request_changes append the reviewer note to `validation_errors` and route to the phase writer; any unrecognized verdict fails closed to revision. Real-graph tests with real interrupt/resume (no mocks) cover all six routing paths including the fail-closed unknown verdict and idempotent resubmission.

S06 wired all three primitives into the compiler. `RESEARCH_ADR` was added to `TopologyType` (resolving the preset-listing failures the `vaultspec-adr-research` preset had caused since P04.S09 staged it while the enum lacked the member). `ResearchThreadSpec` and `research_threads` were added to `TopologyConfig`. A fourth dispatch branch in the compiler routes `research_adr` to `_compile_research_adr`, which builds: START into the S04 diverge stage (one researcher branch per thread spec, defaulting to a single branch when unconfigured), join into the synthesist, an inner doc-review loop (a `REVISION REQUIRED` sentinel routes back to the writer; anything else advances), the S05 research phase gate, the adr-author writer, a second inner doc-review loop, and the S05 adr phase gate advancing to END. Required-role resolution raises a `ConfigError` when any of researcher, synthesist, adr-author, doc-reviewer, or the proposal submitter is missing. Tests over the real preset with a stub provider factory and a fake submitter prove the expected node set, both config-error paths, and a complete fan-out-synthesize-review-gate run that parks at the first gate with the correct `document_approval_request` payload and both findings accumulated.

**S06 commit stranding and recovery.** The S06 commit was delayed by repeated `ty` pre-commit hook failures caused by a concurrent provider-session's in-flight files that were unstaged at commit time. On the first commit attempt, `prek` stashed the unstaged changes to a `.prek-home/patches/` patch file, ran hooks, and the vault-fix hook modified staged vault files. Because the hook chain failed on `ty`, the commit was rejected but the patch was restored. The critical lesson: vault-fix and vault-doctor-deep hooks modify staged files in place during each `prek` pass; after any failed commit attempt, all S06 files must be re-added before the next attempt, or the commit will contain stale hook-pre-modification content. The safe pattern — re-stage the full target set after each `prek` pass, verify with `git diff --cached --name-only`, then commit — was applied to land the commit cleanly once the concurrent `ty` blocker was resolved.

Verification: the full default pytest suite (1373 tests) passes at commit `c056241`. `ruff check`, `ruff format`, and `ty check` are clean across all P02 changed modules.
