---
tags:
  - "#exec"
  - "#core-layer"
date: "2026-03-23"
modified: '2026-03-23'
related:
  - "[[2026-03-23-core-layer-boundary-plan]]"
  - "[[2026-03-23-core-layer-boundary-adr]]"
---

# core-layer phase-2 config split

Split `core/config.py` (731 lines, ~93 fields) into domain vs infrastructure
configuration, preserving full backwards compatibility.

## Files Created

- `src/vaultspec_a2a/domain_config.py` — 18 domain fields (DomainConfig)
- `src/vaultspec_a2a/control/config.py` — ~75 infrastructure fields
  (InfraConfig), composed Settings facade, global `settings` singleton

## Files Modified

- `src/vaultspec_a2a/core/config.py` — replaced with re-export shim
  delegating to `control.config` and `domain_config`
- `src/vaultspec_a2a/core/__init__.py` — removed eager `Settings`/`settings`
  import; added `_REDIRECTS` entries for `settings`, `Settings`, `DomainConfig`

## Domain Fields (18)

`tool_call_debounce_seconds`, `plan_update_debounce_seconds`,
`chunk_flush_interval_seconds`, `debounce_map_max_entries`,
`chunk_buffer_max_bytes`, `tool_arg_truncate_len`, `event_queue_maxsize`,
`aget_state_timeout_seconds`, `context_limit_tokens`, `chars_per_token`,
`anchor_path_cap`, `max_context_refs`, `vault_index_cap`,
`mount_token_ceiling`, `min_remaining_tokens_for_mount`,
`task_queue_pending_horizon`, `graph_recursion_limit`, `max_cached_graphs`

## Infrastructure Fields (~75)

Everything else: ports, hosts, database URLs/backends, API keys, filesystem
paths, pool sizes, service timeouts, CORS, worker settings, ACP settings,
MCP settings, WebSocket settings, IPC settings, OAuth, LangSmith, env flags.

## Backwards Compatibility

All four import paths verified:

- `from vaultspec_a2a.domain_config import DomainConfig` — direct
- `from vaultspec_a2a.control.config import Settings, settings` — canonical
- `from vaultspec_a2a.core import settings` — via `_REDIRECTS`
- `from vaultspec_a2a.core.config import settings` — via re-export shim

`isinstance(settings, DomainConfig)` returns True.

## Validators Preserved

- `_normalize_blank_internal_token` field_validator on InfraConfig
- `_derive_service_urls` model_validator on Settings
- All 7 properties (`is_dev`, `resolved_database_backend`,
  `resolved_checkpoint_backend`, `database_path`, `checkpoint_path`,
  `checkpoint_connection_string`, `database_sync_url`) on Settings
- `validate_postgres_requirement()` method on Settings

## Test Results

- `test_config.py`: 4/4 passed
- `core/tests/` (excluding test_graph.py): 402 passed, 9 deselected
- `ruff check` + `ruff format`: clean
