---
tags:
  - "#exec"
  - "#entry-point-layer"
date: "2026-03-24"
modified: '2026-07-15'
related:
  - "[[2026-03-24-entry-point-layer-plan]]"
---

# `entry-point-layer` `phase9` `step2`

Rewired `cli/_team.py` to delegate all rendering to `cli/_renderers.py`. File reduced from 825 to 493 lines.

- Modified: `src/vaultspec_a2a/cli/_team.py`

## Description

Refactored `cli/_team.py` to import rendering functions from `_renderers.py`:

- `status` command: delegates to `render_status_display()` for the non-JSON path
- `list` command: fetches pending permissions separately, passes them to `render_thread_list()`
- `_watch_async`: imports `render_event` and `handle_permission_prompt`, passes `_elapsed()` result and `api_url` as explicit arguments
- Removed `_format_elapsed()` (now in `_renderers.py` as `format_elapsed`)
- Removed all inline `_render_*` functions and `_handle_permission` from `_watch_async`

`_team.py` now contains only Click command definitions, data fetching (`_fetch_thread_metadata`), and WebSocket connection management. All domain rendering is delegated.

## Tests

- `pytest` (excluding pre-existing `test_factory.py` ACP failure): 1026 passed, 0 failed
- `pytest -m core`: 425 passed
- `_team.py`: 493 lines (target: under 525)
- `_renderers.py`: 442 lines (under 500)
- ruff check + format: clean
