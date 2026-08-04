---
tags:
  - '#audit'
  - '#canonical-homes'
date: '2026-08-04'
modified: '2026-08-04'
body_schema: 'body-v1'
body_hash: 'sha256:45ad7949b436840905d3a6d8a60eadee16347eb478ac34da5171b9c3dec3a49a'
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

### a-mechanism-without-deletions-makes-it-worse | critical | the rule the campaign must execute by

Verified by direct sweep rather than from any report: two clusters genuinely
deleted their old declarations, and one did not. The canonical selection
mechanism landed while every derivation it replaces stayed in place, so that
concept currently has SEVEN declarations where it had six. Landing a home and
migrating consumers later is not a phased delivery; it is a state strictly worse
than before, because the maintenance question is still unanswerable and there is
now one more file to check. The rule this campaign executes by, stated so no
later reader has to infer it: a cluster is CLOSED only when the old declarations
are deleted, and every commit deletes the declaration it replaces in the same
change. A site that cannot migrate because the mechanism lacks its filter is a
reason to extend the mechanism in that commit, never a reason to leave the site
behind.

### two-more-uncounted-selection-sites | high | the third sweep still missed sites

The same verification found two derivations that appear on no previous list,
after three sweeps by two different readers. One lives in a role-override test
and filters for a lane advertising MORE THAN ONE model, because a test that
overrides between entries needs two to choose from - a third filter the mechanism
must express rather than let that site keep its own copy. The other lives in the
CLI live tests and returns a different shape entirely, an entry rather than a
selection reference. Neither matches the naming the earlier sweeps keyed on; both
were found only by searching for what code DOES with the served payload. Recorded
as a finding about the discriminator, not the sites: a list that has missed
members three times should be treated as incomplete by default, and any further
site found is evidence of that rather than a surprise.

### a-bare-commit-takes-another-lanes-index | high | method finding, and it broke the repository

An audit commit captured another lane's staged rename and published a state where
a module had moved but its three importers had not, so importing that package
failed at HEAD while every working tree was fine. The mechanism is narrower than
it looks and worth stating exactly: no broad add was used. One explicit path was
staged, and then a bare commit was run - which commits the ENTIRE INDEX rather
than what was just added. An explicit-pathspec discipline that covers the add and
not the commit is not a discipline at all, and in a shared index every commit
carries the exposure, not only the careless ones. The practice adopted: verify
the staged set matches intent immediately before committing, or pass the pathspec
to the commit itself. Recorded beside the two earlier method findings because
this one reached the repository rather than only a report, and because it is the
mirror image of the earlier trap - there HEAD was correct and the tree was wrong,
here the tree was correct and HEAD was wrong.

### a-home-nothing-can-reach-is-not-a-home | high | a documented exception, measured away

The most useful category this campaign has produced is not a duplicate but a
documented exception whose stated reason could be measured away. The atomic
writer declared itself the only copy of its pattern and named two writers keeping
their own loop, each with a recorded justification. One of them - a provider
leaf's credential refresh - said importing the audited writer would drag the
process registry, service discovery and control configuration into a leaf whose
import latency sits on an interactive window. That was true and the cost was
real, but small when measured cold, and the decisive fact was not the size: the
utility package was ALREADY fully loaded at that leaf, because a leaf cannot be
imported without executing its package. So the canonical implementation costs
nothing where it was needed, and the reason for the exception was an artefact of
WHERE the implementation lived rather than of what it did. A home nothing can
reach is not a canonical home. The duplicate is deleted rather than wrapped, and
the writer now lives where its consumers already are.

One genuine difference was preserved rather than flattened, and the method is the
model for every remaining rehoming: the shared writer suppresses newline
translation while the local copy took it, so a co-owned credential file is
currently written with platform line endings. The delta was proved empirically on
an identical payload rather than argued, exposed as a seam the one co-owned
caller declares, and pinned by a test so a later collapse fails there instead of
silently rewriting a third party's file. Changing the bytes of a file this
project co-owns with an external tool is a decision to take deliberately, and it
was left open rather than taken in passing.

### path-containment-checks-are-not-one-concept | medium | six sites, high flattening risk, left alone

Containment checks appear at six production sites and read as one concept. They
differ in resolve strictness, in the error type raised, and in whether the root is
resolved as well as the candidate, and one asks a different question entirely -
mutual nesting in either direction rather than containment in one. Verdict
DISTINCT. Recorded because this is security-relevant code where a flattening
error is a boundary failure rather than an inconvenience, and because reporting it
rather than churning it is the behaviour the campaign wants from a sweep that
finds a plausible cluster with no safe merge.

### service-cannot-express-a-posture-its-factory-supports | high | the arming tension, and its real cause

Migrating the API suite onto the canonical selection mechanism failed twice, and
the second failure named the real defect. Arming in-process lanes through the
process environment leaks into the real gateway subprocesses this suite spawns,
changing the lane inventory for tests that have nothing to do with selection.
Scoping the arming to the derivation instead fixes the leak and then fails
differently, because run start REVALIDATES a selection against a fresh catalog
read at request time - so a lane armed only for the derivation is gone by the
time the reference is checked, and the selection names a lane the gateway no
longer serves. Arming must therefore hold for every read the application
performs, which is exactly the process-wide scope that leaks.

The cause is not the tension; it is that the catalog service cannot express a
posture its own factory already supports. The factory takes an explicit
in-process arming argument and its docstring states that an explicit value is the
same decision made by a caller that knows its own posture, so the policy is
exercisable WITHOUT reaching into the process environment. The service drops that
argument at the single call where it builds registrations, leaving the
environment as the only transport. Threading it through is completing a declared
design rather than adding a test-shaped affordance to production, and it removes
the whole class of problem instead of teaching more sites about an environment
variable. Recorded because the rejected alternative - unsetting the variable at
each subprocess spawn site - would have worked while leaving a discovery test
carrying a selection concern permanently, and environment-as-transport is what
leaked in the first place.

