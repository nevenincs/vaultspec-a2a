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
  - '[[2026-10-04-authoring-retry-followups-parent-authority-adr]]'
modified: '2026-10-04'
body_schema: body-v2
body_hash: 'sha256:df1518be2b1269c7715ccc2c61e079051d6e1727f7148ed13dfb72898528a167'
---

# `authoring-retry-followups` plan

## Description

Approved 2026-10-04

Basis: the user's instruction to continue the three follow-ups recorded in `2026-10-04-a2a-edge-conformance-authoring-retry-audit`. Preserve stable call identity, credential isolation and engine-owned execution. The authoring-edge ADR governs S01/S02; action leases and run-continuation govern S03's deletion boundary. Do not claim native lane capability without a completed real provider turn. A missing native hook or inaccessible protected discovery remains an explicit evidence gap, with no unsafe fallback.

Approved extension 2026-10-04: the user instructed continued implementation of all remaining items. S04 introduces the worker-owned runtime authoring relay and private replay placement governed by the parent-authority ADR; it completes isolated refresh under S02 and closes the shared-journal integrity gap. Preserve closed S03's deletion policy and historical shared files for cleanup. The user selected the lowest native model tiers: Codex gpt-6-luna and Claude haiku; use their current catalog identities only for disposable proof turns.

## Steps

- [x] `S01` - Consume the Codex native logical identity and establish the remaining provider proof boundary; `protocols/mcp, providers/_acp_authoring.py and providers/_codex_config_home.py with corresponding native certification and configuration tests`.
- [x] `S02` - Wire stdio bearer refresh to explicitly handed protected discovery and verify rotation; `new authoring/_bridge_refresh.py, protocols/mcp/authoring_stdio.py, providers/_acp_authoring.py and process tests`.
- [x] `S03` - Reclaim authoring journal entries at durable run deletion while preserving closed identity; `authoring/_tool_calls.py, control/cleanup/executor.py, journal and deletion tests and retention decision`.
- [x] `S04` - Execute provider authoring calls through worker-owned runtime authority and private replay state; `new worker/authoring_relay.py and authoring/_relay_client.py, worker lifespan and binding, stdio provider handoff, connection proof and real protocol platform tests`.

## Parallelization

Execute sequentially. S01 closes with native certification; S04 supplies parent authority and isolated refresh, then S02 receives its final completion checkpoint. S03 remains complete. Preserve concurrent engine-discovery and workspace changes. This plan does not authorize provider dependency upgrades or changes to the dashboard engine API.

## Verification

Use real MCP/HTTP/process tests for native metadata, bearer rotation and stable envelopes; prove unavailable/malicious discovery refuses refresh. Exercise SQLite retirement and the real deletion coordinator, including restart and stale dispatch. Run Ruff lint/format, project type checks and vault conformance. Review actual diffs and record every classified issue in the existing authoring retry audit before closing each Step.
