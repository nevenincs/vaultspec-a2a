---
tags:
  - '#audit'
  - '#canonical-homes'
date: '2026-08-04'
modified: '2026-08-04'
body_schema: 'body-v1'
body_hash: 'sha256:ed3cf6135b3600dc1a994b2bff82442a260734ae539610e991c48937f51efe32'
related: []
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #audit) and one feature tag.
     Replace canonical-homes with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[yyyy-mm-dd-foo-bar]]'.

     modified: CLI-maintained last-modified stamp; set at scaffold time,
     refreshed by mutating CLI verbs and vault check fix; never hand-edit.

     DO NOT add fields beyond those scaffolded; metadata lives
     only in the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `canonical-homes` audit: `declaration fragmentation inventory`

## Scope

A rolling inventory of every concept in this project that is declared in more
than one place, and of declarations that sit somewhere other than their
concept's home. The aim is operational rather than aesthetic: when a behaviour
must change, there has to be exactly one file to change. A concept spread across
six sites makes that question unanswerable, and the sites drift apart silently
because nothing forces them to agree.

Three verdicts are used throughout, and the middle one is the reason this audit
exists as an inventory rather than a refactor list.

- `DUPLICATE` - one concept, several declarations. Rehome to one, delete the
  rest, update every consumer in the same change.
- `DISTINCT` - similar names, genuinely different concepts. Leave them apart.
  Record where the boundary is and whether it is written down, because an
  undocumented boundary is the one a later sweep destroys.
- `MISPLACED` - a single declaration living away from its concept's home. Not
  duplication, still unfindable.

No compatibility shim, re-export stub, or alias is admissible as a migration
aid. A move deletes the old declaration.

This audit has no fixed end. It is appended as sites surface, and settled
entries are not rewritten.

## Findings

<!-- A rolling log of findings: append one subsection per finding, grouped or ordered by
     severity, using the heading form

       ### declaration fragmentation inventory | {level} | {summary}

     followed by a paragraph carrying the detail. declaration fragmentation inventory is a concise kebab-case slug,
     {level} is the severity (critical, high, medium, low), and {summary} is a one-line
     statement. Append continuously as findings surface; do not rewrite settled entries. -->

### served-catalog-selection-derivation | critical | one concept, six declarations

Deriving a run's provider selection from the served catalog is declared six
times. `src/vaultspec_a2a/cli/main.py` resolves an entry the operator named and
looks up only the revision it is current against;
`src/vaultspec_a2a/service_tests/_provider_catalog_live.py` reads the lane from
environment variables; `src/vaultspec_a2a/desktop_tests/_catalog.py` takes the
first selectable lane and caches per gateway and workspace;
`src/vaultspec_a2a/api/tests/conftest.py` takes the first selectable lane and
caches per workspace; `src/vaultspec_a2a/acceptance/_harness.py` prefers the
in-process lane and falls back to the first selectable one. A sixth site,
`src/vaultspec_a2a/service_tests/harness.py`, needs the concept and does not
have it at all. Verdict is DUPLICATE on the mechanism only. The flattening risk
is severe and specific: operator-named, environment-named, first-selectable and
in-process-first are four different POLICIES about which lane a run executes on,
and a canonical helper that quietly picks one would hand a test a lane its
author never chose. Consolidate the mechanism - read the catalog served for a
workspace, validate the reference, cache it - and keep the policy an explicit
argument at each call site. The production resolver states the discipline the
consolidated mechanism must inherit: it never ranks entries, never reads a
display name as a quality or price signal, and never falls back to the first
one.

### service-harness-cannot-start-a-run | high | the shared harness omits two required fields

`src/vaultspec_a2a/service_tests/harness.py` builds its run-start body from a
message, a preset and three optional fields. The request schema requires a
selection and a run identifier and forbids extra keys, so every body it posts is
refused at validation. Eleven call sites across five service test files inherit
this. The lane is gated behind a marker and a live stack, so nothing observed
it. This is the absence half of the finding above: the concept has no canonical
home to import, so the one caller that needed it went without. Severity is
against the coverage lost rather than a running regression - no lane was
executing.

### port-acquisition-split-across-modules | medium | canonical home exists, one member lives elsewhere

`src/vaultspec_a2a/testing/ports.py` already declares itself the one canonical
way a test acquires a port to bind, and deliberately carves out a second
concept: an ephemeral probe that hands out no claim and must never be used to
obtain a port a test will bind. That boundary is documented and correct. The
defect is address, not duplication - the probe concept is implemented in
`src/vaultspec_a2a/tests/gateway_boot.py`, away from the sibling it is defined
against. Verdict MISPLACED. This entry is also the calibration case for the
whole audit: it is what a real distinction looks like, and merging the two would
be worse than leaving them apart.

### distinct-pairs-to-protect | medium | four near-identical names that must not be merged

Recorded so a later sweep does not destroy them. Two session-factory accessors
in `src/vaultspec_a2a/database/session.py` differ in that one manufactures an
engine from ambient settings when none exists and the other reports whether the
process has one, returning nothing when it does not; collapsing them
reintroduces a durable write against an invented database. Two digest rules in
`src/vaultspec_a2a/api/run_admission.py` are computed over different exclusion
sets, and the module states they are deliberately not harmonised. The
bind-claiming and no-listener port concepts described above. And the distinction
between a message safe to return to a client over HTTP and one safe to write to
a local operator log, which several modules keep apart because provider text can
carry a credential, a URL or a local path. Each is DISTINCT.

### suspected-domains-under-sweep | low | breadth not yet established

Five semantic sweeps are in flight over domains no one has audited for
duplicate declaration: process lifecycle and subprocess control; HTTP client
construction, bearer verification and timing policy; persistence, session
handling and schema materialization; validation, bounded value types, digests
and identity minting; and observability, log shaping and event normalization.
Two clusters already surfaced by hand and not yet triaged are gateway boot with
wait-until-healthy, declared in at least four places, and credential seeding
into an application home, declared in at least five. This entry is a placeholder
for that breadth and will be replaced by specific findings, not amended.

## Recommendations

<!-- Actionable recommendations, each tied to a finding above. An
     architecturally significant recommendation names the decision a
     follow-on ADR must make; the decision itself is never recorded here. -->

Rehome each DUPLICATE cluster to a single declaration and update every consumer
in the same change, deleting the old declaration rather than aliasing it. Commit
one cluster at a time: a batched rehoming cannot be partially reverted when one
member turns out to have been DISTINCT.

Close the harness omission by consuming the consolidated selection mechanism
rather than by adding a seventh derivation beside it. Sequence it before the
consolidation, because it unblocks eleven dark call sites and because it is the
consumer that proves the mechanism serves a caller who has no policy opinion.

Move the no-listener port probe beside the bind-claiming acquisition it is
defined against, and keep the two concepts separate in their shared home. The
existing prose stating why they differ moves with them; a boundary that is not
written down where both live is the one a later sweep destroys.

Verify each rehoming by running the suites of BOTH the old and the new location.
A rehoming proven only at its new home has not proven its consumers, and a
whole-tree type check rather than a file-scoped one is what surfaces an import
that was missed.

Two decisions are deferred to a follow-on record rather than settled here. The
first is where a mechanism shared by production and test callers belongs, raised
concretely by the catalog-selection cluster: the production resolver and the
consolidated test mechanism may converge on the same code, and admitting
test-support code onto a production import path is not a call this inventory
makes. The second is whether the canonical-home rule is promoted to a
team-shared rule source, which would make it enforceable rather than
conventional.
