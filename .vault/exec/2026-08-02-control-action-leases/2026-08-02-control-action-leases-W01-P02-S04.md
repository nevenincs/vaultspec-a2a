---
tags:
  - '#exec'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:d2b3e539cbead6df7381a3044c4f86e9fb18afa26f45a3bbaf953c95035e61b2'
step_id: 'S04'
related:
  - "[[2026-08-02-control-action-leases-plan]]"
---

# Add bounded synchronous dispatch id admission

## Scope

- `src/vaultspec_a2a/worker/app.py`
- `src/vaultspec_a2a/worker/dispatch_ids.py`

## Description

Added bounded synchronous FIFO admission for stable worker dispatch IDs before task scheduling.

## Outcome

A repeated dispatch ID receives a normal acknowledgement but schedules no second executor task.

## Notes

Admission is process-local and bounded to 10000 identifiers; durable gateway leases remain the restart authority.
