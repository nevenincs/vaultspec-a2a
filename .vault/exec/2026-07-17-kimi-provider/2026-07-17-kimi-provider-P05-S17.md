---
tags:
  - '#exec'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
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

Re-arm (on `KIMI_API_KEY` arrival): same stack as `P05.S16` plus the rag pre-flight - restore `:8766` discovery and index the engine-scoped workspace (`uvx vaultspec-rag index --port 8766`, attach); run `pytest -m service -k invokes_rag_search` with the Kimi profile; capture the run id, the agent's `mcp__vaultspec-rag__search_*` invocation, resolving citations, the rag daemon `:8766 /search` corroboration in the run window, and the empty document-dir write-delta. Do not flip until green. Shares the key gate + stack with `P05.S16`.
