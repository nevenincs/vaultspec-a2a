---
tags:
  - '#exec'
  - '#multi-provider-execution'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S16'
related:
  - "[[2026-07-15-multi-provider-execution-plan]]"
---

# Run a live research_adr run under the mixed-provider profile end to end riding the standing acceptance harness (PW7) once the adr-authoring-orchestration P04.S10 finale harness lands, verifying per-role attribution and document quality hold across providers

## Scope

- `src/vaultspec_a2a/service_tests/`

## Description

Ran a live research-to-ADR run under the mixed codex/claude provider profile end
to end on the standing PW7 acceptance harness (the adr-authoring-orchestration
P04.S10 finale harness, now landed), verifying per-role attribution and document
quality across providers.

- Selected the provider axis through the harness per-case `profile_id`: the new
  `codex` profile on the `vaultspec-adr-research` preset (S15), MIXED gate shape
  (research AUTO, ADR HUMAN) mirroring the live-mixed case.
- Booted an own gateway/worker pair on free ports with an own scratchpad SQLite
  checkpoint and the authoring subscriber enabled, attached to the shared
  dashboard engine (attach-never-own); real Codex spend, file-based ChatGPT
  session auth.
- Drove the full loop programmatically over the engine review surface: research
  AUTO system-auto-approve+apply under `system:operation-modes`, mode downgrade to
  manual (requeued 0, applied research marker undisturbed), ADR HUMAN gate 409
  stale-review fence, reject-with-notes (edit_proposal), codex re-author, approve,
  apply.

## Outcome

GREEN. The mixed codex/claude lane passed end to end in 14m24s (run
`pw7-1784166683`). Two substantial codex-authored documents materialized on the
engine workspace vault: a 15.6 KB research document and a 10.1 KB ADR that
wiki-links the research by stem - both real content, zero template annotations,
zero placeholders, valid frontmatter.

Per-role provider attribution, read from the live run-status `assignments`
(runtime evidence, not inference): researcher, synthesist, and adr-author resolved
to `codex` with `source=profile`; doc-reviewer resolved to `claude` with
`source=agent`. Codex authors both documents; Claude runs the inner quality gate -
the genuine cross-provider collaboration the mixed profile promises.

Document quality held across providers: the codex-authored research and ADR passed
the a2a `ScaffoldEchoError` submit guard and the engine apply, and the ADR
correctly cited the research document by stem in its `related` frontmatter and
body.

## Notes

The pure-HUMAN acceptance lane's intermittent request_changes-recovery control
race (documented on the adr-authoring-orchestration P04.S10 record) is unrelated
to the provider axis and was not exercised here - this lane's HUMAN gate is the
ADR gate only (MIXED shape), which is solid. The Z.ai sibling lane is
credential-blocked (no `ZAI_AUTH_TOKEN`) and ships as a truthful skip, not a live
proof; see S15 for the zai profile and the harness skip gate.
