---
tags:
  - '#plan'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
tier: L2
related:
  - '[[2026-07-17-kimi-provider-adr]]'
  - '[[2026-07-17-kimi-provider-research]]'
  - '[[2026-07-17-tool-cores-adr]]'
---

# `kimi-provider` plan

### Phase `P01` - Provider plumbing

Ground the seams, then land the Kimi provider enum, passthrough settings, factory dispatch on kimi acp with the backend discriminator and pinned CLI, and the readiness probe branch. Foundation for the rest.

Add Kimi (Moonshot AI) as a fourth provider lane on the native-ACP shape, executing the accepted
`2026-07-17-kimi-provider-adr` with full tool-cores conformance.

- [ ] `P01.S01` - Grounding and dedup gate - via vaultspec-rag semantically ground every seam this plan touches (provider enum, factory dispatch, config settings, ACP session meta sites, request_permission handler, compose_harness_mcp_servers, readiness probe, preset profiles) and confirm no Kimi lane already exists before any coding begins (executor-core); `src/vaultspec_a2a/`.
- [ ] `P01.S02` - Add Provider.KIMI to the provider enum with its MODEL_MAP and PROVIDER_DEFAULT_MODELS entries, additive and never renaming existing members (executor-core); `src/vaultspec_a2a/graph/enums.py`.
- [ ] `P01.S03` - Add passthrough Pydantic settings kimi_api_key as SecretStr, kimi_base_url, and kimi_model_name that inject into the subprocess as the CLI native KIMI_API_KEY, KIMI_BASE_URL, and KIMI_MODEL_NAME (executor-core); `src/vaultspec_a2a/control/config.py`.
- [ ] `P01.S04` - Add the factory KIMI dispatch branch that builds an AcpChatModel on the kimi acp command with the backend discriminator set to the kimi family and Kimi env injected (executor-core); `src/vaultspec_a2a/providers/factory.py`.
- [ ] `P01.S05` - Record the kimi-cli 1.49.0 pin as a named constant co-located with the factory binary-resolution code and surface it in the install hint mirroring the _classify_acp_command pattern, verifying the Git-Bash prerequisite and honoring KIMI_SHELL_PATH (executor-core); `src/vaultspec_a2a/providers/factory.py`.
- [ ] `P01.S06` - Add a probe_provider_readiness KIMI branch that verifies the kimi binary presence and never emits a secret, with unit coverage for the key-present and key-absent branches (executor-service); `src/vaultspec_a2a/providers/model_profiles.py`.

### Phase `P02` - ACP conditioning

Condition the Claude-only allowedTools meta behind the backend discriminator so Kimi omits it while the terminal-auth handshake stays unconditional, verified deterministically and against the real installed kimi acp.

- [ ] `P02.S07` - Gate the session-new meta.claudeCode.options.allowedTools emission to the claude family via the backend discriminator so the Kimi lane omits it (executor-core); `src/vaultspec_a2a/providers/_acp_session.py`.
- [ ] `P02.S08` - Keep the clientCapabilities meta.terminal-auth handshake unconditional and add a deterministic test that the claude and zai families keep the allowedTools meta while kimi omits it (executor-service); `src/vaultspec_a2a/providers/tests/`.
- [ ] `P02.S09` - Add a real-subprocess keyless handshake test that drives initialize against the installed kimi acp and asserts protocolVersion 1 and the terminal-auth meta family (executor-service); `src/vaultspec_a2a/providers/tests/`.

### Phase `P03` - Read-only permission layer

Enforce read-only discipline at the request_permission handler as an exact-name auto-approve set, isolate the per-run config from the ambient home, and prove harness composition rides the existing ACP branch through the real compose seam.

- [ ] `P03.S10` - Extend the on_request_permission handler to auto-approve exactly the composed read-tool names plus the enumerated Kimi native read tools in autonomous mode and reject every other request (executor-core); `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`.
- [ ] `P03.S11` - Keep supervised-mode prompting unchanged and add deterministic tests for both the autonomous auto-approve-exact branch and the reject-by-default branch (executor-service); `src/vaultspec_a2a/providers/tests/`.
- [ ] `P03.S12` - Launch kimi acp with a per-run config-file that excludes the ambient home config so ambient Kimi MCP is suppressed (executor-core); `src/vaultspec_a2a/providers/factory.py`.
- [ ] `P03.S13` - Verify Kimi harness composition rides the existing with_mcp_servers branch by testing through the real compose_harness_mcp_servers seam rather than a direct-field assertion (executor-service); `src/vaultspec_a2a/providers/tests/`.

### Phase `P04` - Team surface

Add the skip-loudly Kimi profile overlay and verify persona tool naming against Kimi native read tools.

- [ ] `P04.S14` - Add a team.profiles.kimi overlay to the live document-authoring preset that skips loudly when the key is absent, mirroring the zai profile precedent (executor-service); `src/vaultspec_a2a/team/presets/teams/vaultspec-adr-research.toml`.
- [ ] `P04.S15` - Verify the document personas name the composed rag tools and native read tools against Kimi native read tool names and add a lane note only if the wording requires it (executor-service); `src/vaultspec_a2a/team/presets/agents/vaultspec-researcher.toml`.

### Phase `P05` - Live proofs

