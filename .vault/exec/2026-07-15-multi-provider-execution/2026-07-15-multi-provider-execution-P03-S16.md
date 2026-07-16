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

### Z.ai lane (2026-07-16)

GREEN. The Z.ai sibling lane - credential-blocked and shipped as a truthful skip
when this step first closed - now passes end to end on the real Z.ai endpoint:
run `pw7-1784221291`, 606.95s. It ran on the hardened worker (`decc667`, the
outer-gate-401 machine-bearer re-resolution), so the lane doubles as the
end-to-end validation of that bearer fix - the worker authored across a live,
concurrently-loaded shared engine with no stale-bearer failure.

Materialized documents (engine workspace vault, feature
`pw7-acceptance-zai-1784221291`):

- research: `2026-07-16-pw7-acceptance-zai-1784221291-research.md`
- adr: `2026-07-16-pw7-acceptance-zai-1784221291-adr.md`

Per-gate ledger classes (the MIXED per-gate proof, verbatim from the engine
surface):

- research AUTO gate -> `SystemPolicyApprovalRecord`: `system_actor.id =
  system:operation-modes`, `kind = system`, `mode = autonomous`, `policy_id =
  authoring.operation_modes`, proposal `status = applied` - the anti-bypass
  invariant held (system approval, never a human decision).
- adr HUMAN gate -> `ReviewDecisionRecord`: the full reject-with-notes ->
  revision -> approve chain (409 stale-review fence, `edit_proposal`
  request-changes, zai re-author, approve
  `approval:87ee24c5e422a225a2560d0b5352595e5dd0ca94`, apply).

Providers resolved per-role: researcher `glm-4.7-flagship`, synthesist +
adr-author `glm-5`, doc-reviewer on `claude` (the inner quality gate) - real Z.ai
spend, `ZAI_AUTH_TOKEN` env-injected from settings and never logged. Both
hardened run-start refusals (422 missing-feature, 422 missing-role) passed and
the verdict subscriber resumed the parked run across both gates.

An earlier attempt (`pw7-1784220945`) aborted at ~57s on a transient
shared-engine `ReadTimeout` in the harness's OWN `/v1/proposals` poll (not the
worker; the timeout passed through the bearer fix untouched, since it is not a
typed 401). The harness engine client's retry-less poll was then hardened with a
bounded transient retry (`aae97ff`), and the re-fired lane passed clean.

## Notes

The pure-HUMAN acceptance lane's intermittent request_changes-recovery control
race (documented on the adr-authoring-orchestration P04.S10 record) is unrelated
to the provider axis and was not exercised here - this lane's HUMAN gate is the
ADR gate only (MIXED shape), which is solid. The Z.ai sibling lane, credential-
blocked when this step first closed, is now live-proven end to end (see the Z.ai
lane section under Outcome above); see S15 for the zai profile and the harness
skip gate.