### the-mechanism-found-a-bug-on-contact | medium | a latent splice, passing by coincidence

The role-override authority test read a catalog revision from one lane and
grafted it onto a selection naming a different lane. It passed only because both
happened to resolve to the same lane on a developer box, and failed the moment
they diverged, with the gateway correctly refusing a stale revision. Recorded
because it is the strongest evidence that the split-function mechanism earns its
design: a consolidation that surfaces a real defect the first time it is pointed
at existing code is doing more than removing copies. The accompanying fix to the
catalog route test is also a strict improvement - asserting the external lanes as
an ordered PREFIX with in-process lanes following tests the factory's stated
invariant, that in-process registrations come last and cannot reorder the
external lanes a client already enumerates, which nothing asserted before.

### a-copied-vocabulary-grew-a-member-that-never-existed | high | the ruling demonstrated, not argued

The terminal-status wire vocabulary - the STRINGS a consumer needs when
comparing a decoded database column, JSON body or relay frame, as opposed to the
enum members the authority holds - was derived independently at nine sites, four
of them production. Two of those sites spelled the same comprehension two
different ways in one module. Two test tiers had each grown their own NAMED
constant for it, and two more had given up on the vocabulary entirely and written
the literals out.

One of those hand-written variants waited on a status of "error". The lifecycle
enumeration has never had such a member - verified against the enumeration
itself, which holds submitted, running, input-required, cancelling, cancelled,
completed, failed, archived, repair-needed and reconciling. So that arm could
never fire. Harmless where it sat, and precisely the failure mode in miniature: a
vocabulary copied by hand acquires members the real one does not have, and
nothing tells you. This is the campaign's ruling demonstrated in the wild rather
than argued from principle.

The consolidated value now sits beside the authority it derives from, following a
precedent already next door where a sibling map is derived rather than restated
for the same reason. Two sites also gain correctness rather than only losing a
copy: one rebuilt its set on every call inside per-thread projection code, and
another ran a membership test against a list.

Two candidates in the same cluster were checked before collapsing, which is the
part worth copying. A settlement payload's status field was traced to its schema
and found to be typed as the same enumeration, so routing it through is correct
rather than a coupling of two vocabularies that may legitimately diverge. And a
list that could have mattered to a database query construct was confirmed to be
used only for a membership test, so narrowing it is behaviour-identical.

### a-gate-result-ages-out-in-a-shared-tree | medium | method finding

A lane reported a clean whole-tree type check; the repository showed two
diagnostics minutes later, in a file that lane held uncommitted. Nothing was
misreported - the gate was run and it passed, and then work continued in the same
tree and the result aged out. In a tree with several concurrent writers a gate
result is true only for the commit it immediately precedes, so gates belong
LAST, immediately before staging, not first. Recorded beside the other method
findings because it is the same class as the bare-commit failure: a discipline
that is correct in a single-writer tree and insufficient in a shared one.

### inference-stated-as-fact-three-times | high | standing method finding, not three incidents

Three attributions in this campaign were asserted from inference and were wrong:
a port-probe verdict placed into a discovery brief as context, which the sweep
returned as independent confirmation; an accusation that a lane had written to
the vault against instruction, when the documents predated it by a day; and an
attribution of a type-check break to the lane that happened to be working
nearby. Each was corrected by the accused answering with evidence rather than by
the claim being checked before it was made, which is the part that has to
change.

The specific artefact that caused the third is worth naming because it will
recur: this project uses ONE shared worktree, so every lane sees every other
lane's uncommitted edits. A file showing as modified proves that someone is
working, never who. The reliable tests are reading the diff for intent, or
checking the suspect's own commits for the path. Recorded as a standing finding
rather than three incidents, because three in one campaign is a practice rather
than a run of bad luck.

### overload-resolution-cannot-see-through-a-splat | medium | a real edge in a correct rehoming

Preserved so the owning lane need not re-derive it. An in-flight rehoming
replaced an inline platform branch selecting detached-spawn flags with a call to
a shared helper, splatted into the subprocess constructor. That constructor's
signature is heavily overloaded, and overload resolution cannot see through a
keyword splat of a plain mapping - so a call that resolved while the two flags
were passed by keyword became unresolvable the moment they arrived as a splat.
Runtime behaviour is unchanged; the checker simply lost the ability to select an
overload. Either a precisely typed mapping return, splatted as such, or a
returned pair with the flags still passed by keyword, restores it. Worth
recording as the campaign working rather than failing: the rehoming is one this
inventory asked for, and the type checker caught a genuine edge in it.

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

### permission-option-kind-derivation-diverges | high | a live sync path bypasses the module's own preferred resolver

