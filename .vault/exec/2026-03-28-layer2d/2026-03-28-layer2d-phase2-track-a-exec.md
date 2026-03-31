---
tags:
  - '#exec'
  - '#layer-2d'
date: '2026-03-28'
related:
  - '[[2026-03-28-layer2d-file-size-plan]]'
---

# layer-2d phase-2 track-a: handler split + server slim

## Summary

Split 11 MCP tool handlers from `server.py` into four domain-grouped
modules under `protocols/mcp/tools/`. Slimmed `server.py` to a 55-line
FastMCP registration stub.

## Changes

- Created `tools/__init__.py` (empty)
- Created `tools/thread_lifecycle.py` (264 lines): `start_thread`,
  `cancel_thread`, `delete_thread`, `archive_thread`
- Created `tools/thread_query.py` (196 lines): `get_thread_status`,
  `list_threads`, `_ws_url_from_api_base`
- Created `tools/messaging.py` (69 lines): `send_message`
- Created `tools/discovery.py` (217 lines): `get_team_status`,
  `get_pending_permissions`, `respond_to_permission`, `list_team_presets`
- Slimmed `server.py` to 55 lines: FastMCP instance + side-effect
  registration imports
- Added per-file-ignores in `pyproject.toml` for `server.py` (E402, F401)
- Updated all 14 test import sites in `test_server.py` to new module paths
- All tool modules use `_mcp_request()` for HTTP calls; zero direct
  httpx imports in `tools/`

## Structural verification

- `server.py`: 55 lines (target < 100)
- All files under 1,000 lines
- Zero `import httpx` in `protocols/mcp/tools/`
- 38/38 MCP tests passed
- 413 non-provider middleware tests passed (1 pre-existing provider
  failure in `test_acp_security.py` unrelated to this change)
