---
tags:
  - '#adr'
  - '#production-boundary'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:872cd29881340e8401402813dbb98b7f34177c7274f71fcd84e45bd0ea2bdf89'
related:
  - '[[2026-08-03-production-boundary-audit]]'
---

# `production-boundary` adr: `refusing a run that carries no active project` | (**status:** `accepted`)

## Problem Statement

Every run this service executes belongs to a project, and the caller that owns
that project supplies it: the dashboard engine derives the workspace from its
own active scope cell on the start, prepare, commit, and release stages alike,
and explicitly accepts nothing browser-supplied. Beneath that, however, the
metadata envelope carrying the project was optional at every layer, and its
absence was never refused. The null propagated into the provider factory, where
ten fallbacks resolved it to whatever directory the serving process had been
started in.

A decision is needed now because the consequence is not merely that agents ran
in the wrong folder. The agent filesystem and terminal sandbox roots derive from
the same value, so an unsited run confined its agent to - and therefore
permitted it within - this service's own tree.

## Considerations

The active project is already mandatory in practice: the producing caller sends
it on every stage, and the field on the metadata model is required and validated
as an existing directory once the envelope is present.

The start path's current protection is accidental. A mandatory
provider-selection freeze happens to refuse a null workspace, reporting it as a
provider-selection error. That invariant is owned by the wrong gate under the
wrong name, and it evaporates if selection ever becomes optional.

The follow-up message path has no protection whatsoever: it degrades a missing
or unreadable stored workspace to null through a bare exception handler and
dispatches the turn anyway.

The middle link of the fallback chains is dead. The factory constructs every
chat model with a workspace root and never sets the intermediate working
directory field, so each three-way chain already reduced to two.

A sandbox root is a security boundary. Deriving one from ambient process state
means the boundary is whatever the launcher happened to choose.

## Considered options

**Refuse at the run-creation seam.** Enforce the requirement where a run becomes
durable, beside the existing invalid-directory refusal, and remove every
fallback beneath it. Costs one new refusal path and the rewriting of tests that
leaned on the ambient default. Chosen.

**Require the metadata envelope in the request schema.** Rejected: the field
serves four stages, and the prepare stage legitimately resolves bundled presets
without a workspace while creating no durable run, so a schema-wide requirement
changes the prepare shape for no gain.

**Refuse only in the provider layer.** Rejected as too late. The run would be
admitted, persisted, and dispatched before failing, burning admission capacity
and producing a mid-run failure instead of a clean client error.

**Keep the status quo.** Rejected. The only protection on the start path is an
incidental side effect of an unrelated gate under a misleading error, there is
no protection at all on the follow-up path, and the ambient sandbox hazard sits
beneath both.

## Constraints

The wire contract must not change: the producing caller already satisfies the
requirement on every stage, so tightening the schema would impose a migration
for an invariant that is already met.

The prepare and release stages create no durable run and must keep working
without a workspace.

The repository-root setting retains a legitimate role resolving this service's
own installed assets, and must not be conflated with agent siting.

## Implementation

The refusal lives at one seam. The metadata processor raises when the envelope
is absent, exactly beside its existing invalid-directory refusal, and the
gateway's existing exception mapping surfaces it as an unprocessable-entity
response. Both the one-shot start and the prepared commit share this seam
through the common run-creation core.

The follow-up path applies the same rule under its own typed failure, mapped to
the same status at the route so one invariant reads identically at both entry
points.

Beneath the seam the workspace root becomes a hard requirement, expressed once
as a shared helper that refuses rather than invents. The dead working-directory
field is deleted from both chat models and the runtime configuration. The spawn
directory, the environment resolution root, the session working directory, and
the filesystem and terminal sandbox roots all take the required value. Catalog
discovery requires an explicit root as well, which is a type-level tightening
only, since every production catalog call already arrives through the
workspace-scoped service behind an existing-directory check.

## Rationale

Enforcing the requirement where runs become durable, rather than where requests
are parsed, keeps the four-stage verb's shape while making the invariant real.
The producing caller already sends the value on every stage, so the refusal
enforces a contract that is met in practice and closes the path for any caller
that is not the engine.

Putting the rule in one named seam replaces an invariant that was borrowed from
the selection gate and reported under the wrong name. The type system stops
advertising an optionality the production system never intends, and the sandbox
roots stop deriving from ambient process state.

## Consequences

Good: an unsited run can no longer execute - silently or otherwise - in this
service's own tree or the worker's working directory, closing both the
wrong-siting defect and the sharper hazard that agent filesystem and terminal
sandboxes rooted themselves in the service's own tree. The invariant is owned by
a named seam with an honest error. The producing caller is unaffected on every
stage; no wire contract changes.

Bad: threads persisted without a workspace root lose follow-up capability and
must be re-started rather than migrated. The stale command-line run-start verb
remains broken for its own reasons - it already omits the required run identity
and selection fields - and now has one more requirement to meet when repaired.
Tests that leaned on the ambient fallback, or on the dead working-directory
field, were rewritten against explicit workspace roots.

Neutral: the worker's resume-after-restart path shifts from silently re-siting a
resumed run to failing loudly when no workspace root is recoverable; the
existing kill-and-restart drill should be re-run to confirm the recovery path
always carries the workspace root. Prepare-stage behaviour is unchanged.
