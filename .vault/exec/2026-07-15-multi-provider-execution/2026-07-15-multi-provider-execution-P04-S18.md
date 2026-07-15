---
tags:
  - '#exec'
  - '#multi-provider-execution'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S18'
related:
  - "[[2026-07-15-multi-provider-execution-plan]]"
---

# Check whether the dashboard/engine's own schema treats provider as an open string or a closed enum

## Scope

- `cross-repo (dashboard/engine, no A2A code change assumed)`

## Description

Read-only audit of the dashboard repo (`Y:/code/vaultspec-dashboard-worktrees/main`, engine = Rust, frontend = TS) to answer the ADR's open cross-repo question: does the dashboard/engine treat the provider identifier as an open string or a closed enum anywhere on the run-start to run-status to review path.

- Swept the Rust engine and the TS frontend case-insensitively for `provider`. Every frontend hit is a React context component (`QueryClientProvider`, `LocalizationProvider`, `I18nextProvider`) or a localization lint rule, none an LLM-provider field.
- Inspected the authoring ingestion contract, the exact pipeline a2a agents post into. The proposal request structs `DraftProposalRequest`, `ValidateProposalRequest`, `SubmitProposalRequest`, and `TerminalProposalRequest` in `engine/crates/vaultspec-api/src/authoring/proposal/mod.rs` are all `#[serde(deny_unknown_fields)]` and carry only `changeset_id`, `expected_revision`, `summary`, `operations`, `current_revisions`, `chunk_evidence`, `validation_digest` — no `provider` field.
- Confirmed the authoring event, review, session, and projection modules contain zero `provider` references; `deny_unknown_fields` is applied across 34 authoring modules.
- Located the ONLY `provider` in the engine: the CLI provisioning scaffolder in `engine/crates/vaultspec-cli/src/main.rs` (`provider: String` at line 130, and `provision.rs` `Option<String>`), an open string whose documented value list is already `all|core|claude|gemini|antigravity|codex`.
- Searched `docs/`, and all `.json`/`.yaml`/`.toml` under `docs`/`engine` for a shared provider schema/contract: none exists.

## Outcome

CLOSED — no dashboard-side change required, no cross-repo contract event needed. The dashboard/engine does NOT model, validate, or closed-enum the provider identifier anywhere on the run-start to run-status to review / authoring pipeline. The only provider value it names anywhere is an OPEN `String` in the CLI scaffolder, which already includes `codex` and would accept `zai` verbatim. Therefore a2a can report `provider=zai` / `provider=codex` on its edge without any dashboard-side enum update. The ADR's flagged cross-repo openness question resolves to: provider is open (in fact absent) on the dashboard side.

## Notes

One a2a-side invariant to preserve, NOT a dashboard change: because the engine's authoring proposal ingestion is `deny_unknown_fields` with no `provider` field, a2a must never inject a `provider` key into those engine-bound authoring payloads — the engine would reject the whole request (any value, not just zai/codex). This is already the case today (existing claude runs succeed), so provider staying an a2a-internal / edge-served concept keeps the contract green. The dashboard has no provider-eligibility picker consuming a2a's edge yet; if one is built later it should type provider as an open string — a future dashboard concern, not a blocker now.
