---
generated: true
tags:
  - '#index'
  - '#control-action-leases'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:90335860600a0bd48ba77f38fe915dcf9fc58d7aa4aa38c7897c55b8ecc85c6b'
related:
  - '[[2026-08-02-control-action-leases-W01-P01-S01]]'
  - '[[2026-08-02-control-action-leases-W01-P01-S02]]'
  - '[[2026-08-02-control-action-leases-W01-P01-S03]]'
  - '[[2026-08-02-control-action-leases-W01-P02-S04]]'
  - '[[2026-08-02-control-action-leases-W01-P02-S05]]'
  - '[[2026-08-02-control-action-leases-W02-P03-S06]]'
  - '[[2026-08-02-control-action-leases-W02-P03-S07]]'
  - '[[2026-08-02-control-action-leases-W02-P03-S08]]'
  - '[[2026-08-02-control-action-leases-W02-P03-S09]]'
  - '[[2026-08-02-control-action-leases-W02-P04-S10]]'
  - '[[2026-08-02-control-action-leases-W02-P04-S11]]'
  - '[[2026-08-02-control-action-leases-W03-P05-S12]]'
  - '[[2026-08-02-control-action-leases-W03-P05-S13]]'
  - '[[2026-08-02-control-action-leases-W03-P06-S14]]'
  - '[[2026-08-02-control-action-leases-W03-P06-S15]]'
  - '[[2026-08-02-control-action-leases-W04-P07-S16]]'
  - '[[2026-08-02-control-action-leases-W04-P07-S17]]'
  - '[[2026-08-02-control-action-leases-W04-P07-S18]]'
  - '[[2026-08-02-control-action-leases-W04-P07-S19]]'
  - '[[2026-08-02-control-action-leases-W04-P08-S20]]'
  - '[[2026-08-02-control-action-leases-W04-P08-S21]]'
  - '[[2026-08-02-control-action-leases-W04-P08-S22]]'
  - '[[2026-08-02-control-action-leases-adr]]'
  - '[[2026-08-02-control-action-leases-implementation-review-audit]]'
  - '[[2026-08-02-control-action-leases-plan]]'
  - '[[2026-08-02-control-action-leases-reference]]'
  - '[[2026-08-02-control-action-leases-research]]'
---

# `control-action-leases` feature index

Auto-generated index of all documents tagged with `#control-action-leases`.

## Documents

### adr

- `2026-08-02-control-action-leases-adr` - `control-action-leases` adr: `durable leased dispatch claims` | (**status:** `accepted`)

### audit

- `2026-08-02-control-action-leases-implementation-review-audit` - `control-action-leases` audit: `leased control dispatch implementation review`

### exec

- `2026-08-02-control-action-leases-W01-P01-S01` - Add generic dispatch lease fields and migration
- `2026-08-02-control-action-leases-W01-P01-S02` - Implement atomic reserve acquire release and settle operations
- `2026-08-02-control-action-leases-W01-P01-S03` - Prove concurrent lease elections and migration lifecycle completeness
- `2026-08-02-control-action-leases-W01-P02-S04` - Add bounded synchronous dispatch id admission
- `2026-08-02-control-action-leases-W01-P02-S05` - Prove duplicate dispatch ids schedule one executor task
- `2026-08-02-control-action-leases-W02-P03-S06` - Add clarification resolution receipts to domain and graph state
- `2026-08-02-control-action-leases-W02-P03-S07` - Implement leased clarification orchestration service
- `2026-08-02-control-action-leases-W02-P03-S08` - Reduce clarification route to the leased service adapter
- `2026-08-02-control-action-leases-W02-P03-S09` - Reconcile parked and applied clarification leases after restart
- `2026-08-02-control-action-leases-W02-P04-S10` - Migrate permission response reservation and dispatch to shared leases
- `2026-08-02-control-action-leases-W02-P04-S11` - Settle permission leases from authoritative progress events
- `2026-08-02-control-action-leases-W03-P05-S12` - Migrate follow-up message dispatch to shared leases
- `2026-08-02-control-action-leases-W03-P05-S13` - Migrate cancellation dispatch to shared leases
- `2026-08-02-control-action-leases-W03-P06-S14` - Migrate verdict resume ownership to shared leases
- `2026-08-02-control-action-leases-W03-P06-S15` - Remove obsolete metadata claim helpers and ratchet single ownership
- `2026-08-02-control-action-leases-W04-P07-S16` - Prove identical and competing concurrent clarification submissions
- `2026-08-02-control-action-leases-W04-P07-S17` - Prove lost acknowledgement expired lease and restart redrive
- `2026-08-02-control-action-leases-W04-P07-S18` - Prove permission message cancel and verdict race safety
- `2026-08-02-control-action-leases-W04-P07-S19` - Replace the clarification negative recording stub with real boundaries
- `2026-08-02-control-action-leases-W04-P08-S20` - Add an all-low Codex clarification load certification
- `2026-08-02-control-action-leases-W04-P08-S21` - Run live Codex load and focused repository quality gates
- `2026-08-02-control-action-leases-W04-P08-S22` - Audit the complete implementation and queue or fix every finding

### plan

- `2026-08-02-control-action-leases-plan` - `control-action-leases` plan

### reference

- `2026-08-02-control-action-leases-reference` - `control-action-leases` reference: `existing control journal and resume paths`

### research

- `2026-08-02-control-action-leases-research` - `control-action-leases` research: `atomic dispatch ownership and recovery`
