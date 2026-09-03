---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-08-04'
modified: '2026-09-03'
body_schema: 'body-v1'
body_hash: 'sha256:08c784fbb6dce7a3f11058d84f05dfa5aa0323bc47d057597e3d811c72b05c42'
step_id: 'S31'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

# Ratify the ephemeral thread posture as a decision and record its reversal condition

## Scope

- `.vault/adr/2026-07-21-ecosystem-artifact-lifecycle-adr.md`
- `src/vaultspec_a2a/providers/codex_chat_model.py`

## Description

- Establish that the ephemeral thread posture is inherited rather than chosen,
  by tracing it to the lane's first commit.
- Ratify it as a decision inside the amended layer, with the grounds stated.
- Record a narrow reversal condition so the ratification is falsifiable rather
  than permanent.

## Outcome

The posture is CORRECT and is now stated as a decision. Three grounds, each
checkable:

The resume half of the tradeoff is worth nothing by construction. The lane opens
one server, one thread, and one turn per generation, so provider-native
continuity has no caller; continuity is owned by this project's checkpoints, and
the usage accounting leans on the one-thread-one-turn shape.

Enabling session records would RECREATE the defect this layer was written to fix.
The record would land in the per-run configuration directory that also holds a
copied credential and is removed by the same teardown - destroyed unread,
literally. Making it durable would require an export-before-teardown step, and
that machinery was deleted when the sibling lane moved to the operator's home.

The content would mostly be a second copy. Full message text is already at rest
in the checkpoint store and served with a truthful availability; a session record
would add workspace and repository metadata in a provider's format, under a
second retention regime - which is this record's own named disease.

The reversal condition is deliberately narrow: the posture changes only if this
project adopts provider-native session continuity, or a compliance obligation
demands provider-native records, and then only together with an export into the
accounted state root and a retention declaration. Never bare.

## Notes

Inherited and correct are not the same claim, and the distinction is the point of
this Step. The flag has been present verbatim since the lane's first commit, so
nobody weighed it; ratifying converts an accident that happens to be right into a
decision that can be argued with.

NOT established, and flagged rather than assumed: whether the provider writes
ACTION items into a session record under this project's exact invocation shape.
The observed inventory covered message text and workspace metadata. Anyone
relitigating the posture on observability grounds needs one live turn that
executes a command with the flag disabled, then reads the resulting record.
