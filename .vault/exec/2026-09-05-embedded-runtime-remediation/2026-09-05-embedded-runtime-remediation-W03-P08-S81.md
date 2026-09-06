---
tags:
  - '#exec'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:3f21a02d9e7ea028ce1c522cd743ae648d9ba5dbe271a13427aa1f769c726865'
step_id: 'S81'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# Implement the admitted Codex app-server lane's native-control mapping against its verified protocol and session identity, with explicit absent-control refusal, bounded outcomes and no arbitrary RPC escape; keep new claims blocked until effect proof

## Scope

- `src/vaultspec_a2a/providers/codex_chat_model.py`

## Changes

- `M` `src/vaultspec_a2a/providers/codex_chat_model.py`
- `M` `src/vaultspec_a2a/providers/tests/test_codex_chat_model.py`
- `verify:` `.venv/Scripts/python.exe -m vaultspec_a2a.testing.runner --run-timeout 90 --exit-timeout 5 -- src/vaultspec_a2a/providers/tests/test_codex_chat_model.py -q` -> `pass`
- `verify:` `.venv/Scripts/python.exe -m vaultspec_a2a.testing.runner --run-timeout 45 --exit-timeout 5 -- src/vaultspec_a2a/providers/tests/test_codex_chat_model.py -q -k "native_interrupt or native_control"` -> `pass`
- `verify:` `.venv/Scripts/python.exe -m ruff check src/vaultspec_a2a/providers/codex_chat_model.py src/vaultspec_a2a/providers/tests/test_codex_chat_model.py` -> `pass`
- `verify:` `.venv/Scripts/python.exe -m ty check src/vaultspec_a2a/providers/codex_chat_model.py src/vaultspec_a2a/providers/tests/test_codex_chat_model.py` -> `pass`

## Notes

Codex compaction remains unavailable because the current per-generation ephemeral thread lifecycle cannot provide durable context-state effect proof. Consumer exposure remains assigned to W04.P09.S42 and W04.P09.S45.
