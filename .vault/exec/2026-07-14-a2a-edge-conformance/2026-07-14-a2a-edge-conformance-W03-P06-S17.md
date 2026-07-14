---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S17'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Write live mock-free integration tests against a loopback dashboard engine covering the envelope, denials, idempotent replay, and whole-document proposal shapes

## Scope

- `src/vaultspec_a2a/authoring/tests/`

## Description

Wrote live, mock-free integration tests that exercise the real client against the running dashboard engine on loopback, resolved through the discovery-file contract with a liveness check. The tests are service-marked and excluded from the default profile; when no engine is reachable they skip with a runbook pointer, an infrastructure gate rather than a masked code failure. Coverage: the catalog schema and its seven tools, actor-token minting returning a raw token, server-generated session creation, a whole-document create-document proposal landing as a draft with a changeset revision, submit capturing the minted proposal id into thread-state references, idempotent same-key replay returning the identical receipt, and an unknown actor token producing the typed inner 401.

- Created: `src/vaultspec_a2a/authoring/tests/test_live_engine.py`
- Modified: `src/vaultspec_a2a/authoring/session.py` (create-session fix)

## Outcome

Committed a10b8f6 (with the proposal-id follow-up in 5bfa362). Running against the real engine caught two genuine defects the source read alone missed: the session id is generated server-side (the payload carries only scope and title, and the id is read back from the receipt), and the proposal id is minted at submit rather than at create-proposal. Both were fixed. Six (later seven) service-marked live tests pass against the engine; the default profile deselects them and stays green. ruff, format, and ty all clean.

## Notes

The value of the live-test mandate was concrete here: two shape errors that read as correct in the Rust source were only exposed by issuing real requests. Live proposals were created against the dev engine, which is expected dev state for an integration proof.
