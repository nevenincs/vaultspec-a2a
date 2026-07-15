---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S14'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
---

# Reconcile the AuthoringToolBinding production construction site honestly: rag-first locate what W03 S19 actually landed versus the S20-deferred binding assembly, construct what production needs (or record precisely why the document topology needs none), and correct the W03 records only on source evidence

## Scope

- `src/vaultspec_a2a/worker/graph_lifecycle.py`
- `src/vaultspec_a2a/authoring/`
- `.vault/exec/2026-07-14-a2a-edge-conformance/`

## Description

- Ground rag-first, then confirm with an exact-symbol sweep, where the authoring tool binding is constructed in the codebase today.
- Read the production wiring amendment to decide whether the document topology requires a binding construction site now.
- Reconcile the W03 records against that verified reality with a dated correction note, correcting only on source evidence and never rewriting history.

## Outcome

Verified reality: the authoring tool binding has NO production construction site. Semantic search returns only its definition module, and an exact constructor sweep finds the binding built solely in test modules and the deferred solo-coder driver — never in the worker lifecycle, the session wiring, or any run-start path. The worker node accepts a binding parameter but defaults it unset, and no production caller supplies one. This matches the W03 record exactly: S19 landed the binding mechanism, and the assembly was explicitly deferred to S20.

Decision on construction: none is built, and this is the correct decided posture, not a gap. The production wiring amendment splits the two tool-exposure mechanisms deliberately. Document topologies such as the research-to-ADR family author through the in-process graph-submitter path (gate nodes calling the authoring session directly); that path is deterministic and replay-exact and needs no binding. The MCP bridge the binding feeds is the agent-initiated tool path for CLI-coder presets and stays behind the upstream tool-surfacing re-arm watch. Building a binding construction site now would be dead, ungated code for a path that is deliberately dormant; the amendment does not call for one. The single construction site the amendment does name (the worker lifecycle) is where the production submitter and any future binding would be assembled, and that submitter construction is the separate sibling step, not this one.

Records reconciliation: the W03 S19 record was accurate but implicit about the deferral, so a dated correction note was appended making it explicit that the step wired the mechanism only, that no production construction site exists by decision, and that the CLI-coder bridge stays behind the re-arm watch while document topologies use the graph-submitter. The W03 S20 step remains open as that watch item, and its record already states the deferral honestly. No checkbox was flipped: the wiring step stays closed because the wiring is real, and the leaf-proof step stays open because the leaf proof is genuinely deferred — both already match executable reality.

## Notes

- This step reads the worker lifecycle module but does not edit it; the sibling construction-site step owns that edit. No source files were changed here — the reconciliation is a records correction grounded in a read-only source sweep.
- Correction applied by appending to the existing record, per the single-home-fact rule; prior prose was left intact.
