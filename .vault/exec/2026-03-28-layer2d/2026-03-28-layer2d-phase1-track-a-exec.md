---
tags:
  - '#exec'
  - '#layer-2d'
date: '2026-03-28'
related:
  - '[[2026-03-28-layer2d-file-size-plan]]'
---

# layer-2d phase-1 track-a: extract shared HTTP helper

## Summary

Created `protocols/mcp/_http.py` containing the shared httpx client
lifecycle, HTTP status constants, credential-stripping utility, preset
cache, and the `_mcp_request` coroutine.

## Changes

- New file `_http.py` (197 lines): `_shared_client`, `_get_client()`,
  `_reset_client()`, `_HTTP_OK`, `_HTTP_NOT_FOUND`, `_HTTP_CONFLICT`,
  `_strip_credentials()`, `_known_presets_cache`, `_get_known_presets()`,
  `_reset_known_presets()`, `_mcp_request()`, re-exported
  `HTTPStatusError` for downstream tool modules
- Updated `server.py` imports to source moved symbols from `_http`
- Updated test imports: `_reset_client` and `_reset_known_presets` now
  imported from `.._http`; inline `_get_known_presets` import and
  `sys.modules` lookup updated to target `_http` module

## Verification

- 38/38 MCP tests passed
