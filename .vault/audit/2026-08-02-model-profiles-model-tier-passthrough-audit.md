---
tags:
  - '#audit'
  - '#model-profiles'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:9903f75f57fe6bc5785fa93ba03e30376381a42fd46ed6402c229225d63324ce'
related:
  - "[[2026-08-02-model-profiles-plan]]"
---
# `model-profiles` audit: `Model tier passthrough review`

## Scope

Formal review of the accepted model-profile amendment, its ACP session-selection implementation, frozen concrete-model propagation, Kimi override removal, all-low served profiles, and live-provider proof. The reviewed surfaces cover ACP session negotiation, the chat-model lifecycle, factory construction, profile freezing, graph restart compilation, team presets, and service/provider tests.

## Findings

### claude-live-quota | low | Full Claude low-tier turn is externally quota-blocked

The production `AcpChatModel` path completed initialize, session creation, negotiated low-model selection, and reached `session/prompt`; the provider then returned its weekly-usage-limit error. The separate real ACP handshake completed selection without a prompt, and the real Z.ai low-tier streamed-turn passed. This is a provider-account availability boundary, not an implementation fallback or an unverified selected tier.

### claude-direct-cli | resolved | Direct authenticated Claude lane works independently

A direct `claude -p` invocation returned the requested minimal response with exit code zero. This confirms the local CLI authentication and direct service lane; it does not alter the separate ACP prompt error, whose payload specifically reports a weekly-limit condition after ACP selected the requested low model.

### obsolete-acp-model-rpc | resolved | Legacy selection transport removed

Review confirmed the obsolete `session/set_model` RPC, its request identifier, malformed generic configuration setter, and global Kimi setting have no remaining supported runtime surface. Claude and Z.ai now use the adapter-advertised configuration identifier and fail before prompting when it cannot select the requested model.

### frozen-concrete-name | resolved | Restart compilation now preserves the persisted model name

The compiler map retains `model_name`; restart passes that concrete value to the primary provider and rejects malformed frozen provider, capability, fallback, or model values rather than silently resolving a current default.

### service-test-tier-soft-edges | resolved | Cost-bearing service tests are fixed to low

The live tool-core and solo-coder harnesses now use the committed `fast` all-low profile with no shell override. The raw Codex web harness now sends `gpt-5.4-mini` in both `thread/start` and `turn/start`; a real low-tier retrieval turn passed.

### codex-web-harness-strict-typing | low | Pre-existing unknown-value errors remain

Focused `basedpyright` reports 19 `Unknown`-typing errors in the raw JSON observation and locator parsing code that pre-date the low-model change. The source is lint-clean, the model-profile/provider slice type-checks with zero diagnostics, and the low-tier live turn passed. This unrelated strictness debt remains queued for a dedicated typed-JSON remediation.

## Recommendations

- Re-run `test_claude_live_turn_completes_and_returns_content` after the documented Claude usage window resets; keep it `Model.LOW`.
- Keep the real no-prompt ACP selection test mandatory when updating `@agentclientprotocol/claude-agent-acp`, because it detects alias and protocol drift before a paid prompt.
- Retain all-low assignment guards for every new served live-provider profile.
- Remediate the raw Codex web-harness JSON typing under a focused audit item; do not suppress strict diagnostics.
