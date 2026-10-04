---
tags:
  - '#plan'
  - '#authoring-retry-followups'
date: '2026-10-04'
tier: L1
related:
  - '[[2026-07-14-a2a-edge-conformance-adr]]'
  - '[[2026-10-01-run-continuation-adr]]'
  - '[[2026-08-02-control-action-leases-adr]]'
  - '[[2026-10-04-authoring-retry-followups-journal-retirement-adr]]'
modified: '2026-10-04'
body_schema: body-v2
body_hash: 'sha256:4b9d9a12f195217b521f2ed7e6b5c129915c6d6d39347fc9a2cc224a5ab7e5b4'
---

# `authoring-retry-followups` plan

## Description

Approved 2026-10-04

Basis: the user's instruction to continue the three follow-ups recorded in `2026-10-04-a2a-edge-conformance-authoring-retry-audit`. Preserve stable call identity, credential isolation and engine-owned execution. The authoring-edge ADR governs S01/S02; action leases and run-continuation govern S03's deletion boundary. Do not claim native lane capability without a completed real provider turn. A missing native hook or inaccessible protected discovery remains an explicit evidence gap, with no unsafe fallback.

## Steps

- [ ] `S01` - Consume the Codex native logical identity and establish the remaining provider proof boundary; `src/vaultspec_a2a/protocols/mcp and providers/_acp_authoring.py with corresponding tests`.
- [ ] `S02` - Wire stdio bearer refresh to explicitly handed protected discovery and verify rotation; `new authoring/_bridge_refresh.py, protocols/mcp/authoring_stdio.py, providers/_acp_authoring.py and process tests`.
- [x] `S03` - Reclaim authoring journal entries at durable run deletion while preserving closed identity; `authoring/_tool_calls.py, control/cleanup/executor.py, journal and deletion tests and retention decision`.

## Parallelization

Execute sequentially. Preserve concurrent engine-discovery and workspace changes. This plan does not authorize provider dependency upgrades or changes to the dashboard engine API.

## Verification

Use real MCP/HTTP/process tests for native metadata, bearer rotation and stable envelopes; prove unavailable/malicious discovery refuses refresh. Exercise SQLite retirement and the real deletion coordinator, including restart and stale dispatch. Run Ruff lint/format, project type checks and vault conformance. Review actual diffs and record every classified issue in the existing authoring retry audit before closing each Step.
