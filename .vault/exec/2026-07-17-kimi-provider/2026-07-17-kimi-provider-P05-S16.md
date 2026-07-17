---
tags:
  - '#exec'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S16'
related:
  - "[[2026-07-17-kimi-provider-plan]]"
---

# Prove live on the Kimi lane that a document agent reads a named .vault ADR mid-turn and cites it, capturing run id and narration or frames with zero document writes, armed on KIMI_API_KEY arrival (executor-service)

## Scope

- `src/vaultspec_a2a/service_tests/`

## Description

- Arm the Kimi-lane floor proof: a document agent reads a named `.vault` ADR mid-turn and cites it, zero document writes, to the established evidence standard.

## Outcome

ARMED, not run - OPEN BY DESIGN pending `KIMI_API_KEY`. The Kimi lane is an `AcpChatModel` variant (shape b1), so the floor proof reuses the tool-cores harness `test_document_agent_reads_named_adr_midturn_and_cites` (`service_tests/test_tool_cores_floor_live.py`), profile-selected - no new driver, exactly the Z.ai/Codex pattern. All non-key work is deterministically verified (P01-P04 landed): factory dispatch, env injection, the per-run config-file isolation, the permission-RPC exact-name auto-approve set, and the `[team.profiles.kimi]` overlay. The floor path needs no key beyond the live model turn itself; with no key present it stays armed rather than reported as passing (the ADR's blocked-on-credentials-not-code posture).

## Notes

Re-arm (on `KIMI_API_KEY` arrival): inject `KIMI_API_KEY` (+ optional `KIMI_BASE_URL`/`KIMI_MODEL_NAME`) into the gateway env; add a temporary all-Kimi profile (all four roles on `kimi`, so no role gates on another provider) or select the `[team.profiles.kimi]` overlay with a Kimi doc-reviewer; boot the engine (scoped to an indexed workspace with a real ADR) + gateway per the tool-cores S05/S17 recipe (Git-Bash prerequisite honored via `KIMI_CLI_GIT_BASH_PATH`); run `pytest -m service -k reads_named_adr` with the Kimi profile; capture the run id, the `message_chunk` citation + a distinctive prompt-absent interior token, and the empty document-dir write-delta. Do not flip the checkbox until the run is green. Shares the key gate with `P05.S17`/`S18`.
