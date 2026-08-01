---
tags:
  - '#exec'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-30'
body_hash: 'sha256:900be974e1c0c777fc2db0d7c53118d63139054d93aa49ba845d18736278ab3a'
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

Re-arm on credential arrival. A missing external prerequisite now means one thing repository-wide, held in the root conftest: the rule skips with the canonical runbook reason, or fails when the caller guaranteed the resource with `--require-prerequisite`. This proof consults that rule for the loopback-stack id alone. The registry carries a kimi-cli PATH prerequisite and a Z.ai credential entry but no Kimi-credential entry, so an absent `KIMI_API_KEY` is not expressed through the canonical rule; it surfaces at run-start provider eligibility instead, and whether that yields a truthful skip or a hard failure on this lane is not asserted in the code as read - treat it as unconfirmed until observed.

Boot the loopback engine, gateway, and worker directly, export the engine service-json path, and confirm the gateway health endpoint answers 200; discovery reads that env var, so nothing here is harness-provisioned. The runtime-directory and worker-bearer corrections landed against the containerized stack helper, not this path: the floor proofs reach the stack through the reachable-stack accessor and the acceptance harness, and never construct the containerized helper.

Run with the all-Kimi profile selected: `$env:S05_PROFILE="kimi-all"; pytest -m service -k reads_named_adr --require-prerequisite loopback-stack`, the declaration turning an absent stack into a failure rather than a quiet skip. Capture the run id, the `message_chunk` citation plus one prompt-absent interior token, and the empty document-directory write-delta. Do not flip the checkbox until the run is green. Shares the key gate with `P05.S17`/`S18`.
