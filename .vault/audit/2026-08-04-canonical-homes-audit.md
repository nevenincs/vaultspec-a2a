---
tags:
  - '#audit'
  - '#canonical-homes'
date: '2026-08-04'
modified: '2026-08-04'
body_schema: 'body-v1'
body_hash: 'sha256:fb5bdf7784ca820544b17cc1f08036148b33c95ea2cf1c39639cffed029cdbf8'
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

### correction-port-probe-was-a-reservation | medium | an earlier entry in this audit was wrong

The port-acquisition entry above described the moved declaration as the
ephemeral no-listener probe living in the wrong module. That is incorrect and is
corrected here rather than edited away, because a wrong finding that silently
disappears teaches nobody. The declaration is reservation-FIRST: it takes an
exclusive scratch-band claim, holds it for the whole process lifetime, and runs
a daemon thread heartbeating the marker so the hold outlives the reservation
expiry. The unclaimed operating-system probe is only its fallback for a missing
or exhausted band. It therefore sits on the reservation side of the boundary the
canonical module documents, not the probe side, and the correct outcome is three
concepts kept apart in one home - a claim scoped to a block, a claim held for
the process, and an unclaimed probe documented as a fallback rather than a peer.
The verdict MISPLACED stands; the reason it was misplaced does not. The decisive
evidence was not the semantic sweep at all: the tests for the concept already
lived beside the canonical module while the implementation lived a tier away in
a gateway-boot module, importing two of its privates upward, and sixteen of its
seventeen consumers have nothing to do with booting a gateway. A test reaching
up a tier for two private names is the concrete form of nobody being able to
find where a thing lives.

### untyped-json-narrowing-restated | high | one narrowing, four names, ten production modules

Narrowing an untyped value into a string-keyed object is declared as a fresh
validator singleton in ten production modules under four different private
names, across the control, api, worker and authoring layers. The only real
variance is that two sites validate strictly and the rest do not, which is
itself the drift: there is no single place to add a size cap, a schema-version
check, or a consistent strictness policy at the untyped boundary. Verdict
DUPLICATE. Two adjacent sites in the provider layer use a tighter recursive
closed-JSON type rather than an arbitrary object and are the direction to
converge toward, not to flatten into the looser form - collapsing them would
silently loosen validation at those two call sites. The canonical export must
offer both a lenient and a strict form rather than picking one silently. Note
the layering question this raises: the natural home is the module that already
owns the closed-JSON shape, in the provider layer, and whether control and
worker modules may import from there is a facade question to settle before the
home is fixed.

### bounded-text-aliases-restated-inline | high | thirteen fields restate numbers a sibling already exports

The provider-catalog schema module declares four reusable bounded-string
aliases. Its sibling in the same package imports other symbols from it but not
these, and instead restates the identical numeric bounds inline at roughly
thirteen field sites - the same 1024 and 256 caps, field for field, on the
frozen execution-authority disclosure types. Verdict DUPLICATE, and the drift
risk is already live rather than introduced by consolidating: a cap changed for
a provider-catalog reason leaves the thirteen restatements silently at the old
value. One thing must be checked before any mechanical swap - two of the aliases
also carry a control-character exclusion pattern that the bare inline
restatements do not enforce, so adopting them tightens validation. That is
probably desirable and is certainly a behaviour change, so it belongs in the
implementing step as an explicit decision rather than a side effect. A separate
constant in the same file is deliberately restated as a cross-repository
contract number that a consumer in another repository cannot import, and is
documented and tested as such; it is DISTINCT and must not be swept up with the
rest.

### admission-state-name-collision | low | one name, two unrelated vocabularies

A state enumeration name is declared twice with entirely different vocabularies:
one describing whether a gateway is admitting or draining, the other describing
whether a provider lane has completed-turn admission evidence. No file imports
both today, so there is no live shadowing defect. Recorded because both live in
domains likely to grow a shared consumer, and because a reviewer reading a diff
that imports the name has even odds of assuming the wrong vocabulary. Verdict
DISTINCT with a naming hazard; no rename proposed here.

### identity-swept-and-found-clean | low | canonicalization, redaction and id shapes are single-homed

The workspace canonicalizer has one home, and the engine-facing scope token
builds on top of it for a documented and genuinely different wire spelling
rather than re-deriving it. Run, reservation and lease identifiers are three
aliases deliberately sharing one regular expression declared once. Credential
handling is three correctly separated concepts with no duplicate copies: a
pattern-scanning redactor for free-text diagnostics, a two-field mask in a
representation method, and the environment scrub that removes credentials before
a subprocess spawn. All DISTINCT or already single-homed.

### process-tree-kill-declared-twice | high | two independent implementations of one escalation

Killing a process and its whole tree is implemented twice, independently, with
the same algorithm: force-kill the tree on Windows, and on POSIX snapshot the
descendants before signalling - because killing the root first severs the parent
links the walk needs - then escalate through terminate and kill across the root
and that snapshot. One is asynchronous in `src/vaultspec_a2a/utils/process.py`
and its own docstring calls itself the single such escalation. The other is a
synchronous twin in `src/vaultspec_a2a/lifecycle/manager.py`. Roughly seventy
lines are duplicated, and each has a substantial independent consumer set -
worker management, provider subprocesses and the desktop suites on one side, the
service CLI, the service harness and the lifecycle suites on the other. Verdict
DUPLICATE, highest burden in this domain. There is no structural obstacle to
collapsing the synchronous twin onto the asynchronous one: the gateway boot
helper already calls the asynchronous version from synchronous code, which is
live proof the wrapper works rather than a proposal that it might.

### detached-spawn-flags-triplicated | medium | one flag decision, three hand-rolled copies

Choosing the platform flags that detach a spawned child - a new process group on
Windows, a new session on POSIX - has a canonical home on the containment type
in `src/vaultspec_a2a/utils/process.py`, correctly used by the provider
subprocess path and partly by worker management. Two further sites hand-roll the
identical branch instead: the lifecycle manager's spawn, and the service test
harness. Milder than the finding above because neither of those two wires
containment teardown, killing by pid instead, so only the flag selection is
duplicated. Verdict MISPLACED for the two copies; a narrow exported accessor for
the flags is enough.

### correction-gateway-boot-is-three-probes | medium | an earlier count in this audit was wrong

An earlier entry listed gateway boot with wait-until-healthy as declared in at
least four places. That count is wrong and is corrected here. There are three
declaring probes and one consumer, and the three ask genuinely different
questions of different callers: a bare health endpoint returning exactly two
hundred, death-aware through the child handle; a discovery-record freshness
check used by the service CLI because a Windows launcher stub makes the spawned
pid untrustworthy; and an aggregate multi-subsystem readiness contract in the
service harness covering worker connection, database, checkpoint and circuit
breaker together. The fourth site is not a declaration at all - the acceptance
harness imports the first one and its module docstring says the lifecycle
primitives live one tier down and are shared by every real-process tier. Verdict
DISTINCT on probe content. Only the loop SHAPE these three sit inside is
duplicated, and that is already recorded as the wall-clock poll cluster.

