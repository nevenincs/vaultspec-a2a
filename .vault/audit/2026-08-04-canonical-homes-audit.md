---
tags:
  - '#audit'
  - '#canonical-homes'
date: '2026-08-04'
modified: '2026-08-04'
body_schema: 'body-v1'
body_hash: 'sha256:a50a5006f69c9590e7d15183cc801a9b0e14dc9def54177c740a1c03d60e9bb8'
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

### bounded-wall-clock-poll-loop | high | one loop shape, seven production declarations

No shared helper for "poll a predicate every N seconds until it returns truthy
or a deadline expires" exists anywhere in the tree - verified, there is no
`wait_until`, `poll_until` or `await_until` to import. Seven production sites
therefore hand-roll it, each declaring its own poll interval as a private
constant at a different value: `src/vaultspec_a2a/utils/process.py` waiting for
pids to disappear at 0.1s; `src/vaultspec_a2a/lifecycle/manager.py` three
separate times, for terminate confirmation at 0.05s, for a kill-tree wait at
0.1s and for port readiness at a 0.1s literal;
`src/vaultspec_a2a/lifecycle/singleton.py` acquiring a lock at 0.05s without
jitter; `src/vaultspec_a2a/cli/service.py` waiting for a pid at 0.2s; and
`src/vaultspec_a2a/testing/leases.py` acquiring a lease with jitter. Verdict
DUPLICATE. Changing how this project waits - adding jitter, changing backoff,
adding a diagnostic on expiry - currently means finding and editing seven
loops, which is precisely the burden this audit exists to remove. Two members
must remain separate call sites layered ON the shared primitive rather than
being folded into it: the Windows kill-tree wait bounds a subprocess wait rather
than polling a boolean, and the service harness variant is deliberately
death-aware, watching a child process and raising with its exit code and log
tail.

### progress-deadline-is-not-a-wall-clock-deadline | medium | the one wait that must never be merged

`src/vaultspec_a2a/testing/progress.py` declares a deadline that fails for two
reasons only - the watched resource died, or the observed state stopped changing
for longer than an idle window - and states that elapsed total time is
deliberately NOT a failure reason. It exists because a fixed wall clock is wrong
in both directions for a live model turn: it kills a legitimately slow one and
lets a hung one burn the whole budget. Verdict DISTINCT, recorded here with the
same weight as a defect because the finding above creates the exact pressure
that would destroy it. A consolidation sweep that sees "another waiting helper"
and merges this into the wall-clock primitive removes the only property it was
built for.

### bearer-header-string-template | low | eight sites format the same header inline

Eight production sites build an authorization header by inline string formatting
rather than through a shared one-liner, spanning six genuinely different
credential planes - gateway service token, worker interprocess token, attach
credential, actor token, machine bearer and an external provider key. The
credentials are correctly DISTINCT and must not be unified. Only the mechanical
formatting is duplicated, carrying no decision logic, so the finding is narrow:
a single formatter removes header-casing and format drift and nothing else.
Verdict DUPLICATE on the template alone, lowest priority in this audit.

### swept-and-found-clean | low | four candidate clusters that are not defects

Recorded because an audit that lists only defects cannot be trusted to have
looked. Worker interprocess bearer verification already has one home and states
so; worker health probing already has one primitive, proven by a test asserting
both callers agree on an identical verdict; production retry and backoff sites
are genuinely different failure domains - restart cooldown, subscriber
reconnect, event-flush retry and provider-retry classification - each with its
own settings-driven constants; and HTTP client construction differs for
load-bearing reasons, including one external-provider client that disables
environment trust so proxy variables cannot redirect a provider call, which is a
security property rather than drift. All DISTINCT or already consolidated. One
sub-cluster inside the service harness does repeat five near-identical client
constructions and is worth a local factoring, test-only and low.

### thread-metadata-decode-reimplemented | high | five decoders, five different validations, one live bug

