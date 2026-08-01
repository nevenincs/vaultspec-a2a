---
tags:
  - '#exec'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-30'
body_hash: 'sha256:8209cedb0164c9782b9d4806a739f13465600cc868e7029533514644df6ec43d'
step_id: 'S17'
related:
  - "[[2026-07-17-kimi-provider-plan]]"
---

# Prove live that a Kimi document agent invokes vaultspec-rag search mid-turn with citations resolving to real locations and port 8766 search corroboration, armed on KIMI_API_KEY arrival (executor-service)

## Scope

- `src/vaultspec_a2a/service_tests/`

## Description

- Arm the Kimi-lane semantic proof: a document agent invokes vaultspec-rag search mid-turn, citations resolve to real locations, `:8766` `/search` corroboration, zero document writes.

## Outcome

ARMED, not run - OPEN BY DESIGN pending `KIMI_API_KEY`. Reuses the tool-cores harness `test_document_agent_invokes_rag_search_midturn_and_cites` (`service_tests/test_tool_cores_floor_live.py`), profile-selected - no new driver. The Kimi lane is decisively favorable for this proof: the probe (`2026-07-17-kimi-provider-research` amendment) established that `kimi acp` HONORS session-injected `mcpServers` (no Claude registration-scope gate), so the composed vaultspec-rag server rides the existing `with_mcp_servers` branch (verified through the real compose seam in P03.S13), and the read-only auto-approve set (P03.S10) admits exactly the composed rag read tools plus Kimi's native `ReadFile`/`Grep`/`Glob`. All of that is deterministically landed; only the live model turn is key-gated.

## Notes

Re-arm as for the floor proof - same canonical prerequisite rule, same manually booted loopback stack, same `S05_PROFILE="kimi-all"` selection - with `-k invokes_rag_search`.

The credential alone does NOT arm this one: it additionally needs a live grounding daemon on port 8766 with the engine-scoped workspace indexed, and that daemon is a second external dependency with no entry in the prerequisite registry, so its absence is not covered by the canonical skip rule either. Confirm the daemon answers before running.

Capture the run id, the agent's grounding-search invocation, citations resolving to real locations, daemon-side search corroboration inside the run window, and the empty write-delta. Do not flip the checkbox until the run is green.
