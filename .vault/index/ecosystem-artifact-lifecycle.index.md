---
generated: true
tags:
  - '#index'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W01-P01-S01]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W01-P01-S02]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W01-P02-S03]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W01-P02-S04]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W01-P02-S23]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W02-P03-S05]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W02-P03-S06]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W02-P03-S07]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W02-P03-S08]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W02-P04-S09]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W02-P04-S10]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W02-P04-S11]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W02-P04-S12]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W02-P04-S13]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W03-P05-S14]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W03-P05-S15]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W03-P05-S16]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W03-P05-S24]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W03-P06-S17]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W03-P06-S18]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W03-P06-S19]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W03-P07-S20]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W03-P07-S21]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-W03-P07-S22]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-adr]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-artifact-delete-residual-risk-audit]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-plan]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-research]]'
---

# `ecosystem-artifact-lifecycle` feature index

Auto-generated index of all documents tagged with `#ecosystem-artifact-lifecycle`.

## Documents

### adr

- `2026-07-21-ecosystem-artifact-lifecycle-adr` - `ecosystem-artifact-lifecycle` adr: `artifact lifecycle contract` | (**status:** `proposed`)

### audit

- `2026-07-21-ecosystem-artifact-lifecycle-artifact-delete-residual-risk-audit` - `ecosystem-artifact-lifecycle` audit: `residual risk in the hard-delete artifact removal path`

### exec

- `2026-07-21-ecosystem-artifact-lifecycle-W01-P01-S01` - Prove the existing workspace containment guard with a test that executes the escape refusal
- `2026-07-21-ecosystem-artifact-lifecycle-W01-P01-S02` - Record the residual risk that a confined delete still removes real files inside the user checkout
- `2026-07-21-ecosystem-artifact-lifecycle-W01-P02-S03` - Run an armed gateway and record whether the published discovery record carries a handoff reference
- `2026-07-21-ecosystem-artifact-lifecycle-W01-P02-S04` - Make a tokenless discovery publication fail loudly instead of silently unlinking the credential
- `2026-07-21-ecosystem-artifact-lifecycle-W01-P02-S23` - Remove the discovery record when the gateway that published it exits
- `2026-07-21-ecosystem-artifact-lifecycle-W02-P03-S05` - Define the retention disposition vocabulary and the declaration record type
- `2026-07-21-ecosystem-artifact-lifecycle-W02-P03-S06` - Attach a retention declaration to each artifact-creating seam in the lifecycle package
- `2026-07-21-ecosystem-artifact-lifecycle-W02-P03-S07` - Attach a retention declaration to the worker autospawn stderr log seam
- `2026-07-21-ecosystem-artifact-lifecycle-W02-P03-S08` - Add a test asserting every declared seam names a disposition and an owner
- `2026-07-21-ecosystem-artifact-lifecycle-W02-P04-S09` - Add one audited atomic write-and-rename helper that unlinks its temporary file on every failure path
- `2026-07-21-ecosystem-artifact-lifecycle-W02-P04-S10` - Route the service discovery writer through the shared helper
- `2026-07-21-ecosystem-artifact-lifecycle-W02-P04-S11` - Route the desktop discovery writer through the shared helper
- `2026-07-21-ecosystem-artifact-lifecycle-W02-P04-S12` - Route the process registry record writer through the shared helper
- `2026-07-21-ecosystem-artifact-lifecycle-W02-P04-S13` - Add a test that forces a write failure and asserts no temporary file survives
- `2026-07-21-ecosystem-artifact-lifecycle-W03-P05-S14` - Export the child session record out of the isolated config home before teardown
- `2026-07-21-ecosystem-artifact-lifecycle-W03-P05-S15` - Resolve the isolated config home under the declared desktop temporary homes root
- `2026-07-21-ecosystem-artifact-lifecycle-W03-P05-S16` - Add a sweeper for orphaned isolated config homes left by a crash
- `2026-07-21-ecosystem-artifact-lifecycle-W03-P05-S24` - Call session preservation from the ACP teardown path before the config home is removed
- `2026-07-21-ecosystem-artifact-lifecycle-W03-P06-S17` - Extend the clear action to cover control actions and permission requests
- `2026-07-21-ecosystem-artifact-lifecycle-W03-P06-S18` - Extend the clear action to cover task queue entries and thread execution state
- `2026-07-21-ecosystem-artifact-lifecycle-W03-P06-S19` - Extend the clear action to cover the checkpoint store
- `2026-07-21-ecosystem-artifact-lifecycle-W03-P07-S20` - Move service test runtime directory creation out of the dataclass constructor into start
- `2026-07-21-ecosystem-artifact-lifecycle-W03-P07-S21` - Add teardown that removes the service test runtime directory after a run
- `2026-07-21-ecosystem-artifact-lifecycle-W03-P07-S22` - Add ignore rules for the generated artifacts that currently escape them

### plan

- `2026-07-21-ecosystem-artifact-lifecycle-plan` - `ecosystem-artifact-lifecycle` plan

### research

- `2026-07-21-ecosystem-artifact-lifecycle-research` - `ecosystem-artifact-lifecycle` research: `ecosystem artifact and output lifecycle sweep`
