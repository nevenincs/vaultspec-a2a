---
tags:
  - '#plan'
  - '#ecosystem-artifact-lifecycle'
date: '2026-07-21'
modified: '2026-07-21'
tier: L3
related:
  - '[[2026-07-21-ecosystem-artifact-lifecycle-adr]]'
  - '[[2026-07-21-ecosystem-artifact-lifecycle-research]]'
---

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the
       related: field above.
     - The related: field carries the AUTHORISING documents
       (ADR, research, reference, prior plan) for every Step in
       this plan. Steps inherit this chain; per-row reference
       footers do not exist.
     - NEVER use [[wiki-links]] or markdown links in the
       document body. -->

# `ecosystem-artifact-lifecycle` plan

Disarm the destructive paths, then make retention a declared and enforced property of
every artifact this project creates.

## Description

This plan executes the artifact lifecycle contract decision. That record establishes that
retention is declared at the seam which creates an artifact, that permanence is a valid
but stated choice, and that enforcement belongs at creation rather than in a central
sweeper. The grounding sweep is recorded in the feature's research document.

The plan is ordered by safety rather than by visibility. The decision names a hard
sequencing constraint: the workspace-delete path must be disarmed before anything persists
artifact rows, because persisting those rows is precisely what arms it. The most valuable
user-facing improvement available - preserving the agent trace the system currently
destroys unread - is therefore deliberately gated behind unglamorous safety work on a path
that appears dead today.

Three defects found by the same sweep are explicitly out of scope for this plan and are not
represented as Steps, because this repository cannot land them: the dashboard console-script
name mismatch, the dashboard discovery location and filename divergence, and the sibling
indexer's reclaim predicate. Each needs a decision record in its own repository. The
service-token publication defect is likewise represented here only as a live verification
Step, not as a fix, because the diagnosis is an inference about the launch path that must be
confirmed by an armed run before any code changes.

Wave one disarms and verifies. Wave two builds the declaration and the shared resolvers the
rest depends on. Wave three applies them to the known offenders and closes the trace-loss
and truncation gaps that wave one made safe to close.

## Steps

## Wave `W01` - disarm and verify

Remove the destructive and unverified conditions before any other work increases their likelihood. Delivers a workspace-delete path that refuses to act outside a managed root, and a live determination of whether the desktop edge publishes a service token. Wave two depends on this landing because several of its Steps make artifact persistence more likely, and artifact persistence is what arms the delete path. Backed by the feature ADR and research.

### Phase `W01.P01` - disarm the workspace delete path

Make the hard-thread-delete file removal refuse to act outside a managed root.

- [x] `W01.P01.S01` - Prove the existing workspace containment guard with a test that executes the escape refusal; `src/vaultspec_a2a/control/tests/test_thread_service_artifact_cleanup.py`.
- [x] `W01.P01.S02` - Record the residual risk that a confined delete still removes real files inside the user checkout; `.vault/audit`.

### Phase `W01.P02` - verify the desktop edge live

Determine by an armed run whether the gateway publishes a service token.

- [x] `W01.P02.S03` - Run an armed gateway and record whether the published discovery record carries a handoff reference; `src/vaultspec_a2a/lifecycle/discovery.py`.
- [x] `W01.P02.S04` - Make a tokenless discovery publication fail loudly instead of silently unlinking the credential; `src/vaultspec_a2a/lifecycle/discovery.py`.
- [x] `W01.P02.S23` - Remove the discovery record when the gateway that published it exits; `src/vaultspec_a2a/lifecycle/discovery.py`.

## Wave `W02` - declaration and shared seams

Build the machinery the contract requires: a retention declaration attached to each artifact-creating seam, one audited write-and-rename helper replacing three independent implementations, and a location policy plus teardown verb for the only workspace-creating verb. Wave three applies this machinery to known offenders and cannot begin before it exists. Backed by the feature ADR.

### Phase `W02.P03` - retention declaration

Introduce the declaration every artifact-creating seam must carry.

- [x] `W02.P03.S05` - Define the retention disposition vocabulary and the declaration record type; `src/vaultspec_a2a/artifacts/retention.py`.
- [x] `W02.P03.S06` - Attach a retention declaration to each artifact-creating seam in the lifecycle package; `src/vaultspec_a2a/lifecycle/discovery.py`.
- [x] `W02.P03.S07` - Attach a retention declaration to the worker autospawn stderr log seam; `src/vaultspec_a2a/control/worker_management.py`.
- [x] `W02.P03.S08` - Add a test asserting every declared seam names a disposition and an owner; `src/vaultspec_a2a/artifacts/tests/test_retention.py`.

