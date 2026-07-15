---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S10'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
---

# Execute the PW7 headless acceptance contract as its first run, building the driver as the STANDING harness

## Scope

- `src/vaultspec_a2a/service_tests/`

## Description

This record captures the resumption state for P04.S10 as of the 2026-07-15 resumability audit. The step itself is NOT complete — this is a status capture, not a completion record, per the owner's instruction not to upgrade the checkbox. No implementation work was performed to produce this record; it exists to stop cold-resume dependence on a prior session's chat history.

Three-way evidence split, verified source by source rather than taken on report:

1. **Durable artifact (materialization proof).** A probe research document exists on disk at `Y:/code/vaultspec-dashboard-worktrees/main/.vault/research/2026-07-15-p04s10-probe-research.md` — confirmed present by direct filesystem check from this worktree. Its existence is the materialization-coordinates evidence: an apply receipt produced a real `document_path`, and the file is there. This is durable, external evidence (lives in the dashboard repo's worktree, not this repo), and it is the one claim in the original report this audit could independently corroborate on disk.

2. **Documented deferral (rollback-refusal reasoning).** The claim that a rollback of an applied `CreateDocument` changeset is refused as a clean value, because `CreateDocument` has no v1 inverse operation, is a design deferral rather than a probe result. This audit did not find that exact reasoning spelled out verbatim in the committed ADR or triage docs; the closest independently-verifiable corroboration is `2026-07-14-a2a-edge-conformance-engine-wire-shapes-reference` (lines ~104, ~483-489), which lists `/v1/rollback-proposals` as a real wire endpoint but explicitly scopes it as NOT covered field-by-field — "unverified struct... must be read in the Rust source before coding against them." That is consistent with (but does not itself state) the no-inverse-for-create reasoning team-lead described. Treat the specific "refused as a clean value" mechanism as UNVERIFIED against engine source until someone reads `rollback-proposals`' actual Rust handler.

3. **Session-only claim (MUST RE-DERIVE).** The "station-flow" sequence — submit → review station → system-actor AUTO approve → apply → materialize — was reportedly observed live in a stopped executor's session. No committed vault record, test file, or other artifact substantiates this sequence beyond the one committed code fix (`06f9151`, keying the submitter's role-token lookup by worker `agent_id`). This audit does not certify the station-flow sequence occurred as described; the only way to make it PROVEN is to build the P04.S10 standing harness and re-run it, which is the step's own remaining work.

## Outcome

Not complete. No code changed by this record. The plan checkbox for P04.S10 stays unchecked — this record exists so the next executor (or a cold resume) inherits an honest evidence inventory instead of an unqualified "proven" claim.

## Notes

Next step for whoever picks this up: build the standing acceptance harness itself (parameterized live pytest driver under `src/vaultspec_a2a/service_tests/`, per the plan row's own action text) and let its live run re-derive claim 3 from scratch. Do not treat this record's claim 1 or claim 2 as a substitute for running the harness — they corroborate parts of the picture, not the whole acceptance contract.

**Harness build progress (2026-07-15, executor-opus-6, two clean increments landed on main, isolated worktrees + real hooks):**

- `4a66cb2` — `Provider.DETERMINISTIC` enum member + `MODEL_MAP`/default entries, `DeterministicResearchAdrChatModel(BaseChatModel)` (in-process, role-keyed deterministic content: researcher→findings, synthesist→valid research doc, adr-author→valid ADR doc, doc-reviewer→"PASS", feature_tag/topic parameterized), a factory dispatch branch, and a 9-test unit suite. This is the Option A provider mechanism itself.
- `49772bc` — `vaultspec-adr-research-deterministic.toml`, opus-6's own driver preset: `provider = "deterministic"` on team defaults and all four workers, same real `vaultspec-*` agent_ids as `vaultspec-adr-research`. Verified loading via `load_team_config` and `resolve_effective_assignment` resolving all four roles to `deterministic`.

**Known unreconciled naming gap (recorded explicitly, not papered over):** the parallel session (same P04.S10 mandate, see the TWO WORKSTREAMS CONVERGING note on the plan row) is separately building an uncommitted `vaultspec-adr-research-mock.toml` preset with `provider = "mock"` — the EXISTING `Provider.MOCK`/VidaiMock-HTTP-proxy path, not an in-process model. That preset's own description text claims "in-process deterministic" behavior it does not yet have. The two Option A devices (opus-6's `Provider.DETERMINISTIC` + own preset vs. the parallel session's `provider="mock"` preset) are deliberately NOT reconciled yet; per team-lead's ruling, whichever committed state lands last on this specific point wins, and the reconciliation call (repoint one preset at the other's provider, or keep both) is architect-2's to make once both plainly exist — tracked as the reconciliation checkpoint on the plan row.

Remaining harness work (the large piece, in progress): the standing parameterized `service_tests/` driver itself, the HUMAN/AUTO/MIXED lane matrix, and the materialization assertions grounded in the real engine's `ApplyChildReceipt` shape (read from the dashboard repo's Rust source per the hard prerequisite, not assumed from prose).
