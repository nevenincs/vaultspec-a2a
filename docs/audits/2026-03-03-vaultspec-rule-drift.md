---
title: VaultSpec Rule Drift Audit
date: 2026-03-03
scope: .vaultspec behavioural rules vs A2A engine (src/vaultspec_a2a/core/, src/vaultspec_a2a/api/, src/vaultspec_a2a/worker/)
auditor: docs-researcher-2
---

# VaultSpec Rule Drift Audit

**Date:** 2026-03-03
**Scope:** All behavioural rules in `Y:/code/vaultspec-worktrees/main/.vaultspec/` vs
A2A engine behaviour in `src/vaultspec_a2a/core/`, `src/vaultspec_a2a/api/`, `src/vaultspec_a2a/worker/`.

Focus areas per mandate: pipeline phase gates, agent persona loading, artifact
validation, wikilink/reference resolution.

Formatting rules (frontmatter field names, filenames, YAML syntax) are excluded.

---

## Drift Summary Table

| ID   | Rule                                                                                                                                                                         | Source file                                                                                                                                           | Engine behaviour                                                                                                                                                                                                                                                                                                            | Drift severity |
| ---- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- |
| D-01 | Pipeline MUST gate phases — each phase requires its predecessor artifact before proceeding (Research → ADR requires research artifact; Execute requires approved plan)       | `framework.md`                                                                                                                                        | Engine routes purely on LLM text output from supervisor. No artifact existence check gates phase transitions. Supervisor can route to executor with no plan artifact present.                                                                                                                                               | HIGH           |
| D-02 | User MUST approve plan before execution proceeds                                                                                                                             | `framework.md` ("The user must approve plans before execution proceeds")                                                                              | No plan-approval interrupt exists in the graph. The supervisor can route directly to an executor worker without any human-in-the-loop approval gate for the plan.                                                                                                                                                           | HIGH           |
| D-03 | Mandatory code review after every execute cycle — vaultspec-review skill MUST be invoked; CRITICAL/HIGH findings MUST be resolved before proceeding                          | `vaultspec-execute/SKILL.md`, `vaultspec-standard-executor.md`                                                                                        | No automatic review invocation exists in graph routing. The supervisor may route to FINISH after an executor worker completes without invoking a reviewer agent. The `validation_errors` FINISH gate (ADR-022) blocks on validation errors but does not enforce review invocation.                                          | HIGH           |
| D-04 | Executor agents MUST write a Step Record to `.vault/exec/{feature}/{step}.md` for every completed phase                                                                      | `vaultspec-execute/SKILL.md` ("Ensure the executor writes a Step Record")                                                                             | Engine does not verify or enforce step record creation. The executor worker's TOML persona instructs it to create step records, but there is no post-execution structural check that the file was actually written to the correct path. A worker can return without creating a step record and the graph proceeds.          | MEDIUM         |
| D-05 | After executor completes, Phase Summary MUST be written to `.vault/exec/{feature}/{phase}-summary.md`                                                                        | `vaultspec-execute/SKILL.md`                                                                                                                          | Same as D-04: no structural enforcement. Summary creation is persona-instructed only.                                                                                                                                                                                                                                       | MEDIUM         |
| D-06 | Artifacts MUST use EXACTLY TWO tags in frontmatter (`tags:` field): one directory tag + one feature tag                                                                      | `vaultspec-documentation.builtin.md`, `vaultspec-execute/SKILL.md`, `vaultspec-research/SKILL.md`                                                     | Engine performs no YAML frontmatter validation on artifacts written by workers. The `validation_errors` accumulator (ADR-019 §2.1) exists for this purpose but no node currently populates it with tag validation results.                                                                                                  | MEDIUM         |
| D-07 | `related:` field MUST use quoted `"[[wiki-links]]"` — no relative paths, no bare strings                                                                                     | `vaultspec-documentation.builtin.md`                                                                                                                  | Engine does not validate or rewrite `related:` fields after artifact writes. No wikilink resolver exists in the engine — `src/vaultspec_a2a/core/` has no module that parses or validates `[[...]]` syntax in written files.                                                                                                              | MEDIUM         |
| D-08 | Before starting a new pipeline phase, engine MUST check `.vault/` for existing artifacts and resume in-progress work rather than starting fresh                              | `framework.md` ("Before starting a new pipeline phase, check `.vault/` for existing artifacts... Resume work in progress rather than starting fresh") | `_build_initial_vault_index` (ADR-019) scans `.vault/` at thread creation and populates `vault_index`. However, the supervisor does not use `vault_index` to detect in-progress work and resume it. The supervisor routes based on LLM text, not on artifact presence. Phase resumption logic is absent.                    | MEDIUM         |
| D-09 | Agent persona selection MUST match task complexity — complex architectural changes → complex-executor, standard features → standard-executor, simple edits → simple-executor | `vaultspec-execute/SKILL.md`                                                                                                                          | The A2A engine uses a static team composition defined in TOML at compile time. There is no runtime agent tier selection based on task complexity. The supervisor routes to the roster of available workers as defined in the team preset — it cannot dynamically substitute a higher-tier executor for a more complex task. | MEDIUM         |
| D-10 | Before starting execution, executor MUST consult `<ADR>`, `<Research>`, and `<Reference>` documents as PRIMARY technical references                                          | `vaultspec-standard-executor.md` ("CONSULT CONTEXT: ADR, Research, and Reference documents are your PRIMARY technical references")                    | ADR-022 anchoring injects vault paths as metadata. ADR-020 (pending implementation) will inject actual content. Currently (pre-ADR-020), workers see paths in the anchoring summary but must issue tool calls to read file content. There is no enforcement that the worker reads binding documents before acting.          | MEDIUM         |
| D-11 | `pipeline_phase` must be set by supervisor on first routing pass and updated as the pipeline progresses                                                                      | ADR-019 §2.1, mirroring `framework.md` phase taxonomy                                                                                                 | `pipeline_phase` field exists in `TeamState` (ADR-019) but is never set by the supervisor at runtime. No supervisor logic reads or writes `pipeline_phase`. The field remains `None` throughout all sessions.                                                                                                               | MEDIUM         |
| D-12 | Wikilinks in artifacts MUST use `[[wiki-links]]` syntax — `@ref` and `[label](path)` are forbidden for internal links                                                        | `vaultspec-documentation.builtin.md`, `vaultspec-research/SKILL.md`                                                                                   | Engine has no wikilink parser or resolver. Links in worker-written artifacts are not validated. No enforcement of link syntax at write time.                                                                                                                                                                                | LOW            |
| D-13 | Executor MUST invoke `vaultspec-code-reviewer` sub-agent and MUST NOT mark task complete until review passes                                                                 | `vaultspec-standard-executor.md` ("YOU MUST invoke vaultspec-code-reviewer... DO NOT mark the task as complete until the review passes")              | This is a persona instruction only. The graph has no structural gate that prevents a worker from returning and the supervisor routing to FINISH without a reviewer agent having been invoked.                                                                                                                               | HIGH           |
| D-14 | vaultspec-review skill MUST persist review artifact to `.vault/exec/{feature}/{feature}-review.md` with `#exec` + feature tags                                               | `vaultspec-review/SKILL.md`                                                                                                                           | Engine does not validate that a review artifact exists before allowing FINISH. No review artifact path is tracked in `vault_index` or `TeamState`.                                                                                                                                                                          | MEDIUM         |