### correction-credential-seeding-count | low | three sites, and one is distinct by design

An earlier entry put credential seeding into an application home at five or more
sites. Three declaring sites are confirmed. The canonical one writes both
credentials and hardens the file, and has twelve consumers across the
acceptance, service and desktop suites. One reimplementation writes only the
attach credential and bundles a discovery-record write, a partial duplicate at a
single site and low value to rehome. The third deliberately writes an UNHARDENED
file, because the tests it serves exist to prove the loader fails closed on a
file whose permissions are wrong - merging it would destroy the property it was
written to demonstrate. Verdict DUPLICATE for the second, DISTINCT for the
third. The remaining count beyond these three is unconfirmed and should not be
asserted without a sweep that owns the credential domain.

### a-brief-that-carries-an-error-returns-it | medium | method finding, not a code finding

Recorded because it affects how much any entry here can be trusted. This
audit's original port-acquisition entry mischaracterised the moved declaration.
That wrong claim was then included in a discovery brief as context, and the
sweep returned it as an independent confirmation of the same mischaracterisation
- while the lane that actually READ the implementation and moved it reported the
opposite, correctly. Two sources agreed and the majority was wrong, because one
of them was quoting the audit rather than the code. The practice this fixes:
briefs carry the QUESTION and the protected distinctions, never a provisional
verdict; and a confirmation that arrives without a citation into the source is
not corroboration. The corrected reading was settled by reading the declaration
at HEAD, which states plainly that the reservation is the primary path and the
unclaimed probe only a fallback.

### terminal-status-vocabulary-declared-three-times | high | agreement by upkeep, not by construction

Which statuses mean a run stopped running is hand-declared three times. The
durable lifecycle authority in `src/vaultspec_a2a/thread/enums.py` holds the
frozen set every production consumer correctly imports. A second declaration in
`src/vaultspec_a2a/thread/snapshots.py` builds an identity map of the same three
strings, typed out again rather than derived from the first, and a third literal
appears in that module's own test, asserted against the second rather than
against the authority. No test anywhere compares the map's membership to the
authority's. They agree today by coincidence of upkeep. The consequence is
specific: the terminal handler documents itself as the run's primary release
site, where a run leaves the drain gate's active set and receives its durable
status write, and that path gates on the SECOND declaration. Add a terminal
status to the authority, miss the map, and a genuinely terminal run silently
fails to release its slot and skips its durable write - and this project has
precedent for growing closed vocabularies additively. Verdict DUPLICATE on the
vocabulary, not on the container: the map does real second work coercing an
untyped wire value, so it stays a map, but its membership must be derived from
the authority and the test must compare against the authority rather than a
fourth literal.

### first-selectable-lane-is-a-billable-footgun | high | a naive consolidation would spend money

Measured under the service harness's own posture: with in-process lanes unarmed,
seven lanes are served and exactly one is selectable - and on a developer box
that one is a real, billable provider, because the box happens to hold a live
session for it. In a credential-less stack the same posture yields zero
selectable lanes, so the runs are unstartable rather than merely misrouted. This
turns the "take the first selectable lane" policy from a stylistic choice into a
hazard: consolidating the six derivation helpers onto it would quietly point
mock tape-replay certification traffic at a paid lane. It is the sharpest
argument for the constraint already recorded on that cluster - consolidate the
mechanism, keep the policy explicit at each call site - and the right shape for
a test-side policy is to REFUSE anything but an in-process lane and raise naming
the missing environment declaration, rather than falling through to whatever the
catalog happened to serve. Related and equally load-bearing: a lane must be
chosen from what a preset is pinned to rather than from what its name suggests,
because a mock preset answered by the deterministic lane stops replaying its
tape while still reporting success - a substitution that looks green and tests
nothing.

### service-harness-dark-for-four-reasons | high | supersedes the two-field finding above

The earlier entry recorded the shared harness as missing a selection and a run
identifier. Two further causes are confirmed, both invisible until the first two
clear. Nine of its eleven call sites pass no metadata envelope at all, and the
thread service refuses a run whose active project is absent rather than
inferring one from the serving process. And the harness arms no in-process lane,
so its gateway serves nothing it may legitimately select. A fifth cause blocks
verification of all four: the versioned router carries an attach dependency on
every route, and the harness attaches its credential to the worker client only,
so every gateway call is refused before any body is examined. Dating: the run
identifier requirement and the attach gate both landed on 2026-07-19 and predate
the catalog campaign entirely, so this is not that campaign's doing. Same
classification as the acceptance lane - broken-on-arm, not broken-now.

### catalog-discovery-output-budget-triplicated | medium | three copies of a stderr meter

Metering a discovery subprocess's standard error volume and killing its tree on
overflow is implemented three times, once in each provider catalog module, with
the bodies identical apart from the exception type caught. Verdict DUPLICATE.
Surfaced by the observability sweep but belonging to the provider catalog lane,
recorded here so it is not lost between domains.

### terminal-status-in-service-tests | medium | two byte-identical copies with a phantom member

Two service test modules each declare the same terminal-status set and the same
polling stack - server base, listening probe, await-terminal loop and readiness
budget - byte for byte. Both sets include a member that is not a status value
anywhere in production, so the drift is not hypothetical, it is already present.
Verdict DUPLICATE, test-only blast radius, and the canonical set must be derived
from the lifecycle authority rather than retyped.

### observability-swept-and-found-clean | low | one home each, and one protection

Logging configuration, the JSON formatter, the correlation filter, telemetry
provider setup, event debouncing and the progress frame encoder each have
exactly one home, with the frame encoder additionally guarded by a closed
allowlist proven by a test that plants secrets and asserts they never cross the
encode boundary. The structured log-context builders are DISTINCT field
vocabularies correctly kept apart - merging them would leak dispatch fields into
provider logs - though the drop-empty-values idiom inside them is written out
three times and is worth one small helper. Most importantly the safe-to-log and
safe-to-return boundary was traced through actual data flow rather than by name,
and no site confuses them: provider standard error is scrubbed at CAPTURE time,
before it is retained or embedded in an error, so by the time the
client-visible renderer sees it the credential-shaped substrings are already
masked, while the local-only debug path may log raw text because its rule
differs. That renderer is deliberately non-recursive and prefers a structured
message precisely because stringifying an exception can fold in a wrapped cause
or a vendor payload - a protection a naive "just stringify it" consolidation
would undo.

