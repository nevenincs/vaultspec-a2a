---
tags:
  - '#exec'
  - '#resource-aware-test-execution'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:f0bf260c137d89400fbfb8851c881f2e3e8313263582b797d800288789133a58'
step_id: 'S18'
related:
  - "[[2026-08-02-resource-aware-test-execution-plan]]"
---
# Heartbeat held reservations so process-lifetime holds outlive the reservation TTL

## Scope

- `src/vaultspec_a2a/tests/gateway_boot.py`

## Description

- Heartbeat every process-lifetime reservation from one daemon refresher
well inside the reservation TTL, stopped at exit alongside release.

## Outcome

Committed as a0d06839. The proof genuinely ages a held marker past the TTL on disk, shows the allocator judges it reclaimable, and shows one refresh pass restores LIVE - the amended decision record's process-lifetime claim is now true.

## Notes

Context-scoped reserved_port holds remain TTL-bounded by design; the audit notes the distinction.
