---
tags:
  - '#exec'
  - '#ecosystem-artifact-lifecycle'
date: '2026-08-04'
modified: '2026-08-04'
body_schema: 'body-v1'
body_hash: 'sha256:ba15c23f2c576594560c696cf2c89233ff31b0d65bfeb90f0742d18f301090ab'
step_id: 'S31'
related:
  - "[[2026-07-21-ecosystem-artifact-lifecycle-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace ecosystem-artifact-lifecycle with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S31 and 2026-07-21-ecosystem-artifact-lifecycle-plan placeholders are machine-filled by
     `vaultspec-core vault add exec`; do not fill them by hand.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar-plan]]' and link the
     parent plan.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

<!-- STEP RECORD:
     This file represents one Step from the originating plan. Identified
     by its canonical leaf identifier (S##) and ancestor display path.
     The Ratify the ephemeral thread posture as a decision and record its reversal condition and ## Scope

- `.vault/adr/2026-07-21-ecosystem-artifact-lifecycle-adr.md`
- `src/vaultspec_a2a/providers/codex_chat_model.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Ratify the ephemeral thread posture as a decision and record its reversal condition

## Scope

- `.vault/adr/2026-07-21-ecosystem-artifact-lifecycle-adr.md`
- `src/vaultspec_a2a/providers/codex_chat_model.py`

## Description

<!-- Succinct line-by-line list of steps executed. Use imperative language, mirroring git commit summary lines. -->

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

<!-- Incidents. Data loss. Difficulties; persistent failures. Skipped work. Scaffolds left in code. Failures. -->

Inherited and correct are not the same claim, and the distinction is the point of
this Step. The flag has been present verbatim since the lane's first commit, so
nobody weighed it; ratifying converts an accident that happens to be right into a
decision that can be argued with.

NOT established, and flagged rather than assumed: whether the provider writes
ACTION items into a session record under this project's exact invocation shape.
The observed inventory covered message text and workspace metadata. Anyone
relitigating the posture on observability grounds needs one live turn that
executes a command with the flag disabled, then reads the resulting record.