### correction-selection-cluster-is-eleven-sites | critical | supersedes the six-site count and its framing

The opening entry counted six derivations and described four competing policies.
Both are wrong and are corrected here. There are about eleven sites across nine
files that actually read a served catalog and pick an entry, found with a sharp
discriminator - who READS and PICKS - rather than who mentions the vocabulary.
Four were on nobody's list, including a second derivation inside the same API
test configuration file that already held one. Two were created during this
campaign by the lane now fixing them, which is recorded because a campaign that
adds to the fragmentation it is removing needs to say so.

The framing correction matters more than the count. There are not four policies;
there are two orthogonal axes - a candidate filter (any selectable, in-process
only, operator-named) and an entry choice (first advertised, or operator-named).
"First selectable" and "in-process first" are the same policy under different
filters. So the mechanism can be one function taking both axes as explicit
arguments, and no call site loses a distinction. Consolidation is more feasible
than the earlier entry assumed, not less.

And the decisive finding: TEN of the eleven sites take the first advertised
entry, which is precisely what the production resolver refuses by name - it never
ranks entries, never reads a display name as a price signal, and never falls back
to the first one, because a run's artifacts are produced by what the caller
chose. So the test-side derivation that reads its lane from operator-supplied
values is not one of several equals; it is the only one already obeying the
production rule, and the other ten are one defect repeated. This reframes the
work from deduplication to raising ten sites to a discipline production already
states. Preserving "first selectable" as a co-equal policy would have enshrined
the defect. The agreed constraint: first-advertised-entry is legal ONLY together
with an in-process-only filter, where the billing and provenance concern does not
apply; any external lane must name its entry. That makes the dangerous
combination inexpressible rather than discouraged.

### credential-seeding-final-inventory | medium | four declaring sites, one protected negative

Supersedes both earlier counts. One production writer mints the worker
interprocess secret per gateway boot and is the only credential this repository
writes at all - attach and ownership are created outside it. One canonical test
fixture writes and hardens the pair in a single call and has twelve consumers
across the acceptance, service and desktop suites. Two narrow single-site
duplicates exist: one writes only the attach half and bundles a discovery-record
write, the other reimplements the fixture's per-file write-and-harden step
locally so a test can seed each plane independently. Both are DUPLICATE, and the
second suggests the fixture's inner single-file step should be extractable so
both can call it. The protected negative is precise: inline unhardened writes at
two places exist to prove the loader fails closed on a file whose permissions are
wrong and on a reparse point. Routing them through any hardening helper destroys
the property under test. Application-home layout is separately clean - one
authority for state paths, one for credential subpaths, consumed consistently.

### three-clock-domains-must-not-merge | medium | heartbeat staleness is declared three times, all DISTINCT

Recorded as a protection because the names invite exactly the wrong merge. One
declaration compares wall-clock epoch milliseconds from an untrusted wire field
and guards against absent, infinite and future-skewed values because the number
crosses a process boundary. A second compares wall-clock epoch milliseconds from
an internally written, statically typed record with a role-specific threshold and
needs no such guard. A third measures monotonic deltas against an in-process
timestamp for a same-process watchdog. These cannot be unified on principle
rather than convenience: monotonic time is process-local and meaningless across a
wire, and wall-clock time is meaningless for a watchdog whose whole point is
immunity to system clock steps. Three clock domains, three correct answers.
Related and also DISTINCT: the freshness helper's home looks misplaced at first
reading, and is not - it is sited where it is specifically to avoid an import
cycle, and the module says so.

### readiness-is-consumed-not-re-derived | low | the ladder has one home and its consumers ask it

Swept as consumed rather than as declared, which is the question that matters for
a single home. The staleness classifier is delegated to by every production
consumer, and the two sites that call the bare liveness primitive instead need
only that fact as a precondition rather than the staleness verdict - correct, not
a re-derivation. The readiness ladder states in its own docstring that it is the
single place readiness is computed so the surfaces cannot drift, and its
consumers re-probe live rather than re-deriving the ladder locally. No local
re-derivation found anywhere in the domain.

### a-second-inference-presented-as-fact | medium | method finding, same class as the first

The lane fixing the selection cluster was accused of writing to the vault against
instruction. It had not. None of its commits touch the vault, and the two
documents attributed to it were first added the previous day in a commit
preserving in-flight work across lanes. The accusation came from a stamp-refresh
that modified those files, and from inferring authorship because the command that
touched them was mine. That is the same failure as the earlier port-probe verdict
- an inference stated as a fact - and it was corrected only because the accused
answered with the commit list rather than accepting it. Recorded because two
instances in one campaign is a pattern, not an accident, and because a
correction that arrives only when someone pushes back is not a working practice.

### gateway-mints-a-credential-nobody-can-learn | high | not fragmentation, found by chasing it

The shared service harness could not authenticate to the versioned router at all,
and the cause is worth recording because it is not what the recipe assumed. The
gateway falls back to minting a random per-process service token when none is
configured. That is safe by default and correct for a gateway nobody is meant to
reach, but it means a harness sharing the process's own machine has no way to
learn the credential it must present - so the failure surfaces as an
authorization refusal rather than as a configuration one. An unconfigured
gateway that refused with a not-configured status would have been diagnosable;
one that mints a secret and then rejects everyone reads as a broken route. The
fix is to declare the bearer rather than to seed a desktop credential store, and
deliberately as a second constant rather than reusing the worker interprocess
secret, because the configuration is explicit that those planes must never
alias. Dark since 2026-07-19, same day as the run-identifier requirement.
Broken-on-arm.

### live-proof-owed-on-two-harness-commits | medium | proven at the seam, not by a run

Recorded so it is not mistaken for completed work. The harness schema fix and the
authentication fix are both landed and both proven only offline - the first by
parsing the committed source and validating the body it builds against the
production request model, the second by comparing the configured bearer against
what the authenticating path would expect, using the real settings object. Both
are the right proofs for the seam they target and neither proves a run completes.
The live run is blocked on an unrelated in-flight rehoming that has left the
working tree unable to collect the suite. Nothing past that gate has executed
since 2026-07-19, so more is expected to surface behind it once it clears.

### api-suite-depends-on-a-paid-provider-session | high | green here, error everywhere else

Both catalog derivations in the API test configuration select with no default, so
on any host where nothing is selectable they raise rather than skip, and every
test using that helper errors. It passes on this machine only because a real
provider session happens to be present. Two consequences, and the second is worse
than the first: the suite cannot pass in continuous integration or for a new
contributor, and on the machines where it does pass it is spending provider money
to assert things that have nothing to do with a provider. Fixed by migrating to
the in-process mechanism and arming in-process lanes for that suite - which is a
behavioural change to the suite's environment, and the right one. A suite whose
green depends on the developer holding a paid session is not a suite anyone can
trust.