### Phase `W02.P04` - one atomic write helper

Replace three independent write-and-rename implementations with one audited helper.

- [x] `W02.P04.S09` - Add one audited atomic write-and-rename helper that unlinks its temporary file on every failure path; `src/vaultspec_a2a/lifecycle/atomic_write.py`.
- [x] `W02.P04.S10` - Route the service discovery writer through the shared helper; `src/vaultspec_a2a/lifecycle/discovery.py`.
- [x] `W02.P04.S11` - Route the desktop discovery writer through the shared helper; `src/vaultspec_a2a/lifecycle/discovery.py`.
- [x] `W02.P04.S12` - Route the process registry record writer through the shared helper; `src/vaultspec_a2a/lifecycle/registry.py`.
- [x] `W02.P04.S13` - Add a test that forces a write failure and asserts no temporary file survives; `src/vaultspec_a2a/lifecycle/tests/test_atomic_write.py`.

## Wave `W03` - apply and close gaps

Apply the wave-two machinery to the subsystems the sweep identified, and close the trace-loss and truncation gaps that wave one made safe to close. Delivers preserved agent transcripts, a complete truncation path, a test harness that leaves no residue in the real state home, and ignore-rule coverage for generated artifacts. Backed by the feature ADR and research.

### Phase `W03.P05` - preserve the agent trace

Stop destroying the child session transcript unread.

- [x] `W03.P05.S14` - Export the child session record out of the isolated config home before teardown; `src/vaultspec_a2a/providers/_acp_config_home.py`.
- [x] `W03.P05.S15` - Resolve the isolated config home under the declared desktop temporary homes root; `src/vaultspec_a2a/desktop/profile.py`.
- [x] `W03.P05.S16` - Add a sweeper for orphaned isolated config homes left by a crash; `src/vaultspec_a2a/providers/_acp_config_home.py`.
- [x] `W03.P05.S24` - Call session preservation from the ACP teardown path before the config home is removed; `src/vaultspec_a2a/providers/acp_chat_model.py`.

### Phase `W03.P06` - complete the truncation path

Cover every table and the checkpoint store.

- [x] `W03.P06.S17` - Extend the clear action to cover control actions and permission requests; `src/vaultspec_a2a/control/db.py`.
- [x] `W03.P06.S18` - Extend the clear action to cover task queue entries and thread execution state; `src/vaultspec_a2a/control/db.py`.
- [x] `W03.P06.S19` - Extend the clear action to cover the checkpoint store; `src/vaultspec_a2a/control/db.py`.

### Phase `W03.P07` - harness and hygiene residue

Remove test residue from the real state home and close ignore-rule gaps.

- [x] `W03.P07.S20` - Move service test runtime directory creation out of the dataclass constructor into start; `src/vaultspec_a2a/service_tests/harness.py`.
- [x] `W03.P07.S21` - Add teardown that removes the service test runtime directory after a run; `src/vaultspec_a2a/service_tests/harness.py`.
- [x] `W03.P07.S22` - Add ignore rules for the generated artifacts that currently escape them; `.gitignore`.

## Parallelization

Waves are sequenced and must land in order. Wave one is a hard gate: no Step in wave two or
three may begin until the destructive workspace-delete path is disarmed, because several
later Steps make artifact persistence more likely and that is the condition which arms it.

Within wave one, the live edge verification is independent of the disarm work and may run in
parallel; it requires an armed run and a real host, so it may also block on operator
availability without blocking anything else.

Within wave two, the retention declaration and the shared write-and-rename helper are
independent and may proceed in parallel. The workspace location policy depends on the
declaration existing first, since the policy is expressed in its terms.

Within wave three, the phases are mutually independent and may be parallelized freely; each
applies the wave-two machinery to a different subsystem.

## Verification

The plan is complete when every Step is closed and the following criteria hold.

The destructive path refuses to delete outside a managed root, proven by a test that
exercises the refusal rather than asserting on a predicate. Every artifact-creating seam in
this project carries a retention declaration, and an undeclared seam is detectable rather
than merely discouraged. A single audited write-and-rename helper is the only implementation
in the tree, and it removes its temporary file on a failure path, proven by a test that
forces the failure. Ephemeral working directories resolve under an operating-system
temporary root, so the sibling indexer's existing reclaim can see them without any change to
that project. The truncation path covers every table and the checkpoint store. The test
harness leaves no directory behind in the real state home after a run.

Verification runs on this host include the full touched-area suite rather than scoped runs,
with the exact command and totals recorded in the execution records. The live edge criterion
is the one item that cannot be proven from this repository alone and is satisfied only by an
armed run reporting an authenticated round-trip.
