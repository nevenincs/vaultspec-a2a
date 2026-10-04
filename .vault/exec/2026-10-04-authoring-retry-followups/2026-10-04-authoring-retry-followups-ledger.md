---
tags:
  - '#exec'
  - '#authoring-retry-followups'
date: '2026-10-04'
modified: '2026-10-04'
body_schema: 'body-v2'
body_hash: 'sha256:55100e38bea0328ae15fd4cdc90534dc3acb41a82b39694068812b71923edb72'
related:
  - "[[2026-10-04-authoring-retry-followups-plan]]"
---

# `authoring-retry-followups` ledger

## Changes

- `S01` `M` `src/vaultspec_a2a/protocols/mcp/tools/authoring_bridge.py`
- `S01` `M` `src/vaultspec_a2a/protocols/mcp/authoring_stdio.py`
- `S01` `M` `src/vaultspec_a2a/providers/_acp_authoring.py`
- `S01` `M` `src/vaultspec_a2a/authoring/tests/test_dispatch_injection.py`
- `S01` `M` `src/vaultspec_a2a/providers/tests/test_acp_authoring.py`
- `S01` `M` `src/vaultspec_a2a/providers/tests/test_codex_config_home.py`
- `S01` `verify:` `native metadata stdio restart and authoring tests` -> `pass`
- `S01` `verify:` `provider source selection and trusted launch tests` -> `pass`
- `S01` `verify:` `Ruff lint format and full project ty` -> `pass`
- `S02` `A` `src/vaultspec_a2a/authoring/_bridge_refresh.py`
- `S02` `M` `src/vaultspec_a2a/protocols/mcp/authoring_stdio.py`
- `S02` `M` `src/vaultspec_a2a/providers/_acp_authoring.py`
- `S02` `A` `src/vaultspec_a2a/authoring/tests/test_stdio_refresh.py`
- `S02` `M` `src/vaultspec_a2a/providers/tests/test_acp_authoring.py`
- `S02` `verify:` `stdio refresh provider replay and client suite 76 passed` -> `pass`
- `S02` `verify:` `Ruff lint format and full project ty` -> `pass`
- `S03` `M` `src/vaultspec_a2a/authoring/_tool_calls.py`
- `S03` `M` `src/vaultspec_a2a/control/cleanup/executor.py`
- `S03` `A` `src/vaultspec_a2a/authoring/tests/test_tool_call_retirement.py`
- `S03` `M` `src/vaultspec_a2a/control/tests/test_thread_deletion_saga.py`
- `S03` `verify:` `SQLite retirement and durable cleanup suite 41 passed` -> `pass`
- `S03` `verify:` `real Linux agent UID replay new and legacy retirement proof` -> `pass`
- `S03` `verify:` `Ruff lint format and full project ty` -> `pass`
- `S03` `verify:` `actual implementation review and classified audit queue update` -> `pass`
- `S03` `by:` `codex`

## Notes

- `S01` Native real-model proof pending: no current served catalog selector; Step remains open.
- `S02` S02 stays open: isolated UID profiles omit protected discovery until a parent-owned runtime relay is decided and proven. Native service test was deselected by repository policy, not treated as passing.
- `S03` Implementation entered peer commits 3f4a8f6a and f9f2ae89; this checkpoint corrects Windows fsync and records final applicable verification. Shared-store hostile-agent integrity and flat-scan costs remain recorded lower-severity follow-ups.
