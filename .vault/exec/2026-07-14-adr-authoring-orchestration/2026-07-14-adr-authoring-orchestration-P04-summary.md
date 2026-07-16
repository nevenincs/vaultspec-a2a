---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-16'
modified: '2026-07-16'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
  - "[[2026-07-14-adr-authoring-orchestration-P04-S16]]"
---

# `adr-authoring-orchestration` `P04` summary

P04 built the research_adr document-authoring topology and its acceptance instrument, then closed the two gaps a live acceptance run surfaced: an empty grounding `related:` and a non-canonical status marker on the materialized ADR. S09 authored the persona TOMLs and the `vaultspec-adr-research` team preset. S10 built the standing, parameterized PW7 acceptance harness (`AcceptanceCase`/`AcceptanceHarness`) and drove it across the full HUMAN/AUTO/MIXED verdict-lane matrix and the provider axis (deterministic, live Claude, codex), surfacing and fixing a chain of engine and control-layer defects along the way (submit-node conformance, the engine's whole-document apply body-drop, a request_changes-recovery resume race). S16 closed the last defect the acceptance run caught after those fixes landed: the materialized ADR passed structurally but failed `vault check all`'s `schema` gate with `related: []` (no grounding references) and a legacy `## Status` section.

- Modified (engine, `0c05f0dc5f`): `engine/crates/vaultspec-api/src/authoring/api/mod.rs`, `.../apply/mod.rs`, `.../apply/tests/group1.rs`, `.../apply/tests/helpers2.rs`, `.../conflicts/tests.rs`, `.../direct_write/mod.rs`
- Modified (a2a, `3f5c5e8`): `src/vaultspec_a2a/authoring/submitter.py`
- Created (a2a, `3f5c5e8`): `src/vaultspec_a2a/authoring/tests/test_submitter_content.py`
- Modified: `src/vaultspec_a2a/team/presets/agents/vaultspec-adr-author.toml`
- Created: `src/vaultspec_a2a/service_tests/test_pw7_acceptance.py` (S10, extended across the campaign)

## Description

S09 authored the four `research_adr` personas (researcher, synthesist, adr-author, doc-reviewer) and the `vaultspec-adr-research` team preset wiring them together on the new document-authoring topology.

S10 built the standing PW7 acceptance harness as a reusable, parameterized live pytest driver: an `AcceptanceCase`/`AcceptanceHarness` pair that mints actor tokens, drives hardened v1 run-start refusals (422 on missing feature tag / incomplete token bundle), and choreographs verdicts programmatically over the engine review surface for three per-gate policies (HUMAN reject-with-notes -> revision -> approve, AUTO system-actor auto-approval under `system:operation-modes`, MIXED a distinct policy per gate in one run) plus a provider axis (deterministic in-process test model as the fast default, live Claude, codex mixed-profile). Landing this harness surfaced and closed a long chain of real defects across two repos: a dead `Provider.DETERMINISTIC` readiness branch, the engine's whole-document `CreateDocument` apply discarding the authored body (fixed engine-side as a two-step create+set-body apply plus a path-collision scope fix), a submit-node scaffold-echo gap, a harness wire-contract mismatch on the decision `CommandKind`, and an intermittent request_changes-recovery resume race in the control layer (fixed by broadening parked-run reconciliation to `RUNNING` candidates keyed on checkpoint truth). All three verdict lanes and the provider axis are live-proven green.

S16 closed the acceptance run's next real catch: a structurally valid ADR that nonetheless failed `vault check all`'s blocking `schema` gate, because `submitter.py`'s whole-document create op never threaded a `related:` grounding link (the author cannot self-author it - the two-step apply's `set-body` strips agent-authored frontmatter, and the applied research doc's real materialization date is unknowable to the writer) and because the adr-author persona could emit a legacy `## Status` section instead of the canonical H1 status token. The engine fix (`0c05f0dc5f`) threads a `related: Vec<String>` field through `ProvisionalCreate` into `vault add --related`; the a2a fix (`3f5c5e8`) resolves the feature's applied research/reference docs from the engine's recovery snapshot (`created_at_ms` -> canonical dated stem) and rides them as `related:[[stem]]` on the ADR-phase create op, while the submit node now refuses a legacy `## Status` body and the persona is hardened to emit the H1 token.

A fresh, isolated live acceptance re-run (own engine build/workspace/ports/PIDs) proved the fix on the first post-fix run: run `pw7-1784190507` materialized a research doc (13,741 bytes) and an ADR (9,076 bytes) with `related:` correctly grounded to `[[2026-07-16-pw7-acceptance-live-1784190507-research]]` and the canonical H1 status token, no `## Status` section. `vault check all` reported zero errors (`schema`/`adr-status`/`references`/`links`/`body-links` all clean; only cosmetic final-newline and missing-feature-index warnings). The lead independently re-verified: fetched all 11 research references (10 live and on-topic, 1 anchor-only), confirmed the `related:` date matches the research file's own materialization date (proving the `created_at_ms` grounding, not a hardcoded today), and confirmed the H1 token and substantively reasoned ADR prose. Full detail, verbatim vault-check output, and evidence in the S16 Step Record. P04 is complete: S09, S10, and S16 all closed.
