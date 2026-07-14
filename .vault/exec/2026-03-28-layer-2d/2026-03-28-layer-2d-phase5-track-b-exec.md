---
tags:
  - '#exec'
  - '#layer-2d'
date: '2026-03-28'
modified: '2026-07-14'
related:
  - '[[2026-03-28-layer2d-file-size-plan]]'
---

# phase 5 — ACP RPC handler extraction (track B)

Extracted RPC handlers from `acp_chat_model.py` into
`providers/_acp_rpc_handlers.py` per ADR D-06.

- Moved constants: `_TERMINAL_COMMAND_ALLOWLIST`, `_SHELL_METACHAR_RE`,
  `_ENV_NAME_RE`
- Extracted `sandbox_path(path, config)` free function
- Extracted `on_request_permission` — uses `config.permission_callback`
- Extracted filesystem: `on_fs_read_text_file` (imports
  `settings.acp_fs_read_max_bytes`), `on_fs_write_text_file` (imports
  `_git_mutex`)
- Extracted terminal: `on_terminal_create` (imports `resolve_env_vars`),
  `on_terminal_kill`, `on_terminal_output`, `on_terminal_wait_for_exit`,
  `on_terminal_release`
- Updated `test_acp_security.py` imports to `_acp_rpc_handlers`
- 123 providers tests pass
