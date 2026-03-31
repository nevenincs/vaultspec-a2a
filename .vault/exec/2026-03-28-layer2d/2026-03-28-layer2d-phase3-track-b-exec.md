---
tags:
  - '#exec'
  - '#layer-2d'
date: '2026-03-28'
related:
  - '[[2026-03-28-layer2d-file-size-plan]]'
---

# phase 3 — ACP session + config extraction (track B)

Extracted session lifecycle, auth helpers, and config dataclass from
`acp_chat_model.py` into `providers/_acp_session.py` per ADR D-04.

- Created `_AcpModelConfig` frozen dataclass with all 17 read-only fields
- Moved `_AcpSessionContext` and extended with `tool_calls`, `agent_modes`,
  `last_auth_url` fields
- Extracted `runtime_log_extra()` as free function taking `_AcpModelConfig`
- Extracted session lifecycle: `initialize_session`, `setup_session`,
  `authenticate_rpc`, `wait_for_authenticate_response`, `setup_prompt`,
  `send_notification`
- Extracted auth helpers: `auth_hint`, `auth_url_hint`,
  `select_auth_method_id`, `is_auth_required_error`,
  `is_auth_cancelled_error`, `is_auth_rejected_error`,
  `raise_auth_outcome_error`
- Moved `_log_task_exception` and `_AuthResponseCancelledError`
- Added `model_post_init` logic to build `self._config: _AcpModelConfig`
- Removed `_agent_capabilities`, `_agent_modes`, `_tool_calls`,
  `_last_auth_url` from class PrivateAttrs (kept `_auth_methods`)
- Updated all test imports in `test_acp_chat_model.py` to use free functions
- 123 providers tests pass
