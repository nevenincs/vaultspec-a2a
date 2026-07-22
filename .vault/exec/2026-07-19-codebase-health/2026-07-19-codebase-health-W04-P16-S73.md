---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S73'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Rewrite service deployment documentation and environment examples to describe the headless runtime

## Scope

- `service/README.md, service/docker/README.md, service/.env.example`

## Description

- Verify the existing documentation against reality before rewriting any of it:
  check that every recipe it names exists, that the ports it publishes match the
  compose files, and that the reference it links to is present.
- Diff every operator-facing setting against the environment example to find
  drift systematically rather than by inspection.
- Document the settings that belong to a service deployment, with their real
  defaults read from the settings model.
- Record the two desktop-profile settings as deliberately excluded, in the file
  itself, so their absence does not read as an omission.
- Pin the whole property with a test so the drift cannot recur silently.

## Outcome

The prose needed no rewrite. The service README already states that the directory
contains no user interface and starts none, every recipe it documents exists in the stack
recipes, the ports it publishes match both compose profiles, and the operator reference it
links to is present. Its only interface mention is the Jaeger trace viewer, which is a
real user interface belonging to a third-party component rather than drift.

The environment example was the part that had drifted, and inspection would not have found
it. A systematic diff against the settings model showed ten explicitly-aliased settings
absent from the file. Eight belong to a service deployment and are now documented with
their real defaults: the state home, the engine-facing gateway credential, request access
logging, the four authoring-subscriber settings, and the worker watchdog cooldown. Two are
desktop-profile only and are now recorded as deliberately excluded.

One of those omissions was load bearing. The authoring subscriber is required for the
document authoring lane, and the live certification lanes skip without it - an operator
following this file had no way to discover the setting exists.

Four tests pin the result: the example exists, every aliased setting is documented or
explicitly excluded, each exclusion is explained in the file, and the exclusion set
contains only settings that really exist so a stale entry cannot mask a genuine gap.

Gates: `ruff check src/` clean, `ty check` clean on the new module, four tests passing.

## Notes

A first pass at the diff synthesized environment names from the settings prefix and
reported thirty-three missing. That was wrong: settings carrying an explicit alias do not
take the prefix, so the list contained names that do not exist. Documenting from it would
have produced an example file describing settings an operator could never set. The check
was narrowed to explicitly-aliased settings only, which is the set with a stable public
name, and the count fell to ten.

The exclusion set is explicit rather than a pattern match on a desktop prefix. A pattern
would silently absorb a future setting that merely looked desktop-shaped; naming the two
makes any addition a visible decision in a diff.

The step's title says rewrite. Nothing was rewritten, because the documentation was
already accurate - verified rather than assumed. Reporting that plainly is more useful
than performing a rewrite to match the wording of a step written before the file was read.
