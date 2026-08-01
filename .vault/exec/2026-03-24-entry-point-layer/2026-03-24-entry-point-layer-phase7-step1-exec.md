---
tags:
  - '#exec'
  - '#entry-point-layer'
date: '2026-03-24'
modified: '2026-07-15'
body_hash: 'sha256:6fc0e13b12e96d80257deb1c8e1206c4a0454b750279d64b0f4da24bc1984c84'
related:
  - '[[2026-03-24-entry-point-layer-plan]]'
---

# `entry-point-layer` `phase7` `step1`

Extracted `_CacheControlMiddleware` from `api/app.py` to `api/middleware.py`.

- Created: `src/vaultspec_a2a/api/middleware.py` (40 lines)
- Modified: `src/vaultspec_a2a/api/app.py` (imports updated)

## Description

Moved the cache-control middleware class and its supporting constants
(`_IMMUTABLE_PATTERN`, `_CACHE_IMMUTABLE`, `_CACHE_HTML`) to a dedicated
`api/middleware.py` module. Renamed to `CacheControlMiddleware` (public in
its new module). `app.py` imports from `middleware.py`.

## Tests

All 10 `test_app.py` tests pass. No middleware-specific tests needed as
behavior is unchanged.
