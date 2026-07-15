---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S06'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
---

# Wire the research_adr topology type through team config and the compiler with structural phase sequencing

## Scope

- `src/vaultspec_a2a/graph/compiler.py`
- `src/vaultspec_a2a/team/team_config.py`

## Description

- Added the `RESEARCH_ADR` member to the topology enum and a `ResearchThreadSpec`
  model plus a `research_threads` field on the topology config so a preset can
  declare the diverge stage's parallel branches.
- Added a `proposal_submitter` parameter to the compiler entry point and a
  fourth dispatch branch that routes the research_adr topology to a new
  `_compile_research_adr` builder.
- Composed the document phase machine structurally: START into the S04 diverge
  stage (one researcher branch per thread spec, defaulting to a single branch
  when unconfigured), a join into synthesis, an inner doc-review loop, the S05
  research phase gate, the adr-author writer, a second inner doc-review loop, and
  the S05 adr phase gate advancing to END.
- Bridged the researcher model into a `ResearchFindingProducer` that scopes one
  model turn to the branch's thread spec and packages the response as a finding.
- Resolved one model per required role (researcher, synthesist, adr-author,
  doc-reviewer) from the team workers, raising a config error when a required
  role or the proposal submitter is missing.
- Implemented the inner doc-review router: a REVISION sentinel routes back to the
  phase writer, anything else advances to the phase gate, keeping the human gate
  as the backstop.
- Added tests over the real preset with a stub provider factory and a fake
  submitter: expected node set, missing-submitter and missing-role config errors,
  and a run that fans out, synthesises, passes review, and parks at the first
  document gate with the correct approval payload and accumulated findings.

## Outcome

- The research_adr topology compiles and runs end to end to its first human gate,
  composing the diverge (S04) and phase-gate (S05) primitives with structural
  phase sequencing.
- Adding the enum member also resolved the preset-listing failures the
  pre-existing `vaultspec-adr-research` preset caused while `research_adr` was
  not yet a valid topology type.
- Full default suite passes (1373 tests); `ruff check`, `ruff format`, and
  `ty check` are clean on the changed modules.

## Notes

- Research thread specs are compile-time structural rather than runtime-composed:
  the fan-out is fixed by config so the gate discipline is graph structure, not
  LLM convention, matching the ADR. The bundled preset declares none and compiles
  to a single default branch; operators declare `research_threads` for real N-way
  parallel research.
- The end-to-end research-to-ADR proof with live models and real proposals is
  P04.S10, out of this Step's scope; this Step proves the structural spine to the
  first gate with stub models.
- Landing this commit was delayed by an intermittent project-wide `ty` pre-commit
  hook failing on a concurrent session's in-flight provider files; the failures
  were foreign to this Step's scope.
