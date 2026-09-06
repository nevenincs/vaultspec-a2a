---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:cc401318b721f744f9037c0ac36c4563bfb059880a584b158c861f70e6772cad'
step_id: 'S38'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Execute negotiated native commands with validated arguments, busy disposition and observable outcomes

## Scope

- `src/vaultspec_a2a/providers/_acp_types.py`
- `src/vaultspec_a2a/providers/acp_chat_model.py`
- `src/vaultspec_a2a/providers/tests/test_acp_native_commands.py`

## Changes

- Added explicit completed, busy, blocked, unsupported, cancelled, and failed outcomes with effect uncertainty.
- Bound each command to the exact advertisement from the session that executes it.
- Added a bounded advertisement wait and refusal before prompting when support is absent.
- Serialized provider-session ownership and returned busy for concurrent command use.
- Validated exact names and bounded printable arguments before provider spawn.
- Executed commands through negotiated ACP prompt syntax without a shell or arbitrary RPC escape.
- Kept native compaction effects and consumer exposure unclaimed.

## Verification

- `.venv/Scripts/python.exe -m vaultspec_a2a.testing.runner --run-timeout 60 --exit-timeout 5 -- -q src/vaultspec_a2a/providers/tests/test_acp_native_commands.py` -> eight passed in 8.83 seconds, natural exit 0.
- `uv run ruff check src/vaultspec_a2a/providers/_acp_types.py src/vaultspec_a2a/providers/acp_chat_model.py src/vaultspec_a2a/providers/tests/test_acp_native_commands.py` -> pass.
- `uv run ty check src/vaultspec_a2a/providers/_acp_types.py src/vaultspec_a2a/providers/acp_chat_model.py src/vaultspec_a2a/providers/tests/test_acp_native_commands.py` -> pass.

## Open dependencies

- W04.P09.S42 and W04.P09.S45 own Dashboard/broker exposure and compaction state semantics.
- W05 qualification owns evidence that a provider command produced its claimed external effect.
- No compaction capability claim is enabled by this step.