`src/vaultspec_a2a/streaming/types.py` declares two ways to turn an ACP
permission option into a `PermissionOptionKind`: `map_acp_option_kind`, a bare
substring heuristic over the option id, and `resolve_acp_option_kind`, which
trusts the option's own declared `kind` field and reaches for the heuristic
only when that declaration is absent or schema-invalid. The module's docstring
is explicit that the second is the authority and the first is "the
derivation, not the authority." `src/vaultspec_a2a/streaming/transformer.py`'s
`_permission_option` - the function that actually builds a `PermissionRequest`
event from a live ACP interrupt - obeys this correctly, calling
`resolve_acp_option_kind` and logging when a declared kind is invalid enough to
need the fallback. But `EventEmitters._sync_permission_request` in
`src/vaultspec_a2a/streaming/emitters.py`, the handler that rebuilds the
gateway's own pending-permission cache from a relayed worker payload inside
`sync_worker_event`, calls `map_acp_option_kind(opt.get("option_id", ""))`
directly - discarding whatever `kind` the relayed payload already carries (a
value that, on the worker side, was itself already correctly resolved through
`resolve_acp_option_kind` before the event was ever serialised) and re-deriving
a possibly different answer from the id alone. The two paths can disagree on
the identical option: `resolve_acp_option_kind("reject_once", "approve")`
resolves to `REJECT_ONCE` (the declared-kind test in
`streaming/tests/test_permission_option_projection.py` asserts exactly this),
while `map_acp_option_kind("approve")` resolves to `ALLOW_ONCE`, because the id
carries no rejecting keyword. Verdict DUPLICATE on the derivation, not the
container. Not established: whether this cache currently has a live reader -
`EventAggregator.get_pending_permissions` has production writers
(`resolve_permission`, `expire_thread_permissions`, `prune_stale_permissions`,
all called from `control/event_handlers.py` and `worker/executor.py`) but no
production caller of the read method was found outside this package's own
tests, so the blast radius today may be limited to an unread cache rather than
a client-visible misclassification. The fix is to have
`_sync_permission_request` call `resolve_acp_option_kind` with the relayed
payload's own `kind` field, the same authority the worker-side emission path
already obeys, rather than re-deriving from the id.

### stale-two-path-rationale-for-the-shared-subscriber-registry | low | the second relay path the safety argument depends on no longer exists

`src/vaultspec_a2a/streaming/fanout.py`'s module docstring states its bounded-
delivery policy exists because "two relay paths implemented that rule
independently - the server-sent-event subscriber registry and the WebSocket
connection manager." `src/vaultspec_a2a/streaming/subscribers.py`'s
`add_subscriber` repeats the same premise - "the SSE stream route and the
event WebSocket both register against it" - to justify enforcing the
connection cap at the registry rather than at either calling route.
`src/vaultspec_a2a/streaming/tests/test_stream_connection_cap.py` opens on the
identical claim and even names its two `_fill()` prefixes `"sse"` and `"ws"` to
dramatise it, though the test itself only ever calls `add_subscriber` and never
drives a real route. `src/vaultspec_a2a/control/event_handlers.py`'s
`relay_event` docstring separately tells a caller to broadcast "to WS clients
via ConnectionManager." No `ConnectionManager` class exists anywhere in the
tree, and no client-facing event WebSocket route exists either - the only
WebSocket in the codebase is the internal worker-to-gateway channel at
`/internal/ws` in `src/vaultspec_a2a/api/internal.py`, which is not a client
registration surface at all. The only live client entry into the shared
registry is the SSE route in `src/vaultspec_a2a/api/thread_stream.py`. Verdict
is neither DUPLICATE nor MISPLACED: there is no second declaration to
consolidate, and this is the inverse of most findings here - a single, correct
implementation whose own safety reasoning is written as though a sibling still
exists. Recorded because the reasoning is otherwise sound engineering
discipline (enforce a shared bound at the shared resource, not at each caller)
and should not be weakened, but a reader following the "two paths" premise to
find the second one, or a future engineer adding a client WebSocket back
because the docstrings describe one as already present, would both be misled
by documentation describing an architecture the tree does not currently have.

### desktop-domain-swept-and-found-clean | low | credentials, filesystem authority, platform ACL, profile, migration, and settlement are each single-homed

The desktop package (`credentials.py`, `_filesystem_authority.py`,
`_platform_acl.py`, `profile.py`, `contract.py`, `migration.py`,
`settlement.py`) was read in full and carries an unusually high density of
explicit single-authority claims that were checked rather than taken on faith.
`credential_paths` in `credentials.py` states it is the one place the credential
filenames are declared and both the settings profile and the gateway resolve
through it; `derive_state_paths` in `profile.py` states the same for the
application-home layout and is in fact called from three sites
(`DesktopProfile.ensure`, the CLI serve path, and `desktop/migration.py`) with
the module's own comment already flagging, correctly, that the mkdir side of
that layout is NOT equally centralised - a MISPLACED-shaped observation the
module records about itself, so it is not repeated here as a new finding.
`_platform_acl.py`'s DACL and POSIX-mode primitives are the sole owner
`harden_credential_file` and `credential_file_is_owner_restricted` calls route
through, consumed identically by the gateway discovery credential and all
three desktop credential planes. `migration.py`'s `_apply_mutations` is
explicitly the one mutation core shared by the dashboard-spawned migrate
entrypoint and fresh-install initialisation, and reuses the checkpoint-pragma
authority this same campaign already flagged a THIRD, unguarded caller of
elsewhere (`checkpoint-pragma-drift-recurred`) - `migration.py`'s own comment
names that exact history. `settlement.py`'s bounded-retry callback is a fifth
retry/backoff shape in the tree, structurally similar to but distinct in
constants from the worker IPC flush retry; consistent with this campaign's
standing ruling that retry/backoff sites are separate failure domains each
entitled to its own settings, it is recorded as DISTINCT rather than folded
into the wall-clock-poll or retry findings above. No new duplicate declaration
was found in this domain.

### vault-stage-discovery-declared-three-times | high | one scan mechanism, one vocabulary, three independent sites

