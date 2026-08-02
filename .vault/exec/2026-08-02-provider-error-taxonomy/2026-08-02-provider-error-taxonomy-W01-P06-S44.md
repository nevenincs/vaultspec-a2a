---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:9b78e3393acdff369a8dfa9355b7c9fb0b3e294adb3450d6436e208adf8f249c'
step_id: 'S44'
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
     The S44 and 2026-08-02-provider-error-taxonomy-plan placeholders are machine-filled by
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
     The Add a scripted failure scenario preset for the integration-verification ask and ## Scope

- `src/vaultspec_a2a/team/presets/teams` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Add a scripted failure scenario preset for the integration-verification ask

## Scope

- `src/vaultspec_a2a/team/presets/teams`

## Description

- Probe the existing scenario presets to establish what the tree already
  delivers before adding anything.
- Add the `deterministic-failure` team preset: a two-stage pipeline on the
  in-process deterministic lane whose graph recursion budget is deliberately
  smaller than the topology needs.
- Add a test module that drives the shipped preset through the real compile and
  invoke path and asserts the run raises rather than completes.
- Assert the failure is preceded by a real completed model turn, and that the
  turn was served in process.
- Assert the preset's served description claims no provider condition.

## Outcome

The scenario produces a real terminal failure through the real graph. Compiling
the shipped preset and invoking it raises the graph's own recursion error; the
run is not narrating a failure it did not have. It needs no credential, no
network, and no tape server, so it behaves the same on an unarmed host as on a
provisioned one.

The scenario was shaped so the run does visible work first. One worker turn
completes and streams real content before the budget is exhausted, which is what
makes it useful for driving a consumer: a client sees a working run that then
fails, rather than a run that dies before anything happens.

The failure is a GRAPH BUDGET failure and reports the recursion-limit code. It
is deliberately NOT presented as a provider failure. No in-process lane can
refuse work the way a real provider does, so no unarmed preset can produce a
provider condition, and the served description says so in as many words rather
than implying a precision the lane lacks. A test asserts that wording, because
the description is what a client is shown.

## Notes

A finding worth carrying forward: the existing tool-failure scenario preset does
NOT fail. Driven through the real graph it COMPLETES successfully, its model
merely emitting the sentence "The command failed as expected. Investigation
complete." while its served description advertises "a team that finished running
with a failure involving tool calling errors". That is a served claim the preset
cannot honour, and it is the reason this Step exists. It was left in place rather
than removed, because deciding its fate is outside this Step's scope, and it is
recorded here so it is not mistaken for coverage of the failure scenario.

A second finding from the same probe: the mock lane is admitted as an in-process
lane but proxies the in-repo tape server, which was found listening during this
work. A scenario on that lane therefore needs a service running and is not
credential-free in the way the admission grouping suggests. The new preset's lane
assertion names the deterministic lane specifically rather than accepting either
in-process lane, because the weaker assertion would have passed for a preset that
silently required a server.

The unarmed claim is empirical rather than declared. The streamed turn's content
is compared against what the in-process provider itself produces for that role,
asked for directly through its public interface, so the assertion shows the turn
was served in process rather than by the tape server that happened to be running
on this machine. The expectation is derived from the production model rather than
pasted from an observed run.

The failure assertions were checked for the obvious way they could be vacuous: at
the default recursion budget the same run COMPLETES, so a later edit that raises
the limit turns these tests red instead of leaving a scenario that passes while
proving nothing.

A pre-existing unresolved-reference type error in the API package's internal test
and an import-sorting lint error in the testing package appeared during this work,
both from concurrent edits in this shared worktree. Neither is in this Step's
surface and both were left alone.