Key-gated: arm the floor and semantic proofs on the Kimi lane to the established evidence standard, plus the shape-a fallback fidelity check only if the primary proof fails.

- [ ] `P05.S16` - Prove live on the Kimi lane that a document agent reads a named .vault ADR mid-turn and cites it, capturing run id and narration or frames with zero document writes, armed on KIMI_API_KEY arrival (executor-service); `src/vaultspec_a2a/service_tests/`.
- [ ] `P05.S17` - Prove live that a Kimi document agent invokes vaultspec-rag search mid-turn with citations resolving to real locations and port 8766 search corroboration, armed on KIMI_API_KEY arrival (executor-service); `src/vaultspec_a2a/service_tests/`.
- [ ] `P05.S18` - Run the shape-a fallback fidelity check of the Claude CLI against the Moonshot Anthropic-compat endpoint only if the primary Kimi proof fails, armed on KIMI_API_KEY arrival (executor-service); `src/vaultspec_a2a/service_tests/`.

### Phase `P06` - Close-out

Dead-code and dedup sweep, mandatory review gate, and plan-exec reconciliation.

- [ ] `P06.S19` - Sweep the codebase and vault via rag for dead or duplicate kimi-lane paths and reconcile any found (executor-service); `src/vaultspec_a2a/`.
- [ ] `P06.S20` - Run the mandatory code-review gate over all landed kimi-provider changes for safety and intent, which must return PASS before close-out (vaultspec-code-reviewer); `.vault/audit/`.
- [ ] `P06.S21` - Reconcile the plan and exec records against what actually landed, ensuring every Step has its exec record and the Verification criteria are honestly closed (executor-service); `.vault/exec/`.

## Description

This plan executes `2026-07-17-kimi-provider-adr`, grounded in `2026-07-17-kimi-provider-research`
and bound by the tool-cores read-only contract (`2026-07-17-tool-cores-adr`). The ADR chose shape
(b1): Kimi is an `AcpChatModel` variant pointed at `kimi acp`, honoring session-injected
`mcpServers` so its harness composition rides the EXISTING `with_mcp_servers` ACP branch with no
third dispatch branch and no isolated-config-home surfacing workaround. The Claude-only
`_meta.claudeCode.options.allowedTools` serialization is conditioned behind a single backend
discriminator, and read-only discipline is enforced at our `session/request_permission` handler as
an exact-name auto-approve set rather than blanket approval.

Binding working method (owner mandate): every coding Step begins with vaultspec-rag semantic
grounding and a dedup sweep against existing implementations before any edit. vaultspec-rag
semantic search leads all discovery; grep confirms exact symbols only. No coding task runs
ungrounded. Phase P01's first Step is the explicit grounding and dedup gate that grounds every seam
this plan touches; each later Step still leads with the same rag-first grounding per this method.

Phase sequencing honors the ADR: all non-key code and its deterministic verification land now (P01
provider plumbing, P02 ACP conditioning, P03 read-only permission layer, P04 team surface); only
the live proofs are key-gated. P05 arms the floor and semantic proofs and the shape-(a) fallback on
`KIMI_API_KEY` arrival, mirroring the Z.ai blocked-on-credentials-not-code posture. P06 closes out.
The masking-gap lesson from the Codex wiring defect is binding: wiring claims are proven through the
REAL compose seam, never a direct-field assertion.

## Steps

## Parallelization

P01 provider plumbing is the foundation and gates the rest. P02 (ACP conditioning) and P03
(read-only permission layer) both depend on P01's factory branch and backend discriminator but are
otherwise independent of each other and may proceed in parallel. P04 (team surface) depends only on
the enum and settings from P01. P05 live proofs are sequenced after P02, P03, and P04 land and are
additionally gated on `KIMI_API_KEY`; the shape-(a) fallback Step runs only if the primary Kimi
proof fails. P06 close-out is last: the review gate depends on all implementation and available
proofs having landed.

## Verification

The plan is complete when every Step is closed and the following hold. The non-key tier is verified
deterministically now: the factory resolves and dispatches the `kimi acp` lane with the backend
discriminator set, the `_meta.claudeCode.options.allowedTools` block is emitted for the claude
family and omitted for Kimi (asserted by test), the terminal-auth handshake stays unconditional and
is confirmed by a real keyless-subprocess handshake against the installed `kimi acp`, the
`session/request_permission` handler auto-approves exactly the composed read-tool names plus the
enumerated Kimi native read tools and rejects everything else in autonomous mode (both branches
tested), Kimi harness composition is proven to ride the existing `with_mcp_servers` branch through
the REAL compose seam, and the readiness probe covers the key-present and key-absent branches
without emitting a secret. The key-gated tier is verified per the established evidence standard: a
live run on the Kimi lane where a document agent reads a named `.vault` ADR mid-turn and cites it,
and a live run where it invokes vaultspec-rag search mid-turn with citations resolving and `:8766`
`/search` corroboration, both with a captured run id and narration or frames and zero document
writes. Read-only discipline is verified by confirming no write verb is composed and that Kimi's
native write and shell tools are rejected by the permission handler in autonomous mode. Honesty
limit: with no `KIMI_API_KEY` present, P05 stays armed and unclosed rather than reported as passing;
the shape-(a) fallback is exercised only if the primary proof fails, and any residual gap is
recorded as an explicit re-arm criterion.