---

## Findings by Focus Area

### 1. Pipeline Phase Gate Mandates

**Critical gap (D-01):** The vaultspec framework defines a strict dependency graph:
Research artifact required before ADR, ADR required before Plan, approved Plan required
before Execute. The engine performs zero artifact-existence checks at phase transitions.
The supervisor routes purely on LLM text output. A thread can proceed from initial
message to executor invocation with no research or plan artifacts present.

**User approval gate absent (D-02):** `framework.md` explicitly states "The user must
approve plans before execution proceeds." The engine has no plan-approval interrupt.
The `interrupt_before=[]` design decision (per CLAUDE.md) means pre-node pauses are
disabled. A separate explicit plan-approval interrupt would be required to satisfy
this mandate.

**Phase resumption absent (D-08):** The `vault_index` populated by ADR-019 gives the
supervisor the data needed to detect in-progress work, but no supervisor logic uses
this data to check "does a plan already exist for this feature?" before routing to a
planner worker.

**`pipeline_phase` never populated (D-11):** The field exists in state but no node
writes to it. Phase-aware routing (e.g., "route to researcher because phase is
research") is structurally impossible without it.

### 2. Agent Persona Mandates

**No runtime tier selection (D-09):** VaultSpec mandates dynamic executor tier
selection (complex/standard/simple) based on task complexity. The A2A engine uses
a static team roster compiled at graph creation time. Runtime tier substitution
requires either a dynamic team composition mechanism or a meta-agent that re-compiles
the graph with a different worker set.

**Persona instructions not structurally enforced (D-10):** The `vaultspec-standard-executor`
persona instructs workers to "CONSULT CONTEXT" before acting. Until ADR-020 is
implemented, actual document content is not injected — workers see only paths. Even
after ADR-020, the engine cannot verify that the worker read the documents before
making implementation decisions.

### 3. Artifact Validation Mandates

**No frontmatter validation (D-06):** The `validation_errors` accumulator in
`TeamState` (ADR-019) was designed precisely for this: nodes append validation errors
when artifacts have incorrect structure. No node currently performs post-write
frontmatter validation. Tag count, tag format, `related:` syntax — all are
uninspected after worker writes.

**No step record enforcement (D-04, D-05):** The engine trusts worker persona
instructions to create step records and summaries. No graph node checks for the
existence of these required artifacts after worker completion.

**No review artifact enforcement (D-14):** The review artifact path is never tracked
in `vault_index` or checked before FINISH.

### 4. Wikilink / Reference Mandates

**No wikilink resolver (D-12):** `src/vaultspec_a2a/core/` contains no module for parsing or
resolving `[[wiki-links]]`. Written artifacts are not scanned for link syntax
compliance. This is the largest structural gap relative to vaultspec's documentation
mandate, which specifies `[[wiki-links]]` exclusively for all internal references.

**`related:` field unvalidated (D-07):** Workers may write `related:` fields with
relative paths or bare strings. No post-write validation catches this.

---

## Pre-existing Drift Items (from alignment tracker)

The following items were already tracked in `docs/audits/2026-03-03-sdd-alignment-tracker.md`
and are not duplicated here:

- DRIFT-03: No mount step (Pending ADR-020 implementation)
- DRIFT-04: No persistent task queue (Pending ADR-021 implementation)
- DRIFT-07: No `{{FEATURE_CONTEXT}}` in supervisor TOML presets
- DRIFT-08: `compile_team_graph()` missing `feature_tag` param (API shape deviation)
- DRIFT-09: `.get()` used for SDD fields in anchoring/supervisor
- DRIFT-10: SDD fields declared `NotRequired` vs required

---

## Severity Classification

| Severity | Count | Items                                                |
| -------- | ----- | ---------------------------------------------------- |
| HIGH     | 4     | D-01, D-02, D-03, D-13                               |
| MEDIUM   | 9     | D-04, D-05, D-06, D-07, D-08, D-09, D-10, D-11, D-14 |
| LOW      | 1     | D-12                                                 |

---

## Recommended Prioritisation

1. **D-02 (Plan approval gate)** — Directly blocks safe autonomous execution. Requires
   a human-in-the-loop interrupt at the plan→execute boundary.
2. **D-03 / D-13 (Mandatory code review)** — The review gate is the primary quality
   control mechanism in vaultspec. Without structural enforcement, it is trivially
   bypassed.
3. **D-01 (Phase artifact gates)** — Prevents "garbage-in" execution from proceeding
   without required upstream artifacts.
4. **D-11 (`pipeline_phase` population)** — Prerequisite for phase-aware routing and
   for ADR-020 phase-scoped mounting to function correctly.
5. **D-06 (Frontmatter validation)** — The `validation_errors` accumulator already
   exists; a post-write validator node is the only missing piece.

## References

- `Y:/code/vaultspec-worktrees/main/.vaultspec/rules/system/framework.md`
- `Y:/code/vaultspec-worktrees/main/.vaultspec/rules/system/workflow.md`
- `Y:/code/vaultspec-worktrees/main/.vaultspec/rules/rules/vaultspec-documentation.builtin.md`
- `Y:/code/vaultspec-worktrees/main/.vaultspec/rules/rules/vaultspec-subagents.builtin.md`
- `Y:/code/vaultspec-worktrees/main/.vaultspec/rules/skills/vaultspec-execute/SKILL.md`
- `Y:/code/vaultspec-worktrees/main/.vaultspec/rules/skills/vaultspec-review/SKILL.md`
- `Y:/code/vaultspec-worktrees/main/.vaultspec/rules/agents/vaultspec-standard-executor.md`
- `docs/audits/2026-03-03-sdd-alignment-tracker.md` — pre-existing drift items
- `docs/adrs/019-teamstate-enrichment-sdd-blackboard.md` — validation_errors accumulator
- `docs/adrs/022-contextual-anchoring-graph-lifecycle.md` — anchoring, FINISH gate
