---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:15c2e5d7870f73fb9eac7ea8c44e115a1c1fe7d4206adc039e2fe93c859c4ca8'
step_id: 'S43'
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
     The S43 and 2026-08-02-provider-error-taxonomy-plan placeholders are machine-filled by
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
     The Replace the usage-limit substring sniff with the typed condition and ## Scope

- `src/vaultspec_a2a/service_tests/test_claude_web_grounding_live.py` placeholders below are machine-filled
     by `vaultspec-core vault add exec` from the originating Step row;
     do not fill them by hand. -->

# Replace the usage-limit substring sniff with the typed condition

## Scope

- `src/vaultspec_a2a/service_tests/test_claude_web_grounding_live.py`

## Description

- Replace the three-substring marker tuple with the one typed condition on which
  this module may decline to prove anything.
- Rewrite the classification predicate to read the run's typed condition instead
  of lowercasing and substring-matching its failure reason.
- Capture the condition beside the reason when the observation loop sees the run
  go terminal, reading both from the authoritative run-status response.
- Choose the skip branch by condition, and carry the reason into both messages as
  diagnosis rather than as the deciding value.
- Replace the prose-matching guard test with one that drives the production lane
  mapper on the error shape the installed adapter emits.
- Add a guard enumerating the production vocabulary so exactly one member opens
  the skip, and a guard that an unclassified failure never opens it.
- Restate the module docstring's failure gate and name the distinction this lane
  cannot make.

## Outcome

The repository's only site that classified a provider failure now reads the
classification instead of re-deriving it. The condition was resolved once, at the
lane, from the discriminator the provider itself put on the wire; this consumer
takes that value off run-status, which is where a run's terminal state is
authoritative and the only place a client with no live stream can recover it.

The skip keys on the throttled member and says plainly what it cannot tell. This
lane's adapter assigns one error kind to both a short-term rate refusal and an
exhausted subscription window, branching between them only on a response header
it consumes internally, so the finer usage member would have been a claim the
wire never supported. The skip message reports that the provider refused for
rate and states that the two causes are indistinguishable here, rather than
naming the one it would be more satisfying to report.

The guard that replaced the prose test is stronger than a translation of it. It
does not assert the predicate against a literal chosen in the test, which would
only restate the constant; it drives the production ACP mapper on the wire shape
the installed adapter emits for a rate refusal and asserts the result opens the
skip. A mapping change that moved rate refusals to another member now fails here
instead of silently turning every throttled run into a loud failure. A second
guard enumerates the condition vocabulary from the production enum, so a member
added later lands in the fail-loud half and forces an explicit decision rather
than inheriting a branch.

## Notes

The file was NOT run. It is service-marked, and its live test starts a real
autonomous run against a real provider on the loopback stack, costing credential
and up to an hour of wall clock. It was audited and rewritten by reading.

Its three stack-free guard tests WERE run, by node id with the marker filter
cleared. That is deliberate and is not the live test: the package auto-marks
every test in it as service, but these three request no fixtures, so nothing
starts a stack, spawns a provider, or spends a credential. Verifying the rewrite
by reading alone would have left the replacement predicate unexercised. All three
pass.

A finding that sharpens the reason this Step existed. The old sniff was believed
to survive on its structured marker, the error kind reproduced into the message
string. It no longer does. The reported failure reason is now rendered by the
shared cause-chain renderer, which prefers an exception's own message attribute
over its string form; the ACP error's string form carries the data payload but
its message attribute does not. Driving a real ACP prompt error through the real
wrapper and the real renderer confirms it: of the three markers, the structured
one and one prose marker match nothing at all, and the sniff survived solely on
the phrase in the vendor's English prose. So this campaign's own earlier
cause-preservation work had already reduced the sniff to pure prose matching,
and it would have gone on skipping only for as long as that wording held. The
typed condition for the same failure resolves correctly.

Two conditions that are arguably also absent external resources - a depleted
credit balance and a rejected credential - were deliberately NOT added to the
skip. The Step replaces a classification mechanism; widening what the module
declines to prove is a separate decision, and the three markers removed here all
mapped to the single member retained.

The shared worktree was mid-flight during this Step. Whole-tree lint and type
checks report failures in the API internal test, the streaming ingest module,
and several provider tests, none of them in this Step's surface and all from
concurrent work. The changed file is clean under lint, format, and the type
checker.
