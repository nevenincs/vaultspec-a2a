---
tags:
  - '#exec'
  - '#kimi-provider'
date: '2026-07-17'
modified: '2026-07-17'
step_id: 'S10'
related:
  - "[[2026-07-17-kimi-provider-plan]]"
---

# Extend the on_request_permission handler to auto-approve exactly the composed read-tool names plus the enumerated Kimi native read tools in autonomous mode and reject every other request (executor-core)

## Scope

- `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`

## Description

- Enumerate Kimi's native read tools mirroring the tool-cores read floor into `_KIMI_NATIVE_READ_TOOLS = {ReadFile, Grep, Glob}`, from the installed kimi-cli 1.49.0 source and cross-checked against executor-service's P04.S15 verification.
- Add `_strip_mcp_prefix` (Claude-form `mcp__<server>__<tool>` to Kimi's raw tool name) and `_kimi_autonomous_option_id` (the exact-name auto-approve/reject decision keyed on the permission title prefix).
- Add an autonomous Kimi branch to `on_request_permission`: when `acp_family == "kimi"` and no `permission_callback`, auto-approve exactly the composed read tools plus the native read tools and reject everything else.

## Outcome

Read-only discipline is enforced at our `session/request_permission` handler for the Kimi lane, as an EXACT-name auto-approve set rather than blanket approval - the Claude `allowedTools` allowlist re-expressed at the RPC layer for a CLI that carries no config allowlist. Verified against representative titles: `ReadFile`/`Grep`/`Glob` and the composed rag reads (`search_codebase` etc.) resolve to `approve`; `WriteFile`, `StrReplaceFile`, `bash`, `SearchWeb`, and `Agent` resolve to `reject`. The branch is additive: it only fires for `acp_family == "kimi"` (default `"claude"`), so the existing Claude/Z.ai permission behavior is unchanged - 45 existing permission/security tests still pass. The deterministic both-branch tests are P03.S11.

## Notes

- TWO KEY GROUNDINGS from the installed kimi-cli source that shaped the matching (a naive match would have been wrong):
  1. Kimi exposes MCP tools by their RAW name (`soul/toolset.py`: `MCPTool.name = mcp_tool.name`), so its permission title carries `search_vault`, NOT the Claude-form `mcp__vaultspec-rag__search_vault`. Hence `_strip_mcp_prefix` reduces our composed allowlist entries to raw names before matching.
  2. The permission request identifies the tool by `get_title()` = `f"{tool_name}: {subtitle}"` or `tool_name` (`acp/session.py`), and options are `approve`/`approve_for_session`/`reject`. Hence the decision keys on `title.split(": ", 1)[0]` and selects by option `kind` (`allow_once`/`reject_once`), not a hardcoded id.
- Native read set enumerated + cited, aligned to the tool-cores read floor (Claude Read/Grep/Glob): `ReadFile` (`tools/file/read.py:64`), `Grep` (`tools/file/grep_local.py:386`), `Glob` (`tools/file/glob.py:56`) - the three that mirror the floor. NOTE the name divergence: Kimi's read tool is `ReadFile`, not Claude's `Read`. `WriteFile`/`StrReplaceFile` (writes), the `bash`/shell exec tool, and the plan/dmail/agent/todo mutators are omitted and thus rejected. `ReadMediaFile` (image reads, `tools/file/read_media.py:51`) and the web tools `FetchURL`/`SearchWeb` are read-only but DELIBERATELY EXCLUDED: neither is part of the text-grounding floor (no Claude-floor analogue), so the conservative posture omits them. DIVERGENCE RESOLVED: an earlier landed revision of this Step included `ReadMediaFile` in the set; executor-service's P04.S15 authoritative enumeration and the lead's relay fixed the floor at `ReadFile`/`Grep`/`Glob`, so `ReadMediaFile` was moved to the rejected set (a follow-up commit) and the S11 test now asserts it is rejected.
- Autonomy signal: autonomous == `permission_callback is None` (supervised runs carry the interrupt callback), so the Kimi branch sits in the no-callback path; supervised Kimi keeps its prompts unchanged (P03.S11 asserts this).
