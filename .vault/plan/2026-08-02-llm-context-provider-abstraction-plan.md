---
tags:
  - '#plan'
  - '#llm-context-provider-abstraction'
date: '2026-08-02'
tier: L2
related:
  - '[[2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-adr]]'
  - '[[2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-research]]'
  - '[[2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-reference]]'
modified: '2026-10-04'
body_hash: 'sha256:c60394ee16f886506892cd3c861fb0142b753d40f4303f82a24c219bdab1dbfe'
---

# `llm-context-provider-abstraction` plan

ACP v1 client-wire conformance.

## Description

Approved 2026-10-05

Authorization: the user requested ALL remaining issue fixes, sequentially, and repeatedly directed continued work and verification.

Execute the accepted ACP v1 client wire decision through the existing handler boundary and real supported-adapter evidence. The work is grounded in `2026-08-02-llm-context-provider-abstraction-acp-v1-client-wire-adr`, its research, and its reference; it does not reopen the parent provider-harness architecture.

P01.S02 retains one combined output tail capped at the smaller of the strict ACP uint64 request and a 1 MiB server budget; missing/null selects that budget, and zero retains nothing while draining. Separate incremental UTF-8 decoders merge decoded stream arrivals without claiming a total stdout/stderr chronology. Final drain settlement is bounded so descendants holding pipes cannot prevent output snapshots or release. These are routine implementation details within the accepted retained-output and lifecycle contract.

## Steps

### Phase `P01` - v1 handler and lifecycle contract

Replace the divergent filesystem and terminal request, response, ownership, and release behaviours with one ACP v1 contract.

- [x] `P01.S01` - Validate ACP v1 session ownership and replace byte-offset filesystem reads with one-based line pagination.; `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`.
- [x] `P01.S02` - Bound terminal output retention by the requested byte limit without splitting UTF-8 characters.; `src/vaultspec_a2a/providers/_acp_client_requests.py, src/vaultspec_a2a/providers/_acp_rpc_terminal_handlers.py, src/vaultspec_a2a/providers/_acp_terminal_output.py, src/vaultspec_a2a/providers/_acp_types.py, src/vaultspec_a2a/providers/tests, src/vaultspec_a2a/desktop_tests/test_owned_process_tree.py`.
- [x] `P01.S03` - Return ACP v1 exit-status objects and preserve killed terminal identity until explicit release.; `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`.

### Phase `P02` - real wire verification

Prove the supported adapter observes exact v1 payloads and terminal lifecycle without doubles or compatibility fallbacks.

- [x] `P02.S04` - Replace obsolete terminal-containment expectations with exact ACP v1 response and lifetime assertions.; `src/vaultspec_a2a/providers/tests/test_terminal_containment.py`.
- [ ] `P02.S05` - Prove supported-adapter filesystem and terminal requests over real stdio with no legacy-shape fallback.; `src/vaultspec_a2a/providers/tests/test_acp_migration_surface.py`.

### Phase `P03` - strict closure and audit

Run configured strict gates, classify review findings, and retain explicit evidence for any unavailable external prerequisite.

- [ ] `P03.S06` - Run strict static and real-behaviour test gates for the ACP v1 surface and classify every review finding.; `src/vaultspec_a2a/providers, src/vaultspec_a2a/providers/tests, .vault/audit, .vault/exec`.

## Parallelization

P01.S01-P01.S03 share one handler module and execute sequentially. P02.S04 can proceed independently after P01.S03 defines the terminal lifecycle; P02.S05 follows P01 because it proves the final request shapes. P03 follows both verification steps.

## Verification

- Run the scoped strict Basedpyright, Ty, Ruff, and formatting gates with zero diagnostics.
- Prove filesystem line semantics, session isolation, output-byte retention, exit-status shape, post-kill addressability, and release through real protocol traffic.
- Run the available real-provider service lane; any unavailable named prerequisite must fail loudly and remain an audit boundary rather than become a skip.
- Complete an independent review, persist its classified findings, and close every plan step only with corresponding execution evidence.