The `.vault/` stage-glob-and-collect mechanism is declared independently
twice, and the six-stage vocabulary it walks is restated a third time.
`src/vaultspec_a2a/context/metadata.py`'s `discover_context_refs` and
`src/vaultspec_a2a/graph/nodes/vault_reader.py`'s `build_initial_vault_index`
(backed by its module constant `_VAULT_STAGE_PATTERNS`) both walk the
identical six patterns - `.vault/research/*{tag}*.md`,
`.vault/reference/*{tag}*.md`, `.vault/adr/*{tag}*.md`, `.vault/plan/*{tag}*.md`,
`.vault/exec/*{tag}*/**/*.md`, `.vault/audit/*{tag}*.md` - each with its own
`glob.escape(feature_tag)` call, its own sorted glob, and its own
`relative_to(workspace_root)` conversion, to build what is structurally the
same per-stage path index under two different return shapes (a flat
`list[ContextRef]` versus a `dict[str, list[str]]`). Both are exercised
together, for the same run, in `src/vaultspec_a2a/control/thread_service.py`:
`discover_context_refs` seeds the one-time `ThreadMetadata.context_refs` at
thread creation, `build_initial_vault_index` seeds the per-turn `vault_index`
state at dispatch. The two declarations have ALREADY diverged in cap
semantics while sharing the same default value: `domain_config.max_context_refs`
(50) bounds the TOTAL across all six stages combined in
`discover_context_refs`, while `domain_config.vault_index_cap` (50) bounds
EACH stage independently in `build_initial_vault_index` - a reader changing
one constant expecting to change "the vault-scan cap" changes only half of
it, silently. Third, the six-stage ORDER itself - `research`, `reference`,
`adr`, `plan`, `exec`, `audit` - is restated a third time as
`src/vaultspec_a2a/context/stage.py`'s `PHASE_ORDER`, used by
`infer_phase_from_vault_index` to walk phases in reverse; it is hand-typed
rather than derived from either glob-pattern dict, and it is a DIFFERENT
vocabulary from `src/vaultspec_a2a/graph/enums.py`'s `PipelinePhase` StrEnum
(five members - no `reference` - the routing-purpose closed set), so a reader
cannot assume the two "phase" lists agree. Verdict DUPLICATE on the scan
mechanism and on the six-stage vocabulary, not on the two return shapes (a
`ContextRef` list and a mount-ready path index are genuinely different
consumer contracts and should stay two functions). Two of the three
declaring sites - `context/metadata.py` and `context/stage.py` - are in this
sweep's domain and could derive their stage list from one shared ordered
tuple; the third, `graph/nodes/vault_reader.py`, is outside it. Recorded
rather than actioned because a real fix needs to reach into `graph/`, and a
partial, context-only consolidation would leave the cap-semantics
divergence exactly as dangerous as it is today.

### token-estimation-two-heuristics-one-concept | low | not folded in, breadth not fully established

`src/vaultspec_a2a/context/token_budget.py`'s `estimate_tokens` (a
configurable `domain_config.chars_per_token` heuristic, default 4, used to
decide when `should_compact` trims `TeamState.messages`) and
`src/vaultspec_a2a/graph/nodes/vault_reader.py`'s use of LangChain's own
`count_tokens_approximately` (to bound mounted-document blocks against
`domain_config.mount_token_ceiling`) answer the same question - roughly how
many tokens will this text cost - with two different heuristics, in sibling
context-assembly code, for two different budgets. Not called DUPLICATE: one
counts a `Sequence[BaseMessage]` for a whole-state compaction decision, the
other counts individual text blocks against a per-turn mount ceiling, and
using the LangChain-provided counter for LangChain message objects is a
defensible independent choice rather than an accidental restatement. Recorded
because two mechanisms answering the same question with different heuristics
is exactly the shape a real drift would take, and because only two sites were
found this sweep - breadth was not established across the rest of the tree
for a third token-estimation site.

### context-and-team-swept-and-found-clean | low | persona composition, harness verification, and rule shadowing confirmed single-homed

Recorded for the negative space in this sweep's domain.
`graph/compiler.py`'s `_compose_persona_prompt` (the function the campaign
flagged as reachable from two compilers) was checked from the consumer side
with four differently-phrased searches for a second, independent prompt-
assembly site in `context/` or `team/`; every hit for persona/system-prompt
composition landed inside `graph/` (`compiler.py`, `worker.py`,
`supervisor.py`). This sweep's domain supplies INGREDIENTS - rules text via
`context/rules.py`'s `RuleManager.compile()`, anchoring text via
`context/anchoring.py`'s `build_anchoring_context`, the preamble via
`context/preamble.py`'s `build_context_preamble` - but composes none of them
into a final system message itself, so the composition site stays
single-homed even though its callers are many, confirming the lead rather
than contradicting it. `context/harness.py`'s `verify_harness` is the sole
consumer of `RuleManager` for readiness probing and the sole site checking
`vaultspec-core` CLI resolution via `shutil.which`. `context/rules.py`'s
workspace-shadows-bundled-by-name resolution documents itself as mirroring
`team_config`'s workspace-over-bundled principle, and it does - but the two
are DISTINCT mechanisms, not one restated: `RuleManager` unions a directory
of many markdown files with per-name override, while `team_config`'s
(now-consolidated, see the entry below) config loader picks the first of
exactly two file candidates per id. The recent `feat(presets): retire
provider policy from presets` change (540d7aef) removed
`[team.defaults]`/`[team.profiles.*]` blocks from every shipped preset TOML
without introducing any new duplicate declaration inside `team/` itself; the
model-resolution logic it moved lives in `providers/`, outside this sweep's
domain. The most valuable finding from the "recently changed code" lead was
inside `team/team_config.py` itself, unrelated to that commit: see the entry
below.

### two-tier-preset-discovery-rehomed | medium | REHOMED - one candidate-path builder now serves both loaders

`src/vaultspec_a2a/team/team_config.py`'s `load_agent_config` and
`load_team_config` independently hand-rolled the identical two-candidate
discovery order (`{workspace_root}/.vaultspec/{subdir}/{id}.toml` first,
then the bundled preset directory, first existing file wins), differing only
in the subdirectory name, the preset directory constant, the Pydantic
loader classmethod, and the not-found exception type. Verdict DUPLICATE on
the path-resolution mechanism, DISTINCT correctly kept apart on the
exception type (an `AgentConfigNotFoundError` and a `TeamConfigNotFoundError`
serve different callers and must not merge into one). Actioned: extracted
into a private `_resolve_preset_path(filename_id, workspace_root, *, subdir,
preset_dir) -> Path | None`, called by both loaders, which still raise their
own typed error when it returns `None`. Both discovery test classes
(`TestLoadAgentConfigDiscovery`, `TestLoadTeamConfigDiscovery`) and the full
`team/` suite (208 tests) pass unchanged; whole-tree `ty check` shows no new
diagnostic in `team/` or `context/`.