Decoding the thread metadata JSON column and pulling well-known keys out of it
is written five times in production, and each site validates differently.
`src/vaultspec_a2a/database/thread_repository.py` bounds the workspace value and
requires it absolute; `src/vaultspec_a2a/control/message_service.py` requires a
non-empty string; `src/vaultspec_a2a/control/thread_service.py` and
`src/vaultspec_a2a/control/dispatch.py` each catch a different set of decode
errors. `src/vaultspec_a2a/control/permission_service.py` assigns the extracted
value straight to a variable annotated as an optional string with no type check
at all, so a stored value of any other type flows through it unexamined. That is
not cosmetic drift: the sibling that does check carries a comment explaining
that degrading this value used to dispatch the turn anyway and let the provider
layer site the agent, and its filesystem sandbox, in whatever directory the
worker happened to start in. Verdict DUPLICATE, and the convergence target is
the strictest existing behaviour, which makes the fix a bug fix at one site
rather than a behaviour change at the others. This is a hot area - two recent
commits already corrected adjacent handling of an absent workspace - which is
exactly why five decoders is expensive.

### checkpoint-pragma-drift-recurred | high | the helper built to stop this has a third path ignoring it

`src/vaultspec_a2a/database/checkpoint_schema.py` returns the connection posture
every writable checkpoint path must apply, and its docstring states it is kept
in one place so the two checkpoint writers cannot drift from each other the way
they already had once. Both writers call it. A third path does not:
`src/vaultspec_a2a/desktop/migration.py` hand-rolls two pragma statements, hard
codes the busy timeout instead of reading the configured value, and omits the
foreign-key pragma entirely - which the helper documents as per-connection and
therefore required on every connection. So the dashboard-spawned fresh-install
path leaves foreign keys unenforced on the checkpoint store. Verdict DUPLICATE
with nothing to lose on convergence: the helper returns a tuple of statements
and the missing pragma is a fix. This is the strongest single argument in the
audit for the campaign itself - a canonical home already existed, was documented
as existing precisely to prevent recurrence, and a later path still bypassed it,
because nothing enforced the rule.

### test-schema-materialization-not-adopted | medium | a helper built for this suite, used by one package

The root test configuration deliberately provides a schema template and a
materialize step because replaying the schema definition cost the single largest
fixture slice in the suite; the API test package adopted it. Fifteen or more
test files still construct an engine and replay the full schema inline, several
carrying two or three copies within one file, and the database test package -
whose own domain this is - has no shared fixture at all. Verdict DUPLICATE for
every file-backed case, where adoption is a drop-in. One genuine carve-out: the
materialize step copies a file, so in-memory databases cannot use it unchanged
and stay hand-rolled or require the template to grow an in-memory path. Recorded
so the carve-out is not mistaken later for an oversight.

### migration-upgrade-lock-omitted | low | same Alembic call, one path unguarded

The migration module wraps its upgrade-to-head in a process lock and declares
itself the project's one migration-configuration authority; the admin verb
resolves its configuration through that same authority but issues the upgrade
call directly, without the lock. Benign while the admin verb runs standalone,
which is the current assumption rather than an enforced property. Verdict
borderline DUPLICATE, recorded at low confidence and low severity for awareness
rather than as a must-fix.

### persistence-swept-and-found-clean | low | repository and migration homes are single

Reported so the sweep's negative space is visible. Repository create, read and
update functions each have exactly one definition, and the package facade is a
re-export rather than a second declaration. Migration configuration and script
resolution have one home that both the desktop and admin paths call into. The
transaction-commit responsibility is concentrated, with at least one repository
function documenting itself as the only one that commits for its lease. And the
asynchronous engine connect listener and the synchronous admin listener are
deliberately restated because an admin verb needs a synchronous engine that
cannot reuse a pool event - a documented boundary, correctly not unified. All
DISTINCT or already single-homed.

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
