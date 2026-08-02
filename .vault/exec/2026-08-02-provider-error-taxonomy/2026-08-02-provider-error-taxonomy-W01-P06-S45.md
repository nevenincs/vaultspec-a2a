---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:ee989cba69296ae3d38364441e33db826a7eed6b8ad29bee8ec9cf4d54a239da'
step_id: 'S45'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #exec) and one feature tag.
     Replace provider-error-taxonomy with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     step_id is the originating Step's canonical identifier, e.g. S01.
     The S45 and 2026-08-02-provider-error-taxonomy-plan placeholders are machine-filled by
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
     The Prove a live provider failure surfaces a typed condition end to end and ## Scope

- `src/vaultspec_a2a/service_tests/test_provider_condition_live.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Prove a live provider failure surfaces a typed condition end to end

## Scope

- `src/vaultspec_a2a/service_tests/test_provider_condition_live.py`

## Description

- Establish empirically that the prescribed rejected-credential provocation does
  not lift from a directly constructed model to a run started through the gateway.
- Add the end-to-end live proof module, asserting the condition on the run-status
  response with no stream attached.
- Build the run's catalog selection from the catalog the gateway actually serves,
  so the request satisfies the current run-creation schema.
- Make the provocation a declared parameter rather than a constant, and make that
  declaration the consent to spend a real credential.
- Add four stack-free guards covering the declaration parser and the selection
  builder.

## Outcome

The module is WRITTEN and its live assertion is UNRUN. No loopback stack is
reachable from this session, so the chain is code-complete and unproven. That is
reported here rather than papered over: an unrun proof is not a proof.

The live path was not merely unexercised for want of a stack. The provocation the
Step was expected to use does not work through the gateway, and establishing that
is the substantive result. Swapping in a deliberately invalid bearer is the proven
recipe at the MODEL level because a directly constructed model never consults the
provider catalog. A run started through the gateway does. Catalog discovery on
this lane opens a real session against the provider, so an invalid credential
yields an unavailable catalog carrying no entries, the lane is not selectable, and
a run cannot even be created - the required selection names a catalog revision and
an entry id that do not exist. The run is refused BEFORE admission. That refusal
is correct behaviour and is emphatically NOT a provider condition, so the
provocation cannot prove the chain no matter how long it is left running.

The module is therefore built so the provocation is declared rather than assumed.
An operator arms the stack for a refusal the credential SURVIVES - a genuinely
throttled or exhausted account, or a transport severed after discovery - and names
the condition to expect; the module proves that condition reached run-status. This
keeps the proof drivable when any one provocation is out of reach, and it asserts
the campaign's actual claim, which is about the chain rather than about a
particular member of the vocabulary.

The assertion surface is the run-status response with no stream attached, which is
the point of the Step. The frame carrying the condition is droppable, so a value
observed only there would prove the channel a reloading client cannot depend on.

## Notes

STATE: written, unrun. The exact command is recorded in the module's own header.
It requires a serving loopback stack and an armed lane, and the arming variable
must name a condition that lane will really produce.

Four stack-free guards WERE run and pass. They cover the declaration parser -
including that a misspelled condition fails loud rather than degrading into a
silent skip, which is how a proof comes to be reported as merely unavailable
forever - and the selection builder, including that the body it assembles
validates against the production run-selection model. That last guard matters
because run creation gained required identity and selection fields during this
campaign, and a request assembled from constants would now be refused.

The arming variable is deliberately also the consent to spend a credential.
Without it the module never starts a run, so pointing the default suite at a
healthy stack cannot burn quota and cannot report a confusing failure for a run
that simply succeeded.

A live gateway was found running during this Step, but it belongs to another
agent's workspace and its engine was not reachable. It was left alone. Driving a
provider refusal through it would have required rebooting its worker with a broken
credential, which would have disrupted concurrent work for a proof that, per the
finding above, that provocation cannot deliver anyway.

Two consequences for the campaign are worth stating plainly. This module remains
the ONLY surface that can exercise a typed condition end to end, because
conditions are resolved only at the served-lane raise sites and no in-process lane
produces one. And until it is driven against an armed stack, the wave is
code-complete rather than proven.
