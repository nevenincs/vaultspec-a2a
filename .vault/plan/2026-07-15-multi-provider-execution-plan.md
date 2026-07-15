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

### Phase `P01` - Z.ai provider

Land Z.ai as a config variant of the existing Claude ACP path: new provider enum member, env-injection helper, factory dispatch branch, readiness probe, and a live fidelity probe against the real endpoint that closes the ADR's Z.ai-fidelity constraint.

**APPROVED for execution** (2026-07-15, interactive owner decision) against `2026-07-15-multi-provider-execution-adr` (status `accepted`). Phase 1 (Z.ai) and Phase 2 (Codex) are authorized to run in parallel; Phase 3 rides the standing acceptance harness (PW7) once the adr-authoring-orchestration P04.S10 finale harness lands.

- [x] `P01.S01` - Add Provider.ZAI to the Provider enum with MODEL_MAP and PROVIDER_DEFAULT_MODELS entries; `src/vaultspec_a2a/graph/enums.py`.
- [x] `P01.S02` - Add zai_base_url/zai_auth_token settings fields and validate they never leak into logs; `src/vaultspec_a2a/control/config.py`.
- [x] `P01.S03` - Add _build_zai_env mirroring _build_gemini_env and a factory dispatch branch mirroring the Claude ACP branch, reusing AcpChatModel unchanged; `src/vaultspec_a2a/providers/factory.py`.
- [x] `P01.S04` - Confirm workspace/environment.py's scrub list does not strip ANTHROPIC_BASE_URL or ANTHROPIC_AUTH_TOKEN, and add a regression test pinning that; `src/vaultspec_a2a/workspace/environment.py, src/vaultspec_a2a/workspace/tests/`.
- [x] `P01.S05` - Add a Provider.ZAI branch to probe_provider_readiness and classify_provider_command, never emitting a secret; `src/vaultspec_a2a/providers/model_profiles.py, src/vaultspec_a2a/providers/factory.py`.
- [ ] `P01.S06` - Live-probe the real Z.ai endpoint for Anthropic Messages API fidelity (tool-calling schema, streaming chunk shape) through claude-agent-acp before marking any profile eligible. PARKED blocked-on-credentials: probe written (2 service-marked tests, deselected by default), lint/type clean, no Z.ai token in env. Evidence: step record P01-S06. Re-arm one command: ZAI_AUTH_TOKEN=<token> uv run --no-sync pytest -m service src/vaultspec_a2a/providers/tests/test_zai_fidelity.py (override gateway with ZAI_BASE_URL) — on green, set record Outcome PASS and check this row, since no profile may mark Z.ai eligible until then; `src/vaultspec_a2a/providers/tests/test_zai_fidelity.py, src/vaultspec_a2a/service_tests/`.
- [x] `P01.S07` - Unit and live-probe tests for the Z.ai env-injection path, readiness branch, and factory dispatch; `src/vaultspec_a2a/providers/tests/test_factory.py, src/vaultspec_a2a/providers/tests/test_model_profiles.py`.

### Phase `P02` - Codex provider

Land Codex as a new non-ACP subprocess chat model: resolve its headless auth model, implement the JSON-RPC app-server driver, wire readiness and factory dispatch.

- [ ] `P02.S08` - Resolve Codex's non-interactive/headless authentication model against the real Codex CLI (API key vs. ChatGPT-session vs. local device auth) — this closes the ADR's flagged Codex auth-model unknown before any settings field is designed; `src/vaultspec_a2a/control/config.py`.
- [ ] `P02.S09` - Add Provider.CODEX to the Provider enum with model-map entries; `src/vaultspec_a2a/graph/enums.py`.
- [ ] `P02.S10` - Implement CodexChatModel(BaseChatModel) driving codex app-server's JSON-RPC-over-stdio surface directly, following the mock_chat_model.py non-ACP precedent; `src/vaultspec_a2a/providers/codex_chat_model.py`.
- [ ] `P02.S11` - Reuse _subprocess.py's protocol-agnostic process lifecycle helpers (spawn/kill-tree) for Codex subprocess management; `src/vaultspec_a2a/providers/_subprocess.py, src/vaultspec_a2a/providers/codex_chat_model.py`.
- [ ] `P02.S12` - Add a classify_codex_command-style readiness check and a Provider.CODEX branch in probe_provider_readiness, never emitting a secret; `src/vaultspec_a2a/providers/factory.py, src/vaultspec_a2a/providers/model_profiles.py`.
- [ ] `P02.S13` - Add a factory.py dispatch branch for Provider.CODEX; `src/vaultspec_a2a/providers/factory.py`.
- [ ] `P02.S14` - Unit tests for CodexChatModel's JSON-RPC framing and subprocess lifecycle, plus a live probe against the real codex app-server once the auth model is resolved; `src/vaultspec_a2a/providers/tests/test_codex_chat_model.py, src/vaultspec_a2a/service_tests/`.

