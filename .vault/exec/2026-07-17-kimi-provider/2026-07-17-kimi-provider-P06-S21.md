---
tags:
  - '#exec'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S21'
related:
  - "[[2026-07-17-kimi-provider-plan]]"
---

# Reconcile the plan and exec records against what actually landed, ensuring every Step has its exec record and the Verification criteria are honestly closed (executor-service)

## Scope

- `.vault/exec/`

## Description

- Reconcile the kimi-provider plan and exec records against what actually landed: verify every closed step has a canonical exec record and every open step records an honest re-arm; record the dispatch deviations and the ADR correction chain; and check the plan Verification criteria against reality.

## Outcome

### Step / exec-record reconciliation

All 21 steps now have a canonical exec record under `.vault/exec/2026-07-17-kimi-provider/` (`...-P0N-SNN.md`). Fifteen were already present with records (`P01.S01-S06`, `P02.S07-S09`, `P03.S10-S13`, `P04.S14-S15`). Five exec-record gaps were closed during this pass via `vault add exec`: `P06.S19` (deliverable the dedup audit `2026-07-17-kimi-provider-dedup-audit`) and `P06.S20` (deliverable the review audit `2026-07-17-kimi-provider-audit`, STATUS PASS, landed `d5694ad`), which had produced audits but no exec-dir record; and `P05.S16`/`S17`/`S18`, which are armed re-arm records. Three steps remain OPEN BY DESIGN pending `KIMI_API_KEY`: `P05.S16` (Kimi floor) and `P05.S17` (Kimi semantic) are armed to the established evidence standard, and `P05.S18` is the doubly-conditional shape-(a) fallback (runs only if the primary proof fails). This step, `P06.S21`, completes when this reconciliation lands even though those three rows stay open.

### Dispatch deviations (process history, none material)

1. Stacked-branch build point: P04 (team surface) was executed by executor-service on branch `kimi-provider-team` built FROM a mid-`kimi-provider-core` head (`8d4d137`), by design - the ADR notes P04 depends only on the P01 enum/settings, so the stacked branch could proceed before the rest of core landed; land order stayed core-first, then team.
2. Kimi native-read-tool enumeration divergence, caught and fixed pre-review: the P04.S15 persona verdict relayed Kimi's read tools as `ReadFile`/`Grep`/`Glob` (source-verified) to executor-core's P03.S10 exact-name auto-approve set; the enumeration (including the `ReadMediaFile` media-read variant alongside `ReadFile`) was reconciled in P03 before the S20 review gate, so the persona verdict and the permission-RPC allowlist do not diverge.

### ADR correction chain (decision-neutral)

The ADR/research referenced `KIMI_SHELL_PATH` as the Git-Bash override env var; the installed-source-verified name is `KIMI_CLI_GIT_BASH_PATH`. This is a decision-neutral naming correction (the Git-Bash prerequisite and its honored-override design are unchanged); the correct name is used in the readiness-probe and the P05 re-arm records.

### Plan Verification criteria vs reality

- Non-key tier: VERIFIED DETERMINISTICALLY. Factory resolves and dispatches the `kimi acp` lane with the backend discriminator set; the `_meta.claudeCode.options.allowedTools` block is emitted for the claude family and omitted for Kimi (tested); the terminal-auth handshake stays unconditional and is confirmed by a REAL keyless-subprocess handshake against the installed `kimi acp` (`protocolVersion 1`, terminal-auth `_meta` family); the `session/request_permission` handler auto-approves exactly the composed read tools plus Kimi's native read tools and rejects everything else in autonomous mode (both branches tested); Kimi harness composition rides the existing `with_mcp_servers` branch through the REAL compose seam; the readiness probe covers key-present and key-absent without emitting a secret. The deterministic suites (421 + 138 across the touched provider and team layers) are green.
- Key-gated tier: ARMED, NOT RUN. The live floor (`P05.S16`) and semantic (`P05.S17`) proofs - and the conditional shape-(a) fallback (`P05.S18`) - are gated on `KIMI_API_KEY` and stay armed-and-unclosed rather than reported as passing, per the plan's honesty limit and the Z.ai blocked-on-credentials-not-code posture.
- Read-only discipline: ENFORCED and AUDITED. No write verb is composed, and Kimi's native write/shell tools are rejected by the permission handler in autonomous mode (the exact-name auto-approve set, never blanket `--yolo`); the `P06.S20` review PASS confirms it.
- Close-out: reviewer PASS obtained (`P06.S20`); this record is the reconciled-exec-record-for-every-step criterion.

## Notes

Reconciliation authored directly in main (markdown-only; vault single-writer). Main carried a parallel session's WIP (`api/routes/gateway.py`, `api/schemas/gateway.py`, `cli/main.py`, `cli/tests/test_cli_live.py`, `control/worker_management.py`, `worker/app.py`, an unrelated `adr-authoring-orchestration-plan.md`, and untracked files) which was NOT staged; only the six exec records this pass created (`P05.S16-S18`, `P06.S19-S21`) and the regenerated feature index were touched. The `P06.S21` checkbox is left UNFLIPPED for the team lead to close after this record lands. `P05.S16`, `P05.S17`, and `P05.S18` remain open by design pending `KIMI_API_KEY` and are not counted as gaps - their exec records carry the exact re-arm recipes.