### canonical-selection-mechanism-landed | high | the dangerous combination has no callable form

The consolidated mechanism is in place, mechanism only, with no consumer migrated
so each call site moves as its own reviewable change. The constraint agreed for
it is enforced more strongly than authorised: rather than a flag that could be
passed wrongly, there are two entry points and the unsafe combination cannot be
expressed - the in-process form takes no lane parameters at all, and the named
form cannot omit its entry. The test asserts that against the signatures rather
than by attempting a call, because the claim is that the API cannot express the
combination and a runtime probe would only show that one attempt failed. The
in-process form also refuses an external lane even when it is the only selectable
thing served, naming both the missing environment declaration and what was
actually served - which is exactly the developer-box case where the old
derivation silently returned a paid lane. Two parts of the original brief did not
generalise and correctly stayed with callers: the HTTP transport, which differs
per tier, and the cache, which keys on the caller's own base address.

### three-of-four-leads-were-already-closed | medium | method finding on how a lead list is built

Three of the four clusters in a lead list I issued turned out to be already
consolidated by earlier campaigns, and the investigating lane reported them as
false leads rather than manufacturing three commits. Gateway boot had already
been fixed, and the owning module's docstring records the earlier failure it
fixed - two copies that had disagreed about whether a dead child may be
tree-killed. Credential seeding has exactly one definition, already delegating
naming and hardening to production. And the two application factories build
different SUBJECTS - one the whole production application, one a bare application
carrying only the internal routes - where merging would have destroyed the very
distinction that let the second declare it has no database. The finding is about
the list, not the code: I assembled it from two semantic queries and memory, and
never checked whether each cluster was already closed. A lead list must be
verified as OPEN before it is issued, or it spends a lane's time re-deriving
history.

### deadline-policies-one-duplicate-two-distinct | medium | only one of three is a rehoming

Three death-aware waits exist with three different policies, and only one is
duplication. The progress-based wait declares its policy outright - fail on death
or stall rather than on elapsed wall clock. The gateway readiness wait is
wall-clock, single-child and HTTP-specific, and its budget is documented at
length as the deliberate larger of two previously forked values, sized for the
slowest real boot path; converting it to progress-based would be a behaviour
change wearing a rehoming's clothes, and it stays. The generic wall-clock wait in
the service harness does genuinely re-implement what the progress module owns and
is the one real move. Recorded as one DUPLICATE and two DISTINCT rather than as a
single cluster, so a later sweep does not collapse all three.

### affirmative-health-listener-declared-three-times | medium | the real move was a level below the brief

The gateway-boot cluster contained no duplication, as the correction above
established. One level down it did: three test packages each declared their own
bare loopback server answering an affirmative health response - silenced access
log, daemon thread, ephemeral port, clean shutdown - in the control watchdog
tests and in two authoring discovery test modules. Now one declaration in the
testing package, with all three local ones deleted rather than wrapped. Recorded
because the lesson generalises: a lead aimed at the WAITER was wrong, and the
duplication was in what the waiters were POINTED AT. A sweep that only asks who
performs an action will miss the fixtures that action is performed against.

One deliberate widening, flagged rather than slipped in: the consolidated handler
answers a not-found status off the health path, where two of the three answered
affirmatively to any request at all. Every caller was checked to probe only the
health path, so the stricter peer is a superset of what each relied on - and a
listener that answers everything is a worse stand-in for a service that does not.
The new module also records why it binds an ephemeral port rather than taking a
registry reservation, since the port cluster had just established the opposite
default: a listener that binds immediately and holds the socket IS its own
allocation, whereas the registry claim exists for a port handed to a child that
binds later. Without that note the next reader would file it as an
inconsistency.

The protected negatives here are the sharpest in the campaign so far, because
their behaviour IS the subject under test rather than shared scaffolding: a peer
that accepts and never responds, one that answers affirmatively with undecodable
bytes, one that stalls past a retry window, and stateful stubs that record what
was asked of them. Folding those together would produce a helper whose options
are a catalogue of unrelated defects.

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

### frozen-assignment-map-rebuilt-in-test-support | medium | a parallel producer for a consumer its canonical producer names

Building the per-role frozen assignment the compiler consumes is now declared
twice. `src/vaultspec_a2a/providers/model_profiles.py` carries the canonical
producer, whose docstring states outright that it returns the complete frozen
execution assignment consumed by the compiler, and which emits agent-id-keyed
entries of provider, capability, model name and fallback.
`src/vaultspec_a2a/graph/tests/conftest.py` hand-rolls the same shape and keying
for seventeen graph tests. Verdict is DUPLICATE. Self-reported: this session
created the second declaration in `dcf4f3e5` while completing the preset
provider-policy retirement, and did so without searching for an existing home -
the canonical producer is returned by a single semantic search for a frozen
per-role assignment, and its docstring names the exact consumer being served.

The consolidation is smaller than most in this inventory and carries one real
constraint. The canonical producer takes a resolved profile assignment, while
the test helper takes a team config and pins every role to the in-process
deterministic lane so a structural assertion never depends on a credential, a
network, or a served catalog. That pinning is a POLICY and must stay explicit at
the call site for the same reason the catalog-selection cluster records: a
structural test that silently acquired a served lane would spend money to assert
a node set. Consolidate by having the test helper build its assignment through
the canonical producer and keep the deterministic pinning as its argument.

A second-order note for the sequencing above: this duplication was introduced
DURING the campaign, by a caller who needed the concept and reached for the
nearest shape rather than the canonical home. That is the same mechanism the
inventory attributes to the older clusters, which suggests the rule is not yet
enforceable enough to bind a writer working at speed.

### terminal-status-map-now-derived | high | closes the vocabulary finding, verified and fixed

Re-verified the terminal-status-vocabulary finding recorded above against
current HEAD before touching anything, per this domain's own caution about
grep chains proving absence: the map in `src/vaultspec_a2a/thread/snapshots.py`
was still hand-typed with the same three literal keys, and its test in
`src/vaultspec_a2a/thread/tests/test_snapshots.py` still asserted a fourth
independent literal set rather than comparing against the authority. No fifth
derivation surfaced anywhere in the permission/control domain during this
sweep. ACTIONED: the map now comprehends over `TERMINAL_STATUSES`
(`src/vaultspec_a2a/thread/enums.py`) instead of restating its members, and
the test now asserts membership against that same authority. The container
stays a `dict[str, str]` rather than collapsing to the frozenset, unchanged
from the prior finding's guidance, because `control/event_handlers.py` reads
it with `.get(payload_status)` against an untrusted wire value, not membership
alone. Verified by running `src/vaultspec_a2a/thread/tests/` (226 passed) and
`src/vaultspec_a2a/control/tests/` (345 passed, 17 deselected `live`-marked)
in full, plus a whole-tree `ty check src/vaultspec_a2a`, which surfaced only
five pre-existing diagnostics in `authoring/tests/` and
`src/vaultspec_a2a/testing/listeners.py` — outside this domain and unrelated
to the change (an undefined `health_listener` fixture name and a stale
`@override` on `do_GET`), left unowned here since they are out of scope for
this sweep.

