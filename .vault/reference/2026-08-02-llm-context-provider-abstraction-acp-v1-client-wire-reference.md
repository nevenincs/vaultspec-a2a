---
tags:
  - '#reference'
  - '#llm-context-provider-abstraction'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:be0065ef167a69c5b4306989008d4655743b9e817186b44bb7bc4100514c71d6'
related:
  - "[[2026-02-25-llm-context-provider-abstraction-adr]]"
---
# `llm-context-provider-abstraction` reference: `ACP v1 client wire`

## Summary

The installed `@agentclientprotocol/sdk@1.2.1` JSON schema is the local, version-pinned contract for the client-side RPCs this provider runtime answers. It exposes five incompatible behaviours in the current hand-rolled handlers: filesystem reads use a one-based `line` and line-count `limit` rather than a byte `offset`; every listed client request requires `sessionId`; `terminal/create` accepts `outputByteLimit`; terminal output and wait responses use an `exitStatus` object with nullable `exitCode` and string `signal`; and kill terminates without discarding the terminal. `node_modules/@agentclientprotocol/sdk/schema/schema.json:328-367`, `:1178-1233`, `:1256-1378`, `:8050-8145`.

## Current implementation map

- `on_fs_read_text_file` accepts `offset`, seeks bytes, and limits Python characters. `src/vaultspec_a2a/providers/_acp_rpc_handlers.py:383-412`.
- Terminal creation records only process identity; it does not interpret `outputByteLimit`. `src/vaultspec_a2a/providers/_acp_rpc_handlers.py:609-618`.
- `on_terminal_kill` removes the live terminal mapping immediately, preventing subsequent output, wait, or release requests. `src/vaultspec_a2a/providers/_acp_rpc_handlers.py:669-679`.
- Terminal output inserts a scalar process return code as `exitStatus`; waiting returns a top-level `exitCode` and numeric signal. `src/vaultspec_a2a/providers/_acp_rpc_handlers.py:706-741`.
- The runtime has a session identifier after setup, so handlers can be made to validate request ownership rather than treating it as unscoped. `src/vaultspec_a2a/providers/_acp_types.py:117-122`.

## Contract baseline

The schema marks `sessionId` and method-specific payload fields required for filesystem and terminal requests. `ReadTextFileRequest` takes `path`, optional non-negative `line`, and optional non-negative `limit`; `offset` is not part of that request. `node_modules/@agentclientprotocol/sdk/schema/schema.json:328-367`.

`CreateTerminalRequest` additionally defines nullable non-negative `outputByteLimit`, with retained output truncated from the beginning at character boundaries. `node_modules/@agentclientprotocol/sdk/schema/schema.json:1178-1233`.

`TerminalOutputResponse` returns `output`, `truncated`, and an optional `TerminalExitStatus`; `WaitForTerminalExitResponse` returns an exit-status object with nullable integer `exitCode` and nullable string `signal`. `node_modules/@agentclientprotocol/sdk/schema/schema.json:8050-8145`.

The schema documentation says `terminal/kill` does not release a terminal; only `terminal/release` makes it unusable. `node_modules/@agentclientprotocol/sdk/schema/schema.json:190-198`, `:1349-1378`.

## Supported-client implications

The current migration-surface test proves the real Claude ACP adapter's initialize and session setup path, but it does not exercise any of these server-to-client request payloads. `src/vaultspec_a2a/providers/tests/test_acp_migration_surface.py:70-124`. A direct conforming replacement can therefore add focused real-stdio contract probes without preserving byte-offset or scalar-exit compatibility for an unproven client. The old accepted provider-harness ADR retains the subscription-first and ACP transport foundations; this reference only narrows the client wire contract beneath that foundation. `2026-02-25-llm-context-provider-abstraction-adr`.
