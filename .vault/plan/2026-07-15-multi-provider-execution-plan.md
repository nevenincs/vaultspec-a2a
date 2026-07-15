---
tags:
  - '#plan'
  - '#multi-provider-execution'
date: '2026-07-15'
modified: '2026-07-15'
tier: L2
related:
  - '[[2026-07-15-multi-provider-execution-adr]]'
  - '[[2026-07-15-multi-provider-execution-research]]'
  - '[[2026-07-15-multi-provider-execution-reference]]'
---

# `multi-provider-execution` plan

**SKELETON — NOT APPROVED.** Drafted against `[[2026-07-15-multi-provider-execution-adr]]` (status `proposed`) for shape only; execution must not start until the owner ratifies the ADR and approves this plan.

## Proposed Changes

Adds two provider integrations (Z.ai routed through the existing Claude ACP path; Codex via a new non-ACP `BaseChatModel`) and proves per-role mixed-provider execution inside the `research_adr` topology, per `[[2026-07-15-multi-provider-execution-adr]]`. Grounded in `[[2026-07-15-multi-provider-execution-research]]` and `[[2026-07-15-multi-provider-execution-reference]]`; extends `[[2026-07-15-model-profiles-adr]]`'s precedence chain without modifying it.

## Tasks

- `Phase 1` — Z.ai provider (config-variant of the existing Claude ACP path)
  1. Add `Provider.ZAI` to `graph/enums.py` with `MODEL_MAP`/`PROVIDER_DEFAULT_MODELS` entries.
  1. Add `zai_base_url`/`zai_auth_token`-style settings to `control/config.py`.
  1. Add `_build_zai_env` to `providers/factory.py` and a dispatch branch mirroring the Claude ACP branch.
  1. Add a `Provider.ZAI` branch to `probe_provider_readiness` (`providers/model_profiles.py`).
  1. Live-probe the real Z.ai endpoint for Anthropic Messages API fidelity (tool-calling, streaming) before marking any profile eligible — closes the ADR's Z.ai fidelity constraint.

- `Phase 2` — Codex provider (new non-ACP subprocess chat model)
  1. Resolve Codex's non-interactive/headless auth model against the real CLI (closes the ADR's auth-model constraint) before designing settings fields.
  1. Add `Provider.CODEX` to `graph/enums.py` with model-map entries.
  1. Implement `CodexChatModel(BaseChatModel)` driving `codex app-server`'s JSON-RPC surface, reusing `_subprocess.py` process-lifecycle helpers, following the `mock_chat_model.py` non-ACP precedent.
  1. Add a `classify_codex_command`-style readiness check and a `Provider.CODEX` branch in `probe_provider_readiness`.
  1. Add a `factory.py` dispatch branch.

- `Phase 3` — Per-role mixed-provider proof
  1. Author or extend a team profile assigning distinct providers per role (researcher=codex, synthesist=claude, adr-author=zai) on the `vaultspec-adr-research` preset.
  1. Run a live research_adr run under the mixed-provider profile end to end; verify per-role attribution and document quality hold across providers.
  1. Verify the a2a-edge discovery/eligibility responses correctly surface the new providers with safe reasons on failure (no secrets).

- `Phase 4` — Cross-repo verification (no code changes assumed)
  1. Check whether the dashboard/engine's own schema treats `provider` as an open string or a closed enum; if closed, file the required cross-repo contract event with the dashboard team rather than proceeding — does not resolve unilaterally from this repo.
  1. Document the outcome in a phase summary; do not mark this plan's cross-repo concern closed without that confirmation.

## Parallelization

Phase 1 (Z.ai) and Phase 2 (Codex) are independent and can run in parallel — neither touches the other's files (`factory.py` dispatch branches are additive, not overlapping edits, but should still land as separate reviewed changes to avoid merge friction on the same file). Phase 3 depends on both. Phase 4 can start in parallel with Phase 1/2 (it's a read-only cross-repo check) but its outcome gates declaring the feature cross-repo-complete.

## Verification

Not yet defined — to be elaborated once the ADR is ratified and phase scope is locked. At minimum: live probes (not mocks) against the real Z.ai endpoint and the real Codex CLI per the ADR's constraints; a live mixed-provider research_adr run producing real dashboard-visible proposals under Phase 3; explicit confirmation (not assumption) of the dashboard-side schema question from Phase 4 before declaring cross-repo completeness.