### permission-fsm-control-domain-swept-clean | low | rejection verdict, control-action journal, and clarification contract are single-homed

Reported because a domain sweep that finds one live defect and stops looks
incomplete rather than thorough. Several clusters were tested with four or
more independently-phrased searches each, per this domain's own method, and
found single-homed with no competing declaration anywhere in
`src/vaultspec_a2a/thread/` or `src/vaultspec_a2a/control/`.

The rejection verdict this domain's own history warns about is still exactly
one predicate: `is_rejection_response` in `src/vaultspec_a2a/graph/enums.py`,
wrapped once by `response_is_rejection` in
`src/vaultspec_a2a/thread/permission_fsm.py`, and consumed by both
`compute_progress_applied_effects` and `control/permission_service.py`'s
`_response_verdict`, whose own docstring states outright that stamping the
verdict from anywhere else is what let a rejection be recorded as an
approval. No third derivation was found. The clarification typed-interrupt
contract (request, answer, continuation, and decline shapes, plus their
bounds) lives once in `src/vaultspec_a2a/thread/clarification.py` and is
consumed, not restated, by `control/clarification_service.py` and the
checkpoint projection in `thread/snapshots.py` — consistent with this
project's binding rule that the checkpoint is the sole disclosure authority
for a pending clarification. The control-action journal and its lease
(reservation, claim, commit, release, settle) are declared once in
`src/vaultspec_a2a/database/permission_repository.py` and wrapped once in
`src/vaultspec_a2a/control/action_lease.py`'s `claim_control_action` /
`release_definite_non_delivery`, both consumed identically by
`permission_service.py`, `clarification_service.py`, and (for the crash-
recovery replay path) `direct_control_recovery.py`, with the definite-vs-
ambiguous non-delivery POLICY correctly staying an argument
(`FailureType`) rather than being decided inside the helper. ACP option-id
extraction from a durable JSON column is a two-layer single chain:
`graph/acp_options.py` owns the identity rule, `control/permission_options.py`
is a thin adapter over the durable column shape, and `permission_service.py`
is the only caller. `permission_resume_value` and
`permission_response_action_key` each have exactly one declaration. The four
permission/control enums (`ApprovalStatus`, `PermissionRequestStatus`,
`ControlActionResultStatus`, `ControlActionType`) are declared exactly once,
in `thread/enums.py`. `supersede_permission_requests` has one declaration and
one caller. Not established: `cancel_service.py` and `message_service.py`
were read only where they share the action-lease mechanism with this domain;
their own dispatch-failure state-restoration logic was not swept, since
cancellation and message follow-up sit outside this domain's assignment.

### compile-one-worker-node-restated-per-topology | medium | one compile step, four independent copies inside one file

`src/vaultspec_a2a/graph/compiler.py` already extracts the diverge/fan-out
mechanism into a shared `_wire_diverge_stage` helper and says so in its own
docstring - proof the file knows how to factor a repeated compile step when it
does. No equivalent exists for the much more frequently repeated step: resolve
a worker's model via `_resolve_model_for_worker`, compose its persona via
`_composed_worker_prompt`, build the node via `create_worker_node` with an
identical nine-keyword argument list, then register it on the builder with
`_agent_node_metadata` and `_NODE_RETRY_POLICY`. `_compile_star`,
`_compile_pipeline`, and `_compile_pipeline_loop` each write that block out in
full, and each also repeats the adjoining mount-node insertion verbatim -
`create_mount_node(workspace_root, task_queue_port)` bound to
`f"mount_{agent_cfg.id}"`, registered, and edged to the worker - differing only
in whether the mount id is computed before or after `add_node` and in
`_compile_pipeline_loop`'s one extra line wrapping the loop node via
`_wrap_loop_node`. `_compile_research_adr` restates the worker half of the same
step a fourth way, six more times over (synthesis, research_review, adr_author,
adr_review, plan_author, plan_review), each a hand-written
`builder.add_node(_RA_X, create_worker_node(...), retry_policy=_NODE_RETRY_POLICY)`
with no mount node and `harness_mcp_servers` composed in instead.

