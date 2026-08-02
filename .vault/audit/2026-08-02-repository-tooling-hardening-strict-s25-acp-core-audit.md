---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:64bc71a6862b74e8505340782f6f8536a8319c59e1402c56229be006ea0d5581'
related: []
---
# `repository-tooling-hardening` audit: `ACP core wire and permission contract review`

## Scope

Independent read-only P25-G review of the ACP core wire boundary: public configuration and session carriers, JSON-RPC frame parsing and dispatch, authentication, session setup, permission enforcement, terminal and filesystem handlers, subprocess containment, and `AcpChatModel`. Also reviewed the ten renamed direct consumers and their real-behavior evidence. No source was edited in this audit.

## Findings

### acp-terminal-wire-semantics | medium | Terminal and filesystem details need an explicit ACP behavior decision

The strict type repair is sound but leaves four protocol choices that need a governing compatibility decision before a later cleanup treats them as mechanical: `fs/read_text_file` passes `offset` and `limit` to text `seek` and `read`, therefore treating them as character positions/counts rather than a documented byte or line contract; `terminal/output` returns scalar numeric `exitStatus` rather than an explicit exit-status object; `terminal/wait_for_exit` returns numeric signal identifiers rather than a protocol string; and `terminal/kill` immediately removes the terminal mapping, making later output or wait calls an unknown-terminal refusal. The direct real-process tests prove the current behavior, but not that it matches every supported ACP client. This is behavior/protocol compatibility debt, not a type-safety defect in P25-G.

## Recommendations

Keep the current P25-G behavior unchanged. Assign `W06.P12.S26` a focused protocol-compatibility follow-up and require an ADR to decide the ACP meanings for filesystem offsets, terminal exit status, signal representation, and post-kill terminal retention before implementation. Preserve the current real-process regression evidence and add client-compatible wire-shape probes once the decision is accepted.
