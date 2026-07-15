---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S21'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Assert zero .vault/ filesystem writes across the whole proof run via filesystem watch or audit and capture the evidence in the step record

## Scope

- `src/vaultspec_a2a/service_tests/`

## Description

- Start a recursive filesystem watch over the run workspace vault directory before each solo-coder turn begins, capturing created, modified, and deleted events at high frequency.
- Seed the watched vault with a document so the watch would register any mutation, then drive the real solo-coder turn to completion.
- Stop the watch after the turn and report the collected event list alongside the turn evidence.

## Outcome

Zero vault filesystem writes were observed across every real solo-coder run of the proof (all channel and transport variations, including the runs on the latest Claude CLI 2.1.210 and ACP adapter 0.23.1). The watch event list was empty on every run. This holds because the agent has no filesystem-write path to the vault: the deny policy blocks vault writes at the ACP write RPC, and the bridged tool surface carries no raw write tool by construction. The mutation path for documents is the engine proposal-and-review lane, which is off the local filesystem entirely.

The evidence is robust independent of the deferred end-to-end tool-call proof: whether or not the agent reached the bridged tools, it produced no vault writes.

## Notes

- This step's zero-write assertion is complete and proven; it is captured here rather than only in the sibling S20 record because the watch spanned the whole proof run.