### Phase `P03` - Per-role mixed-provider proof

Prove researcher=codex, synthesist=claude, adr-author=zai end to end on the vaultspec-adr-research preset, riding the standing acceptance harness (PW7) once the adr-authoring-orchestration P04.S10 finale harness lands.

- [ ] `P03.S15` - Author or extend a team profile assigning distinct providers per role (researcher=codex, synthesist=claude, adr-author=zai) on the vaultspec-adr-research preset; `src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research.toml`.
- [ ] `P03.S16` - Run a live research_adr run under the mixed-provider profile end to end riding the standing acceptance harness (PW7) once the adr-authoring-orchestration P04.S10 finale harness lands, verifying per-role attribution and document quality hold across providers; `src/vaultspec_a2a/service_tests/`.
- [ ] `P03.S17` - Verify the a2a-edge discovery/eligibility responses correctly surface the new providers with safe reasons on failure and no secrets; `src/vaultspec_a2a/api/tests/`.

### Phase `P04` - Cross-repo verification

Check whether the dashboard/engine's own schema treats provider as an open string or a closed enum; file the required cross-repo contract event rather than assuming compatibility.

- [ ] `P04.S18` - Check whether the dashboard/engine's own schema treats provider as an open string or a closed enum — if closed, file the required cross-repo contract event with the dashboard team rather than proceeding unilaterally; `cross-repo (dashboard/engine, no A2A code change assumed)`.
- [ ] `P04.S19` - Document the outcome in a phase summary — do not mark this plan's cross-repo concern closed without that confirmation; `.vault/exec/2026-07-15-multi-provider-execution/`.

## Proposed Changes

Adds two provider integrations (Z.ai routed through the existing Claude ACP path; Codex via a new non-ACP `BaseChatModel`) and proves per-role mixed-provider execution inside the `research_adr` topology, per `2026-07-15-multi-provider-execution-adr`. Grounded in `2026-07-15-multi-provider-execution-research` and `2026-07-15-multi-provider-execution-reference`; extends `2026-07-15-model-profiles-adr`'s precedence chain without modifying it.

## Description

**Resumability state (2026-07-15 audit, updated live):** Executor-of-record P01 (Z.ai): executor-opus-5. Executor-of-record P02 (Codex): executor-opus-6. Both dispatched in parallel 2026-07-15 per owner approval; current frontier is uncommitted in-flight work on `src/vaultspec_a2a/control/config.py`, `graph/enums.py`, `providers/factory.py`, `providers/model_profiles.py`, `providers/codex_chat_model.py` (new), and both providers' test files. See `2026-07-15-multi-provider-execution-adr` Constraints for the current resolution state of each phase's flagged unknown (Codex auth: resolved; Z.ai fidelity: still open, blocked on credentials). No exec Step Records exist yet for P01/P02 — a cold resume should read the uncommitted diff (`git diff` against this commit) or, once committed, the Step Records under `.vault/exec/2026-07-15-multi-provider-execution/`. P03 depends on the adr-authoring-orchestration P04.S10 acceptance harness landing first (not yet built as of this audit).

**Tracked hardening follow-up (out of P01/P02 scope):** `AcpChatModel.env_vars` has no repr redaction — the Z.ai auth token and Claude's OAuth token both sit in that plain dict unredacted. Residual risk is scoped to a direct `repr(model)` call, not present in any current code path. Cross-cutting across every ACP-path provider; not picked up by this plan.

## Steps

## Parallelization

Phase 1 (Z.ai) and Phase 2 (Codex) are independent and run in parallel — neither touches the other's files in a conflicting way (`factory.py` dispatch branches are additive, not overlapping edits, but should still land as separate reviewed changes to avoid merge friction on the same file). Phase 3 depends on both. Phase 4 can start in parallel with Phase 1/2 (it's a read-only cross-repo check) but its outcome gates declaring the feature cross-repo-complete.

## Verification

Live probes (not mocks) against the real Z.ai endpoint and the real Codex CLI per the ADR's constraints; a live mixed-provider research_adr run producing real dashboard-visible proposals under Phase 3, riding the standing acceptance harness (PW7) once the adr-authoring-orchestration P04.S10 finale harness lands; explicit confirmation (not assumption) of the dashboard-side schema question from Phase 4 before declaring cross-repo completeness.