Verdict DUPLICATE on the mechanism, confirmed by grep: no private helper named
anything like `_compile_worker_node` exists anywhere in the file, and the
argument list to `create_worker_node` was checked call site by call site rather
than assumed. The policy that must stay explicit per call site is real and
three-way: whether a mount node is inserted (star and pipeline/pipeline_loop
yes, research_adr no, composing harness servers instead), how the compiled node
is edged onward (back to the supervisor, into the next pipeline stage, into the
loop's conditional edge, or into a fixed document-phase successor), and whether
the node is loop-wrapped. None of those three axes is reason to keep the
resolve-compose-build-register step itself typed out four times: a shared
helper returning the built node (or the node plus its mount id) and leaving
insertion/edging to the caller would cut roughly eighty lines of near-identical
code from the file's already-largest module and remove the risk this audit
keeps finding elsewhere under different names - that `create_worker_node`'s
argument list, `_agent_node_metadata`, and `_NODE_RETRY_POLICY` are currently
kept in agreement across four call sites by upkeep, not by construction.

### domain-event-vocabulary-restated-across-two-catalogs | high | the closed event set is authored twice, with different failure postures on drift

`src/vaultspec_a2a/ipc/serializers.py` enumerates the eleven `DomainEvent`
subclasses declared in `graph/events.py` (`AgentStatus`, `ArtifactUpdate`,
`ClarificationPending`, `ErrorOccurred`, `MessageChunk`, `PermissionRequest`,
`PlanUpdate`, `TeamStatus`, `ThoughtChunk`, `ToolCallStart`, `ToolCallUpdate`)
in a `match` statement that tags each with its stable wire-type string for the
worker-to-gateway IPC relay. `src/vaultspec_a2a/api/event_adapter.py`
enumerates the identical eleven-member set in its own independent `match`
statement, `domain_to_wire`, which projects each event onto a distinct
Pydantic wire model for in-process API streaming. Neither Python's structural
pattern matching nor the project's type checker enforces exhaustiveness across
a dataclass union, so nothing statically ties the two enumerations together;
they agree today purely because both were kept in sync by hand. The drift
postures differ and one is dangerous: `event_adapter.py`'s catch-all raises
`TypeError` for an event neither match handles, a loud failure a test will
catch; `ipc/serializers.py`'s catch-all returns `None`, which the module's own
docstring names as the exact mechanism that shipped `ClarificationPending`'s
wire tag undeliverable once already - a relayed event crosses the IPC boundary
with no `type` at all, is stripped to the always-safe identity keys on the far
side, and nothing raises, because the loss happens after the in-process
emitter has already returned. Verdict DUPLICATE on the vocabulary: a third
domain event added to `graph/events.py` and threaded into only one of the two
match statements silently loses either its API wire shape or its IPC-relayed
type, and the silent side has already burned the project once. The fix is not
to merge the two match statements - they produce genuinely different outputs,
a type tag versus a full wire model - but to derive both from one
authoritative enumeration of the union's members, or add an exhaustiveness
assertion to each catch-all, so a missed case fails a type check rather than a
production relay.

### per-run-store-mechanism-duplicated | medium | two worker-scoped stores share one shape, declared twice

`src/vaultspec_a2a/worker/token_store.py`'s `RunTokenStore` and
`src/vaultspec_a2a/worker/catalog_store.py`'s `RunCatalogStore` are two
independent declarations of the identical mechanism: an in-memory
`dict[str, T]` keyed by thread id, with `register` (a no-op on `None`), a
read accessor, `has`, `active_run_count`, an idempotent `drop`, and a
`__repr__` that reports only the active-run count so neither store ever
widens a log line. Both docstrings say so explicitly - `RunCatalogStore`'s
states it mirrors `RunTokenStore`'s lifecycle, and its own test class carries
the same description. The only real variance is the value type and its
accessors: `RunTokenStore` adds a role-scoped `actor_token` reader and an
`engine_bearer` reader, both reading fields off the held actor-token bundle;
`RunCatalogStore` adds a bare `get`. Verdict DUPLICATE on the mechanism, and
safely so: nothing here is a policy divergence, both stores are dropped at the
identical terminal boundary in `Executor._mark_ingest_done` and constructed
together in `Executor.__init__`. A generic per-thread holder - register, has,
drop, active_run_count, redacting repr, parameterised on the held type - would
collapse both to a thin subclass or a direct instantiation, and the accessor
asymmetry, role-scoped reads for the token bundle against a bare read for the
catalog snapshot, stays exactly where it is now as the one piece that is not
shared.

### worker-ipc-domain-swept-and-found-clean | low | dispatch identity, project-root minting, and duplicate suppression are single-homed

Recorded for the negative space in the worker execution and inter-process
dispatch domain. `DispatchIdAdmission` in `src/vaultspec_a2a/worker/dispatch_ids.py`
and the durable control-action journal lease consumed by
`src/vaultspec_a2a/control/direct_control_recovery.py` and
`verdict_subscriber.py` are DISTINCT by design and documented as such: the
worker's admission is a process-local, restart-cleared FIFO suppression window
that exists solely to keep a duplicate HTTP POST from crossing into the task
group twice, while the journal lease is the durable, cross-restart recovery
authority - the worker's own docstring states plainly that the journal
"retains recovery authority" and the admission window does not attempt to.
`canonical_project_root` in `src/vaultspec_a2a/ipc/schemas.py` is confirmed the
single site that mints a run's active-project spelling for the dispatch wire;
the admission-time mint in `src/vaultspec_a2a/control/thread_service.py`
writes that same canonical form into the durable record so every later
dispatch reads it back rather than re-deriving one, and the separate reduction
function in `src/vaultspec_a2a/providers/_acp_types.py` is a documented
DISTINCT concept serving scope-enforcement comparison rather than wire
transport. Worker interprocess bearer verification and worker health probing
were already confirmed single-homed by an earlier sweep and are not
re-litigated here.

### correction-bounded-poll-loop-has-an-eighth-site | high | supersedes the seven-site count in engine discovery

`resolve_engine_with_retry` in `src/vaultspec_a2a/authoring/discovery.py` is an
eighth production declaration of the bounded wall-clock poll shape the earlier
`bounded-wall-clock-poll-loop` finding inventoried as seven sites. It is not a
test helper: `src/vaultspec_a2a/worker/graph_lifecycle.py` calls it twice, off
the thread pool, at the two points a run must resolve a live engine before it
can submit or bridge authoring work, with its own docstring stating plainly
that it exists because the engine's health endpoint measurably stalls for
several seconds while its scope watcher rebuilds. It declares its own interval
(`delay_seconds=2.0`) and attempt count (`attempts=4`), a fourth private
constant alongside the seven the original finding named. This does not change
that finding's verdict - DUPLICATE, no shared `poll_until` primitive exists
anywhere in the tree - it only corrects the count and names the site the
earlier sweep's search terms did not reach. Recorded as a correction rather
than a rewrite, per this audit's own rule against rewriting settled entries.

### service-json-candidate-list-reimplemented-in-control | medium | canonical builder is private, so a caller re-derived it

`src/vaultspec_a2a/authoring/discovery.py` builds the engine discovery
candidate list - the `VAULTSPEC_ENGINE_SERVICE_JSON` env override, then
`~/.vaultspec/service.json` - in a private, unexported `_candidates()`
function. `src/vaultspec_a2a/control/health.py`'s
`probe_engine_discovery_freshness` imports `SERVICE_JSON_ENV`,
`heartbeat_is_fresh`, and `read_service_json` from that same module - it is
clearly aware of the canonical source - but reconstructs the two-entry
candidate list inline, statement for statement, rather than importing a
shared builder, because none is exported. Verdict DUPLICATE on the ordered
candidate-list construction, not on the freshness classification (which
`control/health.py` does correctly per its own distinct non-blocking, no-HTTP
contract). The fix is narrow and stays inside the discovery module: export the
existing `_candidates()` (or a thin public alias) so the control-side caller
imports the ordering instead of restating it; both files agree today only
because nobody has yet changed the env-override-then-home order in one and
forgotten the other. Recorded rather than actioned because the consuming
call site is in `control/`, outside this sweep's domain.

### reviewer-verdict-vocabulary-blocked-from-merging-by-layering | medium | one vocabulary, two declarations, a real import-cycle wall between them

`VERDICT_APPROVED` / `VERDICT_REJECTED` / `VERDICT_REQUEST_CHANGES` -
`"approved"` / `"rejected"` / `"request_changes"` - are declared as three
identical module-level string constants in both
`src/vaultspec_a2a/authoring/lifecycle.py` and
`src/vaultspec_a2a/graph/nodes/phase_gate.py`. This is not an oversight: the
latter module's own docstring states the gate is built as a `Protocol` seam
"decoupled from the authoring package" on purpose, and the decoupling is not
optional - `src/vaultspec_a2a/authoring/submitter.py` already imports
`ProposalRevisionRequiredError` FROM `graph.nodes.phase_gate`, so the reverse
import phase_gate.py would need to reuse authoring's constants does not exist
to take: it would close an import cycle. Verdict DUPLICATE on the value, but
correctly DISTINCT in its current form given the dependency direction as it
stands today - flattening this into one import would require extracting the
three-string vocabulary into a leaf module beneath both `graph.nodes` and
`authoring` (a role comparable to `graph/enums.py`, which `authoring` already
imports without cycling), a change that touches `graph/`, outside this
sweep's domain. Recorded so a future consolidation does not "fix" this by
naively importing one from the other and reintroducing the cycle it avoids.

### dispatcher-injected-fields-declared-at-two-resolution-stages | medium | untested parity between a tool-name map and a command map

The set of fields the run dispatcher owns and silently overwrites on a
proposal command is declared independently in two places, keyed by two
different vocabularies. `src/vaultspec_a2a/protocols/mcp/tools/authoring_bridge.py`'s
`_INJECTED_FIELDS_BY_TOOL` maps the catalog's semantic TOOL names
(`propose_changeset`, `validate_proposal`, `request_approval`, `cancel`,
`request_apply`) to the fields hidden from that tool's advertised schema.
`src/vaultspec_a2a/authoring/catalog.py`'s `make_tool_dispatch._apply_injection`
maps the resolved engine COMMAND names (`create_proposal`, `append_draft`,
`replace_draft`, `validate_proposal`, `submit_for_review`, `cancel_proposal`,
`request_apply`) to the fields it actually strips and overwrites at dispatch
time - a single tool name like `propose_changeset` resolves to three different
commands depending on the model-supplied `operation`, each with a different
injected set in the command map, while the tool-name map applies one fixed set
across all three. The bridge module's own comment says the two "MUST stay
consistent," but no test asserts it, and grepping both symbols found no shared
call site. Consequence is currently latent, not live: the engine's served
catalog for `propose_changeset` already excludes `expected_revision` from its
schema `properties` (verified against the fixture at
`src/vaultspec_a2a/protocols/mcp/tests/catalog.json`, whose own `description`
field independently states `expected_revision` is "Injected below the model"
alongside `session_id`/`changeset_id`, a THIRD, prose-only assertion of the
same fact), so there is nothing to leak today. But the tool-name map does not
list `expected_revision` for `propose_changeset`, unlike the command map,
which injects it for the `append_draft`/`replace_draft` resolution - if a
future engine catalog exposes `expected_revision` as a real property on that
tool's schema, `_deep_strip_injected` would not remove it and the model would
see a dispatcher-owned field as though it were free to set, silently discarded
at dispatch. Verdict DUPLICATE on the injection policy across two resolution
stages, not actioned: the two maps operate at genuinely different points
(schema-authoring-time hiding by tool name versus dispatch-time value
overwrite by resolved command) and collapsing them risks conflating "what the
model is shown" with "what the model cannot forge," which the campaign brief
names as exactly the mechanism-versus-policy distinction to preserve. The
narrower, safe fix is a parity test asserting every command-map entry's field
set is a superset of its resolving tool's schema-map entry.

### authoring-and-protocols-swept-and-found-clean | low | eleven modules confirmed single-homed

Recorded for the negative space in this sweep's domain. `authoring/contract.py`
(the document-authoring role/topology leaf), `authoring/_ids.py` (id validation
and idempotency-key derivation - confirmed the sole declaration by four
differently-phrased semantic searches), `authoring/_envelope.py` and
`authoring/_errors.py` (the shared-envelope and typed-error decoding, each
consumed rather than restated by every caller), `authoring/session.py` (the
proposal-verb lifecycle), `authoring/catalog.py`'s fetch/parse/execute
mechanism, `authoring/discovery.py`'s heartbeat and record-parsing logic
(distinct by design and documented as such from `lifecycle/discovery.py`, the
producer-side authority it mirrors), `protocols/mcp/tools/schema_normalize.py`
(confirmed the single normalization seam by
`protocols/mcp/tools/authoring_bridge.py`'s own docstring and by search), and
`protocols/mcp/authoring_stdio.py`'s `ENV_*` names (the sole declaration site;
`providers/_acp_authoring.py` imports them rather than restating the strings)
are each single-homed. `authoring/feedback_reader.py`'s `render_feedback_batch`
looks, by name, like a third mounting mechanism alongside
`graph/nodes/vault_reader.py`'s document and task-queue mounts, but it is
DISTINCT by injection site, not merely by content: the vault/queue mounts wrap
every block in a shared `_DOC_SEPARATOR`/`_DOC_FOOTER` header inside
`mounted_context`, while feedback grounding rides into the worker's system-
message construction (`graph/nodes/worker.py`'s `_build_worker_messages`)
through an entirely separate parameter, never touching the mount header
format. `authoring/submitter.py`'s body-link and frontmatter scan mirrors
vaultspec-core's own check by necessity (a cross-repository boundary, not a
same-tree duplicate) and is already regression-locked by
`authoring/tests/test_core_grounding_parity.py` against drift. Breadth not
established beyond the modules read: `authoring/tests/` and
`protocols/mcp/tests/` internals were not swept for their own duplication
against each other.

### worker-node-id-convention-declared-in-two-domains | low | a naming convention, not three lines

Recovering the agent id from a compiled node name is declared twice, in two
domains, each stripping the `mount_` prefix and treating an empty name or
`__end__` as no node before doing a genuinely different lookup.
`src/vaultspec_a2a/graph/enums.py` resolves the node to its semantic phase;
`src/vaultspec_a2a/api/routes/gateway.py` resolves it to the active role.
Verdict is DUPLICATE, and the entry is worth making despite its size because
what is duplicated is not the three lines - it is the CONVENTION. The `mount_`
prefix and the `__end__` sentinel together define what a worker node id is, and
that definition currently has no home: it is knowledge the compiler creates and
two unrelated readers each re-derive. Renaming the prefix would require finding
both, and nothing points either at the other.

Surfaced by the graph sweep, which correctly declined to act on it because the
second site lies outside that domain. Recorded here rather than actioned in the
same breath for the same reason the campaign records everything else: the
consolidation is small, but it decides where a compile-time convention is
allowed to live, and that is a placement question rather than a mechanical one.
The cheap resolution is a single normalizer beside the compiler that mints the
prefix, exported for both readers, so the convention is declared exactly where
it is created.

### compiler-worker-node-extraction-is-deferred-deliberately | medium | a recorded non-action, so it is not re-litigated

The graph sweep recorded that resolving a worker's model, composing its persona,
building the node with an identical nine-argument call and registering it with
shared metadata and retry policy is written out in full by three topology
compilers and a fourth way, six more times, by the research-adr compiler. It
declined to extract it. That decision is endorsed and recorded here so a later
sweep does not read the absence of action as an oversight: the extraction spans
four call sites in the tree's largest module, and the three edge-wiring policies
around it - mount-node versus harness insertion, how the node edges onward,
whether it is loop-wrapped - are exactly the kind of per-site policy this
campaign has repeatedly found flattened by well-meant consolidation. It wants
dedicated per-site test scrutiny, not a fold-in at the end of a sweep.

### agent-descriptor-wire-model-declared-a-third-time-untested | high | the exact incident the parity guard exists to prevent, recurring outside its reach

`src/vaultspec_a2a/thread/snapshots.py` declares `AgentData` a canonical
dataclass and says so explicitly: "Single declaration behind every
agent-shaped surface: the REST team-status entry, the `team_status` broadcast
summary, and the thread snapshot all project from this type rather than
redeclaring the field set." `src/vaultspec_a2a/api/schemas/tests/test_snapshot_parity.py`
enforces exactly that for one of the three named surfaces: it pairs
`domain.AgentData` with `wire._AgentSnapshot` (`src/vaultspec_a2a/api/schemas/snapshots.py`)
in its `_MIRRORS` table and fails the suite the moment either declares a field
the other does not, citing the concrete past incident that motivated it -
`provider`/`model` reaching clients as unconditional `null` from the
team-status route until an implicit splat was replaced with explicit field
names.

The second named surface, the `team_status` broadcast, is carried by
`AgentSummary` in `src/vaultspec_a2a/api/schemas/events.py` - a THIRD
independent Pydantic declaration of the identical eight-field set
(`agent_id`, `node_name`, `state`, `provider`, `model`, `role`, `display_name`,
`description`), docstringed the same way ("Mirrors `thread.snapshots.AgentData`")
but absent from `_MIRRORS` and therefore unguarded. `src/vaultspec_a2a/api/event_adapter.py`
builds it field-by-field from a plain `dict` (the domain `TeamStatus` event
carries `agents: list[dict[str, str]]`, not typed `AgentData`), so the
guard's `model_validate(asdict(data))` seam does not even run over this path -
nothing anywhere compares `AgentSummary`'s fields against `AgentData`'s.
`PermissionOption` (same file) repeats the shape exactly: a third declaration
of `PermissionOptionData`'s field set, alongside the tested `_PermissionOptionSnapshot`
in `snapshots.py`, built field-by-field from a `dict` in the same adapter and
equally absent from `_MIRRORS`.

Verdict DUPLICATE, high severity precisely because the parity guard's own
docstring names the failure mode this reproduces: a field added to `AgentData`
(or `PermissionOptionData`) and forgotten on the snapshot mirror is caught by
`test_domain_and_wire_declare_the_same_fields`; the identical omission on
`AgentSummary` or `PermissionOption` is caught by nothing, and the broadcast
surface silently ships the field as absent - the exact `provider`/`model` null
incident, on the surface the guard was written to also cover but does not
reach. Recorded rather than actioned: the clean consolidation - `snapshots.py`
importing `AgentSummary`/`PermissionOption` from `events.py` in place of
declaring `_AgentSnapshot`/`_PermissionOptionSnapshot` (the file already
imports `PlanEntry`, `ToolCallContent`, and `ToolCallLocation` from `.events`,
so the direction is established) - touches `_MIRRORS` in
`api/schemas/tests/test_snapshot_parity.py` (in scope) but also
`src/vaultspec_a2a/thread/tests/test_snapshots.py`, which imports
`_AgentSnapshot`/`_PermissionSnapshot` by name directly from
`api.schemas.snapshots` (`thread/`, out of scope for this sweep). Whoever owns
`thread/` should coordinate the rename in the same change, not a follow-up.

### team-status-rest-route-narrower-than-its-own-canonical-docstring | medium | an absent projection, not a duplicate - recorded as its own verdict

`src/vaultspec_a2a/thread/snapshots.py`'s `AgentData` docstring names three
surfaces it is the single declaration behind: "the REST team-status entry, the
`team_status` broadcast summary, and the thread snapshot." Two of the three
carry the full eight-field set (`agent_id`, `node_name`, `state`, `provider`,
`model`, `role`, `display_name`, `description`) - the broadcast's `AgentSummary`
and the snapshot's `_AgentSnapshot` (both `api/schemas/`, the latter parity-
tested against `AgentData` per the finding above). The REST entry does not:
`RunAgentSummary` (`api/schemas/gateway.py`), served by `GET /team/status` in
`api/routes/gateway.py`, declares only `agent_id`, `display_name`, `state` -
dropping `node_name`, `provider`, `model`, `role`, and `description`.
`RunStatusResponse.roles` on the sibling per-run read (`GET /runs/{run_id}`)
uses `RoleState` (`agent_id`, `role`, `state`, `display_name`), which restores
`role` but still omits `provider`/`model`. Neither narrowing is accidental:
both wire models are hand-declared with exactly those fields, and
`control/team_service.py`'s `build_team_status` resolves the FULL `AgentData` -
including `provider`/`model` - via the shared `build_agent_descriptor` seam
before the route discards the difference at construction. This is confirmed
deliberate by `api/tests/test_team_status_descriptor.py`'s own docstring:
"They stop at the SERVICE rather than a route. The versioned team-status verb
is a deliberately narrow operational projection - agent id, display name,
state - and carries neither field, so the route can no longer express what
these cases are about while the service still resolves it." That module exists
specifically to guard the provider/model resolution chain, and states outright
that it cannot assert its own subject at the REST layer because the REST
contract was narrowed underneath it.

Verdict is neither DUPLICATE nor MISPLACED - it is the third class the domain
lead named going into this sweep: an absent projection. `AgentData` is a
canonical, single, correctly-consumed declaration; nothing here restates its
field set incorrectly. The gap is that its own docstring's claim - that the
REST team-status entry projects from it - is not true today, and has not been
true since whatever narrowed `RunAgentSummary`/`RoleState` to their current
field sets (no `git blame` was pulled to date that change; not asserted). The
practical consequence: a client polling either REST status route cannot learn
which provider or model an agent is running - only a WebSocket subscriber
catching the `team_status` broadcast, or a client reading the reconnect
snapshot, can. Whether that is the intended product boundary (REST is a
lighter poll, the socket carries the full picture) or a regression from a
narrower verb that was never widened back is a product decision this inventory
does not make; recorded so whoever owns that decision is choosing it rather
than discovering it. If the answer is "REST should carry it too," the fix is
additive - two more fields on each of `RunAgentSummary` and `RoleState`,
sourced from the same `AgentData` the service already resolves - not a new
mechanism.