### service-json-candidate-list-now-exported | medium | closes the prior finding, verified and fixed

Re-verified the `service-json-candidate-list-reimplemented-in-control` finding
recorded above against current HEAD before acting, per this campaign's method:
`src/vaultspec_a2a/authoring/discovery.py` still built the ordered
`VAULTSPEC_ENGINE_SERVICE_JSON`-then-home candidate list in a private
`_candidates()`, and `src/vaultspec_a2a/control/health.py`'s
`probe_engine_discovery_freshness` still reconstructed the same two-entry list
inline rather than importing it, agreeing with the canonical order only
because nobody had changed one without the other. ACTIONED exactly as the
prior finding proposed: `_candidates()` is renamed to the exported
`service_json_candidates()` (added to `authoring/discovery.py`'s `__all__`),
`resolve_engine` now calls the exported name, and `control/health.py` imports
and calls it instead of restating the two-entry construction. Nothing about
the freshness classification changed - that half of the prior finding was
already correct and stays as `control/health.py`'s own distinct
non-blocking, no-HTTP contract. Verified by running
`src/vaultspec_a2a/authoring/tests/` filtered to the discovery suites (16
passed) and `src/vaultspec_a2a/api/tests/test_health_database_probe.py` +
`test_app.py` (14 passed, covering the `/health` route this function feeds),
plus a whole-tree `ty check`. The `ty` run is reported with a caveat rather
than a clean bill: three separate whole-tree runs in this session (by two
different agents) produced three different diagnostic sets on the same
nominal HEAD, which is concurrent-writer noise in this shared tree rather than
a stable signal - none of the three runs' diagnostics named
`authoring/discovery.py` or `control/health.py`, which is the narrower claim
actually verified here.

### cancel-vs-message-dispatch-failure-restoration-is-three-distinct-shapes | medium | a self-flagged thread that resolved to DISTINCT, not a fix

Followed up the dispatch-failure state-restoration thread flagged when the
permission/action-lease sweep closed, covering exactly the files newly in
scope here: `src/vaultspec_a2a/control/cancel_service.py`,
`src/vaultspec_a2a/control/message_service.py`, and (for comparison, already
swept but load-bearing context) `src/vaultspec_a2a/control/
direct_control_recovery.py`. All three react to a dispatch that could not be
confirmed delivered, and at first read they look like the same "undo the
requested-state write" concept spelled three ways. They are not - each
follows from what `src/vaultspec_a2a/thread/repair_policy.py`'s
`repair_state_for_action` sets for that action's own `"requested"` phase, and
that table is not free to change to make the callers converge.
`MESSAGE_FOLLOWUP_REQUESTED`'s `"requested"` transition sets `repair_status`
to `HEALTHY` - a no-op resting state - so `message_service.py`'s definite-
non-delivery arm correctly does the minimal thing: call the already-shared
`record_undelivered_dispatch` (`control/repair_transitions.py`) to attach a
repair reason without moving `repair_status` away from where it already
rests, exactly as `control/clarification_service.py` does for the same
reason. `CANCEL`'s `"requested"` transition instead sets `repair_status` to
`CANCEL_PENDING`, a real marker asserting a cancel is in flight - so leaving
it in place after the worker demonstrably never received the cancel would
report a "ghost cancel_pending state" (the exact phrase in
`cancel_service.py`'s own covering test,
`test_failed_cancel_dispatch_restores_repair_state`, in
`src/vaultspec_a2a/api/tests/test_endpoints.py`). `cancel_service.py`
therefore captures a `_PriorRepairState` snapshot before requesting the
cancel and restores all four fields on definite non-delivery - a genuine undo
`record_undelivered_dispatch` cannot express, because that helper deliberately
leaves `repair_status` exactly as the pre-dispatch transition set it.
`direct_control_recovery.py`'s `_restore_requested_state` is a third shape
again: during REDRIVE of an already-durable action after a crash, it does not
undo to "before the original request" (there is no such snapshot to restore
in a recovery pass) and does not merely attach a reason - it RE-APPLIES the
same `"requested"` transition (`mark_cancel_requested` /
`mark_message_followup_requested` / `mark_permission_response_requested`) so
a redrive that fails to acquire or dispatch leaves the row in the same
"requested" posture a fresh request would have produced. Verdict: three
DISTINCT operations, correctly separated, each dictated by its own action
type's repair-state semantics rather than by which module happened to write
it. Not actioned, because there is nothing to converge - flattening any pair
of these would either leave a `CANCEL_PENDING` ghost, silently move a healthy
follow-up's repair status, or break the redrive path's idempotent re-stamping.

### control-service-domain-partially-swept | low | drain, worker spawn/health, circuit breaker, and the snapshot pipeline are single-homed; one prior finding unconfirmed

`src/vaultspec_a2a/control/drain.py`'s `DrainGate` is the sole admission/drain
authority, stating so in its own module docstring, with one caller
(`api/app.py`'s shutdown path and `api/routes/admin.py`'s shutdown endpoint)
closing it and one reader (`gateway.py`'s admission path) consulting it - no
second gate found. `probe_worker_health` in
`src/vaultspec_a2a/control/worker_management.py` is confirmed still the
single worker-health primitive its own docstring claims: the watchdog, the
boot/spawn paths, and `control/health.py`'s `/health` route all call the same
function, and both call sites that assert "healthy" enforce the identical
exact-200 rule, so they structurally cannot disagree - this re-confirms the
"one primitive" claim the earlier `swept-and-found-clean` entry made for this
concept, on the file now newly in scope. `WorkerCircuitBreaker` in
`circuit_breaker.py` has one declaration, consumed only through
`control/dispatch.py`'s `safe_dispatch`, the single dispatch entry point
every service in this domain and the previously-swept permission domain calls
through. `control/snapshot.py` (`enrich_snapshot_from_state`, from LangGraph
state), `control/projection.py` (`apply_checkpoint_projection` and durable-vs-
checkpoint reconciliation), and `control/thread_state_service.py`
(`capture_thread_state`, the orchestrator) are three cooperating stages of one
pipeline, not competing declarations of one concept - each is called exactly
once, in sequence, from `thread_state_service.py`. The `state=active` versus
`state=all` run-listing split in `api/routes/gateway.py`'s
`active_runs_endpoint` is explicitly documented in the route's own docstring
as two different questions (live discovery, capped, versus history, paginated
and wider) rather than a duplicate, and the `state=all` branch consumes
`ThreadSummaryData` already reconciled by `control/thread_service.py`'s
`list_threads_service` rather than re-deriving repair/execution state from
the raw thread row, so there is no second reconciliation to drift from the
first.

Not established: an earlier finding on this audit
(`thread-metadata-decode-reimplemented`) named `control/thread_service.py` as
one of five sites decoding the durable `thread_metadata` JSON column to
extract `workspace_root` with inconsistent error handling. Reading
`thread_service.py` in full for this sweep found only one JSON-decode of that
column, `_parse_thread_summary_metadata`, and it extracts `feature_tag`,
`source_branch`, and `callee` for run-listing display - not `workspace_root`,
and not feeding a dispatch. Every `workspace_root` reference in this file
traces to `process_metadata`, which validates a typed, already-structured
inbound request field rather than decoding the durable column. This may mean
that part of the earlier finding has since been fixed by another lane, was
imprecise about which file carried the site, or names a function this sweep
did not recognise as the same pattern - recorded as unconfirmed rather than
silently left standing or rewritten, per this audit's rule against editing a
settled entry.

### stdio-json-rpc-client-reimplemented-for-codex | high | one generic mechanism, two independent implementations

`src/vaultspec_a2a/providers/_acp_protocol.py`'s `process_stdout_loop` and
`dispatch_packet`, together with the response-future map the ACP session
builder populates per call in `src/vaultspec_a2a/providers/_acp_session.py`,
implement a generic asynchronous JSON-RPC-over-stdio client: read
newline-delimited JSON frames from a subprocess's stdout, route a frame
carrying `result`/`error` to a pending request keyed by id in a future map,
route an unsolicited frame to its own handling path, and on stream EOF fail
every still-pending future and push a sentinel so a blocked consumer does not
hang forever. `codex_chat_model.py`'s `_CodexAppServerClient` implements the
identical mechanism from scratch, independently: `_read_loop` reads the same
newline-delimited frames, `_dispatch` routes a response frame (has `id`, no
`method`) to a future in `self._pending`, routes a notification (has `method`,
no `id`) to `self.notifications`, and on EOF `_fail_pending` fails every
pending future exactly as the ACP finally-block does, followed by pushing its
own `_STREAM_CLOSED` sentinel onto the notification queue - the same shape,
the same ordering, the same reasoning, arrived at twice. `request`/`notify`/
the outbound `_send` writer duplicate the ACP session builder's
`ctx.response_futures[rpc_id] = asyncio.get_running_loop().create_future()` /
stdin-write-plus-drain idiom the same way. Verdict DUPLICATE on the mechanism,
not on the dialect. What must NOT be merged is already correctly separate on
each side: ACP's `dispatch_packet` additionally handles a server-initiated
`session/update` notification stream with capability-gated dispatch back to the
agent (tool calls, mode changes, plan updates - genuine ACP-only semantics),
while Codex's app-server apparently never issues a server-initiated request at
all, so `_dispatch` only ever needs to refuse one with a bare method-not-found.
Those dialect-specific bodies are correctly provider-owned. What is duplicated
is everything beneath the dialect: the frame loop, the id-to-future bookkeeping,
the fail-all-pending-on-EOF discipline, and the sentinel-on-close signal to an
otherwise-blocked consumer. Teardown itself is NOT duplicated - both sides
already route through the same `kill_process_tree`
(`src/vaultspec_a2a/providers/_subprocess.py`) and the same
`run_independent_cleanups` (`src/vaultspec_a2a/providers/_cleanup.py`) for the
two-fold process-tree-plus-reader-task shutdown, which is the shape a
consolidation of the read side should match: a shared low-level stdio JSON-RPC
client (send, notify, request-with-future, a read loop keyed on id-vs-method
presence, EOF failure and closure signalling) that each provider's own
dialect-specific dispatcher sits on top of, the same layering `_acp_protocol.py`
already keeps deliberately separate from `_acp_rpc_handlers.py` via its
passed-in handler map rather than an import, specifically to avoid a circular
import - the same discipline a shared client module would need to preserve.

### config-home-roots-correctly-distinct | low | protected pair, not a new finding

`src/vaultspec_a2a/providers/_config_home_roots.py` and
`src/vaultspec_a2a/providers/_codex_config_home.py` read as a duplicate pair by
name alone. They are not: the roots module owns WHERE a per-run config home
lives and HOW an abandoned one is swept by age, generically, for any CLI
lane's prefix; the Codex module is the one caller that still needs an isolated
per-run home at all, and its own docstring records that the ACP/Claude lane
that used to be the sibling caller was retired in favour of running in the
operator's ambient config home under a different confinement contract. Recorded
because the name pair invites exactly the wrong merge on sight, not because
either declaration is fragmented.

### checkpoint-pragma-fix-holds-but-a-fourth-touchpoint-bypasses-it | medium | the "two checkpoint paths" framing is now stale

Following up on `checkpoint-pragma-drift-recurred`: the fix holds. All three
checkpoint-writing paths this sweep found now call
`checkpoint_pragmas()` (`src/vaultspec_a2a/database/checkpoint_schema.py`) -
the LangGraph saver in `src/vaultspec_a2a/database/checkpoints.py`, the
identity installer inside `checkpoint_schema.py` itself, and
`src/vaultspec_a2a/desktop/migration.py`'s `_setup_checkpointer`, whose comment
now narrates the exact prior drift ("This path had restated it and drifted
anyway: it hardcoded the busy timeout instead of reading the configured one,
and omitted the foreign-key pragma") as the reason it now imports the helper.
Good - but a fourth touchpoint on the checkpoint store's connection exists that
none of the audit's counts named: `src/vaultspec_a2a/database/admin.py`'s
`_clear_checkpoint_store`, reached from the `admin clear` verb, opens
`settings.checkpoint_sync_url` through `_administrative_engine`, whose connect
listener is `_apply_sqlite_pragmas` - a SECOND, independently declared pragma
set built for the APPLICATION database's synchronous admin connection
(`foreign_keys=ON` and `busy_timeout`, deliberately omitting `journal_mode=WAL`
because that pragma is file-header-level and the admin module's own docstring
reasons the async engine already fixed it for that store). `_administrative_engine`
is reused verbatim for the checkpoint URL at `admin.py:376`, so the checkpoint
store's clear path is governed by a declaration that was never written with the
checkpoint schema in mind and has no relationship to `checkpoint_pragmas()` at
all.

Verdict DUPLICATE-adjacent rather than a live functional gap today: `foreign_keys`
and `busy_timeout` ARE applied (satisfying the per-connection half of the
contract `checkpoint_pragmas()` documents), and `journal_mode` is safe to omit
in the ordinary sequencing, where the checkpoint file already carries WAL in its
header from whichever of the three canonical writers created it first - the
same reasoning `admin.py` already relies on for the application store. The real
risk is the one this whole cluster keeps illustrating: `checkpoint_pragmas()`'s
own docstring still says it exists "so the two checkpoint paths cannot drift
from each other," and that count was already wrong before this sweep - there
are three canonical writers, plus this fourth path that does not consult the
declaration at all. If the checkpoint posture ever gains a fourth pragma, three
call sites pick it up by importing the function and this one does not, silently,
because it was never wired to notice. The fix is small: `_clear_checkpoint_store`
resolving its engine's connect listener from `checkpoint_pragmas()` instead of
`_apply_sqlite_pragmas`, the same way the three canonical writers already do.

### non-terminal-thread-sweep-omits-the-deletion-sink | high | live gap, not merely a duplicate risk

`src/vaultspec_a2a/thread/enums.py` declares `NON_ACTIVE_STATUSES` as
`TERMINAL_STATUSES | {ARCHIVED, DELETING}` and documents exactly why `DELETING`
belongs there: "a durable teardown marker, not a settled outcome... must never
be dispatched, cancelled, or messaged again." `src/vaultspec_a2a/thread/transitions.py`
enforces the same fact structurally - `ThreadStatus.DELETING` maps to an empty
transition set, a declared lifecycle sink with zero valid outbound moves.

`list_non_terminal_threads` in `src/vaultspec_a2a/database/thread_repository.py`
does not consult either. It hand-rolls its own exclusion literal - `NOT IN
[COMPLETED, FAILED, CANCELLED, ARCHIVED]` - which is `TERMINAL_STATUSES |
{ARCHIVED}` short exactly one member of `NON_ACTIVE_STATUSES`: `DELETING`. Its
one caller, `reconcile_threads_on_startup` in
`src/vaultspec_a2a/database/reconciliation.py`, runs this query on every gateway
boot to find threads needing repair attention. Traced forward: the snapshots it
builds feed `compute_reconciliation_actions` in
`src/vaultspec_a2a/lifecycle/reconciliation.py`, which has no `DELETING`
awareness anywhere in it - confirmed by grep, the token does not appear in that
module - so a thread mid-teardown that also happens to have a pending
permission or clarification, or sits in `CANCELLING`, is scored exactly like
any other in-flight run and can be assigned a `new_thread_status`
(`INPUT_REQUIRED`, for the pending-answer branch). `execute_reconciliation`
then calls `update_thread_status`, which calls `validate_transition(DELETING,
target, ...)` against the empty transition set `transitions.py` declares - a
call this codebase's own structural authority defines as always illegal from
`DELETING`. The action would raise `InvalidTransitionError` mid-boot
reconciliation for a run that should have been invisible to this sweep
entirely; a branch that only sets `repair_status`/`execution_readiness` without
a status change writes to a row the deletion saga - the one caller
`mark_thread_deleting`'s own docstring names as sole owner - may be tearing down
concurrently across the checkpoint, artifact, and control stores at that exact
moment.

Verdict DUPLICATE on the vocabulary (a fourth ad hoc restatement of a status set
this project has already found drifting three times elsewhere in this audit),
but the severity is HIGH rather than the usual future-drift risk: this is
already wrong today relative to the codebase's own declared invariant, reachable
on ordinary gateway restart, and requires no unusual timing beyond a thread
being mid-deletion (or newly `DELETING`) across a boot - the ordinary case a
deletion saga spanning a HTTP request and a background teardown is exactly
built to survive. The fix is narrow: derive the exclusion from
`NON_ACTIVE_STATUSES` (or `TERMINAL_STATUSES | {ThreadStatus.ARCHIVED,
ThreadStatus.DELETING}` if the query needs the members rather than the wire
values) instead of the hand-typed four-item list, so a future member added to
either canonical set is inherited rather than requiring a fifth site to
remember it independently.

### correction-stdio-json-rpc-count-is-four-not-two | medium | the same mechanism recurs a second time, narrower

Extends `stdio-json-rpc-client-reimplemented-for-codex` rather than replacing
it; that entry's verdict and recommended shape both stand. A second, narrower
pair of the identical mechanism was found in the catalog-discovery lane, sitting
beside the already-recorded stderr-metering triplication
(`catalog-discovery-output-budget-triplicated`) in the same files.
`src/vaultspec_a2a/providers/acp_catalog.py`'s `_request`/`_read_response` and
`src/vaultspec_a2a/providers/codex_catalog.py`'s `_request`/`_read_response` are
near byte-identical: write a JSON-RPC frame plus newline to stdin and drain,
read stdout lines up to a bounded frame count matching the request id, raise a
module-local protocol error on an `error` field or a non-object `result`, and
budget every line's bytes through the same `_OutputBudget`. `_cancel` in both
files is the identical two-line cancel-and-suppress helper, word for word. This
is a ONE-SHOT variant of the mechanism (single in-flight request per call, no
pending-id map, no notification stream) rather than the long-lived multiplexed
session variant the parent entry describes, which is why it was not folded into
that entry directly - but it is the same primitive at smaller scope, and the
same ACP/Codex axis. The count across the package is therefore four
independent hand-rollings of one mechanism, two long-lived (the turn-driving
session in `_acp_protocol.py`/`_acp_session.py` and `codex_chat_model.py`'s
`_CodexAppServerClient`) and two one-shot (`acp_catalog.py` and
`codex_catalog.py`'s discovery probes), not two. A consolidated low-level
client should offer both call shapes - fire a request and await one matching
frame, or multiplex many in flight against a pending map - since the discovery
probes have no use for session bookkeeping they would otherwise have to carry
and ignore.

Not established: whether `kimi_catalog.py` and `openai_catalog.py`, the other
two catalog modules, carry a fifth and sixth variant. `kimi_catalog.py` reads
`catalog_from_provider_list`/`_read_bounded` rather than `_request`/
`_read_response`, and `openai_catalog.py` calls out to an HTTP models endpoint
rather than a subprocess at all, so neither was assumed to match on name alone
- confirming or ruling out either needs a closer read this sweep did not reach.

### vault-index-cap-contradicts-its-own-description | high | one number, two meanings, both live for one run

Split out of `vault-stage-discovery-declared-three-times`, whose PATTERN half is
now rehomed. This half is a behaviour question and was deliberately left out of
that change so it could not be hidden inside a mechanical consolidation.

Two caps in `src/vaultspec_a2a/domain_config.py` share the default 50 and
describe themselves as totals. `max_context_refs` says "Maximum context
references included in a single graph invocation" and is enforced as one:
`src/vaultspec_a2a/context/metadata.py` stops accumulating once the running
total reaches it. `vault_index_cap` says "Maximum vault index entries surfaced
to the agent per turn" but `src/vaultspec_a2a/graph/nodes/vault_reader.py`
applies it PER STAGE, slicing each stage's matches independently. With six
stages that is up to 300 entries surfaced under a setting that claims 50.

The implementation therefore contradicts its own declared contract, and the
divergence is invisible from either side alone: read the config and both caps
look equivalent; read either call site and it looks correct locally. Both run
for the SAME run - context refs at thread creation, vault index at dispatch - so
one run carries two differently-bounded views of the same vault.

Not actioned, and the reason is the ambiguity rather than the size. Making the
cap a total would REDUCE what an agent sees, which is a product decision about
grounding breadth; making the description per-stage would legitimise a bound
that can surface six times its stated number while `mount_token_ceiling` is the
only thing standing between that and the context window. Either is defensible;
choosing one silently is not. Whoever owns grounding breadth should rule, and
the fix is then a one-line change plus a description that matches it.

### command-classification-metadata-shape-restated | medium | an untyped five-key contract, agreed by convention across five classifiers

`src/vaultspec_a2a/providers/factory.py` resolves each subprocess provider's
launch command through its own classifier -
`_classify_gemini_command`, `_classify_acp_command` (and its
`_classify_capsule_acp_command` sibling), `_classify_codex_command`,
`_classify_kimi_command` - and every one returns
`tuple[list[str], dict[str, str]]`, where the dict always carries the same five
keys: `runtime_authority`, `command_origin`, `command_kind`,
`command_executable`, `command_target`. Nothing declares this shape once; each
classifier builds it as inline dict literals, roughly a dozen times across the
file. `classify_provider_command`, the dispatcher, and two of the catalog
discovery functions (`_discover_gemini_catalog`, `_discover_codex_catalog`
around lines 710 and 772) all branch on the same magic string sentinel,
`meta.get("command_origin") == "fallback_cli_name"`, repeated five times with
no shared constant. `ProviderFactory`'s model-construction branches - one per
provider, five call sites - then unpack the dict field by field
(`command_meta["runtime_authority"]`, `command_meta["command_origin"]`, and so
on) into keyword arguments for `AcpChatModel`/`CodexChatModel`/the other chat
models, which each declare the same five fields independently rather than
accepting one typed bundle. No `TypedDict`, dataclass, or `NamedTuple` exists
for this shape anywhere in the module or its imports - confirmed by search, not
assumed. Verdict DUPLICATE on the vocabulary, in the same shape this audit has
already named for a wire-event catalog and a terminal-status set: the contract
holds today only because every writer and every reader happened to spell the
same five keys and the one sentinel value identically. A classifier that
misspells a key, drops one, or a future provider added without matching the
existing five would fail at the unpacking call site with a bare `KeyError`
rather than at a type check, and a call site that reads only four of the five
keys would silently under-populate a model's provenance fields with no error at
all. The fix is a shared `TypedDict` (or frozen dataclass) for the classified-
command result, with `FALLBACK_CLI_NAME` as a named constant the dispatcher and
the two discovery functions import instead of retyping the string, so a missed
key or a typo'd sentinel fails a type check instead of a runtime lookup.
