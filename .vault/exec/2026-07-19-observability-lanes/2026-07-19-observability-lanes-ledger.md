---
tags:
  - '#exec'
  - '#observability-lanes'
date: '2026-07-19'
modified: '2026-09-03'
body_schema: 'body-v2'
body_hash: 'sha256:3e19fbfdeb7a2e45cc7f580b5076317b799668f2536ca7639cce9c95ca5d6fcb'
related:
  - "[[2026-07-19-observability-lanes-plan]]"
---

# `observability-lanes` ledger

## Changes

- `S01` `T` `src/vaultspec_a2a/utils/logging.py`
- `S01` `T` `src/vaultspec_a2a/utils/tests/`
- `S01` `T` `src/vaultspec_a2a/control/config.py`
- `S02` `T` `src/vaultspec_a2a/api/app.py`
- `S02` `T` `src/vaultspec_a2a/worker/app.py`
- `S02` `T` `src/vaultspec_a2a/cli/main.py`
- `S02` `T` `src/vaultspec_a2a/protocols/mcp/authoring_stdio.py`
- `S03` `T` `src/vaultspec_a2a/lifecycle/`
- `S03` `T` `src/vaultspec_a2a/control/worker_management.py`
- `S03` `T` `src/vaultspec_a2a/lifecycle/tests/`
- `S04` `T` `src/vaultspec_a2a/control/dispatch.py`
- `S04` `T` `src/vaultspec_a2a/api/websocket.py`
- `S04` `T` `pyproject.toml`
- `S04` `T` `docs/`
- `S05` `T` `src/vaultspec_a2a/protocols/mcp/__main__.py`
- `S05` `T` `src/vaultspec_a2a/utils/logging.py`
- `S05` `T` `src/vaultspec_a2a/utils/tests/`
- `S06` `T` `websocket: failing client ids at the recovery or periodic summary) so storm dedup keeps per-entity diagnosability`
- `S06` `T` `and scope the websocket recovered message so it cannot claim global recovery while other clients still fail. Live tests asserting ids appear in summaries while gapped occurrences stay unlogged`
- `S06` `T` `src/vaultspec_a2a/control/dispatch.py`
- `S06` `T` `src/vaultspec_a2a/api/websocket.py`
- `S06` `T` `src/vaultspec_a2a/control/tests/`
- `S06` `T` `src/vaultspec_a2a/api/tests/`
