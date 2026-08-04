---
tags:
  - '#audit'
  - '#canonical-homes'
date: '2026-08-04'
modified: '2026-08-04'
body_schema: 'body-v1'
body_hash: 'sha256:23e2db5a4914a7b80d3c3b6e7f7c8693ab36afc3acb38c3645cb56ec3e5cb163'
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

### correction-the-harness-wait-is-distinct | high | the deadline cluster had no duplicate at all

The deadline entry recorded three policies as one duplicate and two distinct,
naming the service harness's generic wait as the one real move. That is wrong and
is corrected here. All three are DISTINCT, and the reason is not the one that
entry anticipated.

The anticipated blocker turned out not to apply: with no fingerprint to touch,
the progress module's idle window bounds the whole wait, so it expresses the
harness's budgets exactly. The real reasons are three, and the last is decisive.
The stated premises are opposites - the progress module exists because a fixed
clock is wrong for a live model turn, while the harness waits on a stack boot
where a bounded wait is correct and a stack that has not booted is broken rather
than slow. The exception TYPE is control flow rather than a label: the boot retry
path keys on the boot-specific error, so a live-but-unready gateway fails loudly
instead of being retried, and a contract test already pins that a
container-managed wait must not escalate to it because there is no exit status to
report. And decisively, the harness swallows probe exceptions into a last-error
while the progress helper propagates whatever its poll raises - so routing the
harness probes through it would end the wait on the first connection refusal,
which occurs on essentially every boot before the gateway has bound. The
rehoming would not have degraded; it would have failed on its first poll, every
time.

Collapsing them would require parameterising the progress module with an error
vocabulary and an exception-tolerance policy, at which point it stops being the
narrow honest thing its docstring describes. A partial extraction was also
declined for the right reason: the harness needs its log tail in both the death
and the timeout message, so sharing half would put one coherent thing in two
modules - this campaign's failure mode arriving from the other direction.

Two facts from the same investigation. The harness wait is not duplicated at all:
one definition, one consuming package, and what made it look otherwise was
resemblance to a neighbour rather than a second copy. And the broader inventory
of roughly twenty wall-clock poll loops is not one concept either - they wait on
a pid to die, a file to appear, a port to answer.

### progress-semantics-for-certification-budgets | medium | offered, deferred, not dropped

Raised while investigating the above and correctly not taken. The service
harness's readiness budgets are fixed wall clocks of the exact kind the progress
module was built to replace, and on a loaded machine or a cold image pull they
can fail a stack that was merely slow. Adopting progress semantics there may well
be right. It is recorded as a candidate for its own decision rather than folded
into this campaign, because it is a behaviour change to certification timing
wearing a rehoming's clothes - the same trap as converting the gateway readiness
budget, which was declined earlier for the same reason.

### json-assertion-helper-family | high | twenty-five declarations, and a name-alike that must not join them

A four-function family for asserting the shape of a service response body -
narrowing to an object, to a list of objects, to required text, to a required
object, each taking the value and a locator string - is declared about
twenty-five times across eleven test files. Duplication was proven rather than
asserted: three declarations compared side by side are byte-identical apart from
docstring wording, with the same body, the same error types and the same message
strings. Two files carry variant parameter spellings of the same functions, which
is part of why the family was hard to count at all and is folded in rather than
excluded.

The guardrail matters more than the cluster. A same-named family exists in the
provider protocol modules and is a DIFFERENT concept: it narrows an optional JSON
value inside production protocol handling, not a test assertion over a service
response. A sweep keying on the name would merge production narrowing with test
assertions - the flattening class this campaign keeps coming close to
committing. Recorded before the move, so the boundary is written down where the
mover will see it.

### the-inventory-was-wrong-a-fifth-time | medium | issued as four files, re-derived as eleven

This cluster was handed over as "three service tests plus acceptance" and
re-derived from source as twenty-five declarations across eleven files. That is
the fifth count in this campaign to be materially wrong when first issued, across
four different concepts and several readers. The standing rule holds and is
earning itself: re-derive immediately before the commit that closes a cluster,
and treat any list - including one from the orchestrator - as provisional.

### too-many-lanes-in-one-worktree | medium | a coordination finding, and it is the orchestrator's

Three of one lane's last four pickups were already occupied by another lane
working in the same files, and two clusters were blocked simultaneously: one
entirely, because a complete move spanned three modules and two were held; one by
a single file out of eleven. No lane did anything wrong - the assignments were
made by concept while contention happens by FILE, and in a single shared worktree
those are different partitions. The mitigations that worked were sequencing
rather than parallelism: asking the holding lane to land one file as its own
commit ahead of batching, and refusing the partial move that would have left one
declaration alive out of eleven. Recorded as an orchestration finding because the
cost was real - a productive lane idle twice - and the cause was assignment
granularity, not any lane's conduct.

### correction-the-assertion-family-was-not-one-cluster | high | the count was mine, and the rule caught it

The entry above described a four-function family as roughly twenty-five
byte-identical declarations. That was derived by comparing three declarations and
generalising, and the three happened to share a dialect. Re-derived at commit
time, the family splits: the two narrowing functions raise one error type in four
files and a different one in five, one module SELF-TESTS its error type in three
places so the vocabulary is asserted behaviour rather than incidental drift, one
variant treats an absent value as an empty list, and the acceptance tier's
same-named readers take a bare value rather than a body-and-field pair with one
additionally requiring non-empty text. Four contracts wearing four identical
names.

Only the provably exact subset was landed: two functions, eight declarations
across four files, byte-identical bodies and failure text, nothing self-testing
them, now in one home with the old definitions deleted and seventy-nine call
sites reaching it. The neighbours were left, and the new module records WHY -
an unexplained omission is what invites the next reader to finish the job by
flattening a dialect two suites assert on.

Recorded as a correction because it is the fifth wrong count in this campaign and
the first raised by the lane that made it, using the rule it had been asking
others to follow. A re-derivation that catches your own number is the rule
working; one that only ever catches someone else's is a habit of suspicion.

### the-json-narrowing-home-already-exists | high | and one test already imports it

The open question was whether the test-tier narrowing should raise an assertion
error rather than a type error, and it is answered by a fact neither side had
checked: the production closed-JSON contract module ALREADY exports the three
narrowing functions, and one service test already imports them from it directly.
So the type-error vocabulary is not a test-suite convention that drifted - it is
the production contract's own, and the self-tests are asserting that contract
rather than a local habit.

The ruling follows from the fact rather than from the argument: converge the
remaining sites onto the existing home and keep its vocabulary. Minting a second
test-tier family beside a canonical home already in use would manufacture the
exact fragmentation this campaign exists to remove, and the self-tests then need
no amendment at all - which is the signal that the move is toward the real home.
The sites that change error type are a behaviour change and must be declared as
one, justified as convergence onto an existing production contract rather than a
new invention. Two carve-outs stay out of it: an optional-list variant is a
different contract and survives only as its own named function, and the
acceptance readers' different shape and non-empty requirement need verifying
before any fold.

This also converges with the untyped-narrowing cluster recorded earlier - ten
production declarations under four private names across four layers. That cluster
named this same module as its natural home. The two are one home, approached from
the test tier and the production tier independently.

### correction-the-narrowing-ruling-would-have-dropped-validation | critical | the worst near-miss in this campaign

The ruling recorded above - converge the test-tier narrowing onto the production
closed-JSON contract and keep its error vocabulary - is WRONG and is reversed
here. It would have caused real harm, and it was made from a fact verified by
checking the wrong file for the wrong property.

Three things are true and none of them were established before the ruling. The
module cited as pinning the production vocabulary declares no local narrowing at
all: it imports the production helpers, so its assertions target those, not a
test-tier family. A different module - unchecked at the time - declares two local
helpers and self-tests them with five assertions matching on the locator, so the
ASSERTION vocabulary is the one with real coverage. And decisively the two are
not the same operation: the production helper is an isinstance narrowing over an
already-typed union with no validation, while the test-tier helpers run a
recursive validator over an untyped decoded payload.

So the ordered convergence would have replaced deep payload validation with a
shallow cast across nine files. Test rigour would have dropped silently and no
type checker would have objected. That is exactly the flattening this inventory
exists to prevent, ordered by the person maintaining it, and caught only because
the implementing lane re-derived from source instead of executing the
instruction.

The corrected shape: a canonical narrowing pair in the test-support package
raising the assertion vocabulary and returning the precise recursive object type,
which leaves the already-precise sites untouched and treats the looser ones as
the drift - declared as a tightening rather than discovered as one. Two
behavioural variants stay separate: one PARSES raw bytes rather than narrowing a
decoded value, and one treats an absent value as an empty list. Neither becomes a
flag on the shared function.

The earlier DISTINCT flag on this pair was right, but the reason first given -
"different subject" - was too weak to protect it. The durable reason is
"different operations on different input types", and only that phrasing would
have stopped the ruling this entry reverses.

### graph-compiler-swept-and-clean | low | the discipline is already applied there

Reported as a clean verdict rather than a manufactured move. The control-character
stripper has one home and is imported by its consumers; the length caps are
DERIVED from the wire models rather than restated, and the test imports the
deriver rather than repeating the numbers. That area already applies the practice
this campaign is installing elsewhere, which is worth recording both as coverage
and as evidence the practice is achievable in this codebase rather than
aspirational.

### narrowing-cluster-settled-by-running-it | critical | seven converge, two must not

The reversal above was over-broad and is narrowed here. It claimed converging the
nine test-tier narrowing sites would drop validation. Two would; seven would not,
and the line between them was found by EXECUTING the three candidates against one
probe value rather than by reading any of them:

- a validator parameterised on an untyped object value ACCEPTS a dict whose value
  is not JSON
- one parameterised on the recursive JSON object type REJECTS it
- the production isinstance narrowing ACCEPTS it

So seven sites were never validating anything the production narrowing does not.
An untyped object value accepts everything, and the validator was only ever
proving "a dict with string keys" - which is precisely what the isinstance check
proves. Converging those seven is a pure deletion with no behavioural change.
The two that genuinely deep-validate the recursive shape are exactly the two that
annotate the precise return type, so the return type and the validation depth are
the same distinction seen twice - which is why the cluster read as a dialect
split and was not one. Those two stay, because converging them would silently
drop a real assertion from two live-provider suites.

Three claims in this one cluster were each wrong in a different direction - the
original ruling, its reversal, and the implementing lane's dialect reading - and a
single executable probe settled all three. Recorded as the strongest argument in
this campaign for running a candidate rather than reading it: every reader
involved was experienced, careful, and looking at the same source, and none of
them got it right from inspection.

The consequence for the production home is favourable. The convergence puts seven
consumers onto the closed-JSON contract module before the ten-site production
cluster commits to it, which turns a proposed canonical home into a load-bearing
one, and it needs an object-list reader added there that the production cluster
will want anyway.

### a-green-type-check-is-not-a-green-import | high | the gate that caught what types could not

During the payload-reader convergence a blanket annotation replacement rewrote
one file's own local alias into a self-referential definition - the name bound to
itself. The whole-tree type check passed clean over it. Collection failed
immediately with a name error. Recorded as a standing lesson for every
annotation-heavy move in this campaign: type checking and import are different
gates, a type checker will happily accept a binding it can resolve statically,
and only actually importing the module proves it loads. Both gates are
load-bearing here, and a move verified by types alone is not verified.

The same convergence also sized the invariance risk that had made it worth
pausing for: the fallout stayed ENTIRELY inside the nine files being edited,
peaking at sixty-one diagnostics mid-repair with none escaping into other
packages. The pause was still right - the size was unknowable in advance, and the
condition for stopping was never triggered because it did not need to be.

### payload-readers-converged | high | seven deleted, two kept, five self-tests unchanged

Closed. The narrowing pair now has one declaration in the test-support package,
validating and raising the assertion vocabulary, with seven files' local copies
deleted rather than wrapped. Two variants survive by design and are visible as
such: one PARSES raw bytes rather than narrowing a decoded value, and one maps an
absent field to an empty list. Neither is a flag on the shared reader.

The confirming signal is the one named in advance: the five self-tests that pin
the dialect pass UNCHANGED, and were run directly through the marker override
rather than left deselected. Converging toward the real contract required no test
to be rewritten, which is what distinguishes a move toward a home from a move
away from one.

Two behaviour changes were declared in the commit rather than discovered
afterwards - five suites move error vocabulary, seven tighten their return type -
and the mis-attribution that nearly prevented all of this is recorded with them:
the type-error assertions elsewhere in that package target the PRODUCTION
readers, not the test-tier family, which both the implementing lane and this
audit had misread.

### correction-the-seven-were-tightened-not-deleted | high | the audit described a plan, not the landing

The narrowing entry recorded seven sites as "a pure deletion with no behavioural
change". That was true of the plan under discussion - converging onto the
production narrowing, which accepts a dict whose values are not JSON. It is not
what landed. The convergence went to a test-support canonical that DEEP-VALIDATES,
so those seven were TIGHTENED from an untyped object value to the precise
recursive type, and the two already-precise sites came along unchanged.

The landed result is better than either position argued for: one home, one
dialect, and every site validating at the strict depth rather than seven keeping
a check that only ever proved "a dict with string keys". Recorded because the
better answer came from neither of the two positions being defended, and because
the implementing commit declared the tightening while this audit did not - which
makes it the audit's defect rather than the move's.

### an-instruction-declined-with-evidence | medium | the rule applied against the person holding it

An instruction to add a list reader to the production contract module was
refused, correctly, on the grounds that issued it. The rationale had been
"consumers first" - a reader with proven consumers is how a canonical home is
established. By the time the instruction was read, the consumers had landed
somewhere else, so the reader would have arrived with none, which is precisely
the "canonical home with nothing converged onto it" failure this inventory
condemns elsewhere. A second fact had also moved: another lane had begun
implementing in that module, adding a near-named reader, so a seventh would have
been both speculative and a collision.

Recorded as a working practice rather than an incident. A lane that refuses an
order with evidence is doing the same job as one that reports a false lead
instead of manufacturing a move, and this campaign has now had both from the same
source. The orchestrator's instructions have been wrong or stale often enough
that treating them as provisional is the correct default, not insubordination.

### output-budget-triplicated-with-its-home-already-built | medium | designed, handed over, not started

An output-size budget for discovery subprocesses is declared three times across
the per-provider catalog modules, identical apart from the error type raised and
carrying the same limit. The canonical home already exists and already declares
BOTH seams the shared form needs - the protocol it satisfies and the error
factory that keeps each lane's message prefix - because the lane that extracted
the neighbouring single-frame read established that convention. Only the concrete
class is missing. The stderr drain is duplicated in two of the three on the same
axis, and with the budget raising whatever the caller's factory produced, the
shared form catches broadly and re-raises after killing the process tree.

Verified before handover: all three files clean, the triplication present at the
stated locations, both seams present in the home, and no import cycle blocking
the shared drain from reaching the tree-kill.

The carve-out is the valuable part. A same-shaped reader in the third module is
NOT a third copy: it accumulates and returns its bytes because that lane parses
its own standard output, while the other two DISCARD - which is the entire point
of a drain, since a noisy child's output must be charged against the budget
without a megabyte of it being retained. Making the shared form accumulate would
defeat the purpose it exists for. Sibling, not survivor.

Recorded as designed-not-started because the analysing lane reached the end of
its context and handed over a complete design rather than beginning a three-file
production refactor it could not finish. That is the behaviour this campaign
wants at a context boundary, and it is the third time today a handover has cost
nothing while a half-landing would have cost a great deal.

### wire-event-vocabulary-declared-twice | critical | the duplication has already shipped a bug, and the code says so

The strongest finding of the campaign, and the only one where the codebase
already documents the defect the duplication caused.

The progress-stream frame vocabulary is a closed enumeration of eleven kinds in
the API schema package. The worker-to-gateway serializer restates all eleven as
string literals in a dispatch statement, with no import between them - verified,
eleven literal returns against eleven enumeration members. The class-to-kind
dispatch is genuine per-event knowledge and must stay; only the STRINGS are
duplicated.

Three things raise this above every other open cluster:

The enumeration's own module states the rule being broken. Its header says the
neighbouring vocabularies are "imported (not duplicated) where needed" - so the
duplication is against a written instruction sitting in the file being
duplicated.

The defect class has already shipped here, and the serializer's own docstring
records it: adding an event kind without adding it to the dispatch is "silent,
and is exactly how the clarification nudge shipped undeliverable". An event with
no case relays with no kind, the gateway's closed catalog projects an untyped
frame onto identity keys, and subscribers receive it stripped of meaning - while
the worker-side emission still looks healthy, so an in-process test of the
emitter passes. Silent by construction, and on the far side of a process
boundary where nothing compares the two lists.

It is the same shape as the terminal-status vocabulary already fixed in this
campaign: a closed vocabulary copied by hand, which then gains or loses members
with nothing to say so.

What makes it non-trivial and why it was reported rather than taken: the IPC
package imports nothing from the API package today, and importing upward would
invert the layering. There is no cycle in practice - the enumeration module
imports only the standard library - but absence of a cycle is not correctness of
layer. The likely honest fix is to move the enumeration DOWN to where the events
it names are defined, then have both the schema package and the serializer import
it. That is a layering decision touching the served API schema surface, and the
destination must be confirmed before anything moves.

### wire-event-type-keys-is-not-the-same-concept | medium | do not merge on the word "wire"

Recorded beside the finding above because the names invite exactly the wrong
merge. A pair of key names in the snapshot module lists the two KEYS a frame's
kind may arrive under. The enumeration lists what that kind may BE. One answers
where to read the discriminator, the other what values it admits. DISTINCT.

### ipc-swept-and-found-clean | low | the bridge is already shaped as this campaign wants

Complete rather than partial, on a small surface. The dispatch and response
models and the worker bridge showed no duplication: event buffering, flush with
retry, and heartbeat-failure escalation each exist once, and a single
serialisation seam is used by both sides of the boundary. Recorded as coverage
and as a second example, after the graph and compiler sweep, that the discipline
this campaign installs is already present in parts of the codebase rather than
being imposed on all of it.

### one-name-two-opposite-contracts | critical | worse than duplication, and it read as duplication

The provider catalog cluster closed with a find that outranks its own moves. A
text-reading helper appears in four catalog modules under one identifier. Three
of them REFUSE a missing or wrongly-typed value and cap its length. The fourth
returns nothing instead and applies no cap. Same name, opposite contract.

That is worse than plain duplication and it presents as duplication, which is the
trap: a reader who learns the name in one module carries a wrong belief into the
others, and the type checker agrees with them because both signatures are
plausible. The resolution was to make the name state which contract it is - a
required reader and an optional one, separately named - rather than to fold four
things into three-plus-a-special-case. Recorded as the sharpest verdict class in
this campaign: not DUPLICATE, not DISTINCT, but a name collision hiding a
contract difference.

A second DISTINCT was protected in the same visit: one lane reads a missing
collection as empty while another refuses it. Collapsing would have silently
changed a lane's contract.

The cluster was also wider than issued - four modules, not the three scoped, and
a home skipping the fourth would have re-created the problem it closed. That is
the SIXTH inventory in this campaign materially wrong on first issue, and every
lane that tested the rule has vindicated it.

### two-lanes-in-one-cluster | high | an orchestration failure that briefly broke a module

While one lane executed the catalog cluster, another writer applied part of the
same planned moves to the same files, leaving a module referencing a name that
had been deleted without its import wired. The state converged before either
committed, and the executing lane re-ran every gate against the converged tree
rather than trusting its earlier green - which is the only reason nothing broken
landed.

The cause is the assignment axis, again: work is assigned by CONCEPT while
contention happens by FILE, and in a single shared worktree those are different
partitions. This is the second occurrence, and the earlier one is already
recorded; what this adds is that the collision produced actual breakage rather
than only idle time, and that the defence was a lane distrusting its own passing
gate.

Which yields the standing property worth stating plainly: in this tree, type-check
and test results have a shelf life of MINUTES. Two diagnostics observed from the
orchestrator's own run vanished on re-run, from a lane mid-edit in the same
files. Gates belong immediately before staging and nowhere else.

### a-lying-name-and-the-workarounds-around-it | critical | duplication hiding a live defect

The owner-restriction authority is genuinely single-homed - the platform DACL
machinery is restated nowhere, verified across every restriction site in the
tree. But its file-restricting entry point applied the file mode
unconditionally on POSIX, while FOUR callers pass a directory. Its Windows branch
had always handled directories; the asymmetry was POSIX-only, and every caller
had answered it separately - one branching around the authority entirely on
POSIX, one open-coding the restriction twice, and one calling it unmodified.

That third caller is a live defect. The file mode on a directory strips the
traversal bit, so nothing beneath it can be opened - and the system call REPORTS
SUCCESS, so the error guard sitting beside it never fires. The profile arms
clean and the state directory holding thread content, the permission-decision log
and the checkpoint store becomes unreachable later, far from the cause.

This is the name-collision class again, in its most expensive form: a name
promising a narrower contract than its callers relied on. The finding worth
carrying is how it was detected - not by the failure, which is silent, but by
noticing that every caller had built a workaround. The workarounds are what a
lying name looks like from the outside, and they are visible long before the
defect is.

Fixed by deciding the mode at the authority rather than at each call site, and
renaming the entry point so it no longer claims to handle only files. The old
name is deleted.

### assert-the-decision-when-you-cannot-run-the-platform | high | method finding

The defect above lives on a platform the executing host cannot run. A test gated
to that platform would have SKIPPED there and reported coverage it did not have -
which, in a campaign that has repeatedly caught stale greens, is the worst
available outcome. The lane instead asserted the mode DECISION rather than the
resulting permission bits: the directory answer must carry the traversal bit, the
file answer must not, and neither may admit group or other access. That runs
everywhere and cannot be vacuously satisfied.

Recorded as method because the choice generalises past platforms: when the
environment cannot exercise the consequence, assert the decision that produces
it, rather than writing a test whose skip is indistinguishable from a pass.

### discovery-heartbeat-directory-unrestricted-on-windows | medium | open, security-relevant

Surfaced by the same sweep and not fixed in it. One of two discovery write paths
creates its parent directory with a POSIX mode and then applies a POSIX-only
restriction, with no Windows branch at all - while its sibling publication path
receives a verified private access-control entry. So on the platform this product
targets first, that parent directory is left unrestricted. Queued rather than
absorbed into the commit that found it.

### correction-the-tree-kill-cluster-was-already-closed | high | an inventory wrong by being stale

The process-tree kill cluster was recorded as two independent implementations of
one escalation, roughly seventy duplicated lines. That was true when the sweep
found it and false when it was assigned: the synchronous twin had already been
reduced to a four-line wrapper over the one escalation, in a commit that removed
over a hundred lines and added coverage. Confirmed an ancestor of HEAD.

Seventh inventory in this campaign materially wrong on first issue, and the first
wrong by being STALE rather than incomplete. Every earlier correction ADDED
sites; this one removed a cluster entirely. So the standing rule needs its
converse stated: re-derivation is not only a guard against undercounting, it is a
guard against a list describing a world that no longer exists. The instruction
here quoted a sweep's finding without checking whether the same sweep had since
fixed it.

Making no production change was the correct outcome, and is recorded as such -
a lane sent to find something to move would have found a wrapper and improved it.

Two things confirmed in passing. The contract difference predicted for this
cluster was real: the synchronous seam maps its single timeout onto the terminate
phase only, so its worst case exceeds its nominal budget - and that was already
written into the docstring rather than left to be discovered. And a third
function that resembles both is not a duplicate at all: it prefers the operating
system's containment and delegates only when a process has none.

### a-guard-pinned-to-one-platforms-spelling | high | half a concept guarded, and it looked green

The standing structural guard already pinned this concept - by matching one
platform's command literal. A re-derivation written for the other platform
carries no such literal and passes untouched. Half the concept was covered and
the row reported green, which is the same failure class as a platform-gated test
whose skip is indistinguishable from a pass.

The repair pins the load-bearing STEP rather than a spelling: on the platform
with no whole-tree signal, descendants must be walked BEFORE the root is
signalled, because signalling the root first severs the parent links the walk
reads. A re-derivation that signals first still terminates the root, so it looks
like it worked while leaving grandchildren alive - precisely the copy that would
never announce itself.

Two generalisations follow. Any guard row keyed to a platform-specific literal, a
vendor spelling, or one implementation's incidental token has the same blind
spot, and the remaining rows should be audited on that criterion. And a guard
must be proven non-vacuous: this one was, by driving the scanning helper directly
- returning the expected module for a present pattern, nothing for an absent one,
and a large count for a trivially common one - rather than by planting a decoy
file in the source tree, which other lanes would have seen mid-run.

Note also what the guard's existence means for the open question this feature's
decision record deferred: whether the rule is enforceable rather than
conventional is being answered in practice, by a structural test that fails when
a concept regains a second declaration.

### discovery-parents-restricted-by-one-declaration | high | closed, and the security part was kept

Both discovery writers performed "create the parent, then restrict it" and had
drifted apart: one resolved a directory authority, applied a private
access-control entry, and refused to publish if it did not read back; the other
created with a POSIX mode, restricted on POSIX only, and stopped - leaving that
directory unrestricted on the platform this product targets first. One
declaration now serves both, verified by a single remaining creation site in the
tree.

The part worth recording is what was NOT collapsed. The consolidation kept the
authority resolution rather than reducing to a bare restriction call, because
that step refuses a link-like path and one whose identity changes mid-resolve -
and applying a private access-control entry THROUGH a planted junction hands the
guarantee to whatever the junction points at, which is the one element of this an
attacker chooses. A merge that kept only the restriction would have read as
equivalent and silently removed the defence.

The refusal message was deliberately not preserved. It was grepped for first and
found asserted nowhere, so both writers now share the authority's message, which
names the offending path - strictly more information, and declared as a behaviour
change rather than absorbed. POSIX was left byte-identical on purpose: extending
the authority resolution there would add a refusal path on a platform this change
cannot exercise, which this campaign has already paid to learn.

### assert-the-consequence-or-the-decision-by-what-the-host-can-run | high | the pair completed

The earlier method finding said: when the environment cannot exercise a
consequence, assert the DECISION that produces it. Its mirror is now recorded
from the opposite case. This defect lives on the platform the host CAN run, so
the consequence itself was asserted directly - and the test was proven
non-vacuous by reproducing the pre-fix sequence exactly and reading the result
back, confirming the parent was NOT restricted before the change.

Together they make one rule rather than two preferences: choose the assertion by
what the host can actually execute. A consequence assertion on a platform that
skips is coverage theatre; a decision assertion where the consequence is
reachable is weaker than it needs to be.

### observed-once-not-reproduced | medium | a reporting standard worth keeping

A lane saw four failures in a registry suite, could not reproduce them - the file
passes alone, the full suite passed on re-run - and recorded them as "observed
once, not reproduced" rather than as flake. The distinction matters because those
tests bind real ports and another lane may have had services live, so the
mechanism is plausible but unproven. Filed so that a second sighting by anyone
else is the SECOND, not the first. The same lane applied the same standard to a
single type diagnostic that vanished on re-run.

Recorded as a reporting standard because this campaign has repeatedly been misled
by results that were true when taken and false minutes later, and because
"flake" is the word that ends an investigation.

### the-blind-spot-is-one-member-of-a-set | critical | the general form, and it is not about platforms

The guard weakness first found as "pinned to one platform's spelling" has a
general form, established after auditing every row: the defect is a pattern
pinned to ONE MEMBER OF A SET THE CONCEPT RANGES OVER. Platform was incidental.
The three instances differ in shape and are the same fault - one platform of two,
one stage of six, one spelling of an assignment where the prevailing house style
supplies a second.

The question that finds it is therefore not "is this platform-specific?" but
**"what else could a writer have chosen here?"** That reframing is the durable
output of this sweep, and it applies to any invariant expressed as a literal
rather than as the property it stands for.

Ratios matter and were measured: the process-tree row guarded one half of its
concept; the vault stage row guarded one SIXTH, pinning a single stage name where
a restatement beginning at any of the other five passes untouched. Both reported
green throughout.

One row was audited and deliberately left alone, which is what makes the sweep
credible: a row pinning a private name looked like the same weakness and is not,
because its actual risk is the function being made public again rather than
copied - and de-privatisation already flips its count and fails it. A sweep that
"fixed" four of four would have been manufacturing.

### a-guard-refused-because-the-concept-is-not-consolidated | high | the honest non-fix

The fourth row pins a function by name, so a copy under another name passes. That
is a genuine weakness and it was NOT repaired, for a reason worth more than the
repair: the invariant it would have to pin - narrow to an object, degrade to
empty rather than raise - occurs INLINE in ten modules across the authoring,
context and provider packages. A row asserting a count of ten would assert
nothing and would need revising on every ordinary edit, which is the
guard-file-as-noise failure this campaign has been careful to avoid.

So the finding is not about the guard. It is that this concept is **less
consolidated than "one declaration" reads**: a canonical helper exists and nine
inline restatements sit beside it. Whether those are a bypass of the helper or
merely idiomatic narrowing is a judgement that belongs in the open, not settled
silently inside a test file. Recorded as open.

This is the second time a lane has declined to strengthen something on the
grounds that the strengthening would be dishonest, and both times the refusal
surfaced a better finding than the change would have.

### ten-inline-narrowings-were-seven-and-five | high | the count was never the question

The open question was whether ten inline restatements of a narrowing invariant
were bypasses of the canonical helper or idiomatic local narrowing. Derived from
bodies rather than counted: thirteen matching lines are one home, SEVEN bypasses
and FIVE distinct sites, and the split falls exactly on a package boundary.

One site settles the question by itself. A module narrows a result THROUGH the
helper, then two lines later inlines the identical check on the next field of
that same result. Not a module lacking access, not a writer disagreeing with the
posture - the same author not reaching for it a second time. A neighbouring site
corroborates by annotating its result with the helper's exact return type,
written out by hand.

The five that stay are blocked by layering rather than preference, and each
blocker was verified: the owning package exports none of this, and the consuming
package imports nothing from it at all, so routing them would mint a
cross-package dependency that does not exist. Their values also arrive as an
untyped mapping off HTTP envelopes rather than the closed JSON type the helper
takes. This is the "cannot import it" case rather than "simply did not", and the
distinction decides it.

Two details a count would have destroyed. One neighbouring site degrades to
NOTHING rather than to an empty object, so the fallback is not even locally
uniform. And the frontmatter site is the last of four identical degradations
inside one parser - extracting only that one to a foreign helper would leave the
function half-speaking two vocabularies, which is less coherent, not more.

Recorded because the campaign's standing question - one concept in many places,
or several sharing a shape - resolved into BOTH answers within one grep, and only
reading bodies separated them.

### converge-on-the-boundarys-precondition-not-the-strictest-site | critical | corrects a rule this audit issued

This audit told a lane to converge divergent validations on "the strictest
existing behaviour". That is wrong as a general rule and is corrected here. The
right target is **the precondition the boundary actually enforces**.

The difference is not academic. Executed against the real dispatch model rather
than reasoned about: an empty, relative or whitespace workspace value fails
validation at that field, and an absolute one is accepted and minted. So
converging the divergent readers on string-non-empty-absolute rejects exactly the
values that crash today and nothing else - a bug fix, not a tightening. "Strictest
wins" would additionally have imported a length bound from a site that produces
database index selectors, newly rejecting a very long absolute path that
currently dispatches fine, in service of a concern the converging sites do not
have.

### the-same-defect-in-two-sites-and-the-code-already-knew | critical | a stuck run, not a crash

Two readers return a stored workspace value that is non-empty but relative or
whitespace and hand it to the dispatch boundary, which raises - and in both, that
construction happens AFTER the control action has been claimed. The result is a
claimed action with no dispatch: the run neither proceeds nor cleanly refuses.
That is worse than an exception, because the claim is durable and the failure is
not. One of the two also admits the empty string.

The knowledge already existed in the codebase and had not reached them. A third
site defends against exactly this, with a comment stating that constructing the
dispatch without a project raises inside the ingest validator and aborts the
whole pass, so one unrecoverable thread would strand every healthy one behind it.
Three sites, one hazard, one of them guarding against it and two never told. That
is this campaign's thesis in a single cluster.

### strictness-differed-by-three-unrelated-contracts | high | the lens question answered fully

The standing lens asks whether divergent strictness is accidental or contractual.
In this cluster it was BOTH, and the contractual half divided three ways inside
one apparent concept: one site differs by OUTPUT, returning a minted value
because it keys a compiled graph and a second entry for one directory would
compile twice; one by PURPOSE, producing hashed discovery selectors for a
database index, which is where its length bound belongs; and one by FAILURE
POLICY, marking a thread failed with a reason rather than returning nothing,
because it is a sweep that must not strand healthy threads behind one bad one.

So the shared reader takes the precondition and leaves output, purpose and
failure policy to the caller. Flattening any one would have destroyed something
load-bearing. Recorded because "several concepts sharing a shape" has until now
meant two; here it meant four, and only comparing bodies separated them.

### a-docstring-claiming-the-guarantee-the-code-lacks | critical | worse than a lying name

The cleanup containment reader resolves the stored workspace value with no
absoluteness check, so a relative stored root resolves against the SERVING
PROCESS's working directory - and if that path happens to exist, the
existing-directory check passes and it proceeds to judge which artifacts are
contained. Containment decides what cleanup may touch, every other reader of that
column now refuses a relative root, and this one silently relocates it. It is
also precisely the split-brain this repository's own absolute-path test exists to
prevent.

What raises it above the other name-collision findings is its docstring, which
states that the existing-directory check is there so a stale root "refuses every
artifact rather than resolving relative paths against the process working
directory". The documentation asserts the exact protection the code does not
have. A lying NAME misleads a reader who is looking; a docstring claiming the
missing guarantee stops them looking at all - a reviewer asking "does this handle
relative roots?" reads that sentence and moves on. Recorded as the more dangerous
form of the same class.

Ruling: refuse a relative stored root, keep the path return and the existence
requirement - those are its genuine contract and the reason it is correctly
DISTINCT - and add only the absoluteness the docstring already promises. It does
not route through the shared reader.

### the-reader-asks-the-boundary-rather-than-restating-it | high | the principle applied to itself

The consolidated workspace reader deliberately does not restate the
absoluteness rule. Writing that predicate inline would have been a second
declaration of a contract the boundary's own minting function already owns, and
it would stop agreeing the moment that owner changed - in a commit whose entire
subject is that class of mistake. It asks the owner instead.

Recorded because it is the campaign's principle turned on the campaign's own
output, and because the alternative would have looked like a fix: a hand-written
`isabs` check reads as defensive rigour and is in fact a fresh copy of somebody
else's rule.

The non-vacuity table filed with it also corrects this audit's earlier framing.
"One site read it with no type check" understated the defect: reproducing both
deleted readers against the test inputs shows one returned all three
crash-inducing values and the other two of three, so BOTH resume paths could
strand a run holding a claim with no dispatch.

### worker-liveness-stamp-has-five-writers-and-no-owner | critical | DUPLICATE

The gateway's worker-liveness signal is written at FIVE production sites and read
at two, and nothing declares it. Writers: the internal WebSocket connection-open
stamp; the WebSocket heartbeat arm, which also records active threads; the HTTP
heartbeat route, which also records active threads; the post-dispatch mark in the
API utility module; and a closure handed to the worker watchdog at app assembly.
Readers: the health projection and the worker-management staleness rule, BOTH
reaching the attribute through a defaulted `getattr`.

The defensive read is the symptom, not the defence. Five ad-hoc writers stamping
an attribute that no module declares means neither reader may assume it exists,
so both degrade silently when it does not - and "worker is unreachable" is
exactly what a silent degradation here produces. This is the same signal the
worker-reachability work earlier in this campaign hardened at the READ side;
hardening a read whose write side has five uncoordinated authors buys much less
than it appears to.

The WebSocket heartbeat arm and the HTTP heartbeat route are the strict
duplicate: the same operation - accept a worker heartbeat payload, stamp
liveness, record the active-thread list - written twice against two transports,
differing only in the transport label they log. A change to what a heartbeat must
carry, or to what accepting one implies, has to be made twice with nothing making
the two agree.

The prose already concedes the coupling it cannot enforce: the post-dispatch
mark's docstring states that the value it writes "is identical in shape to the
timestamp written by POST /internal/heartbeat". That is a cross-site invariant
asserted in a comment instead of expressed in code - and it is already stale,
naming one of the four other writers.

Canonical home: worker management, which already owns the staleness rule that
gives the value meaning. One recording function taking the optional active-thread
list, consumed by all five writers, letting both readers stop guarding against
their own codebase.

### the-two-heartbeats-share-a-wire-name-and-differ-in-contract | medium | name collision

Two unrelated signals are both called `heartbeat` on the wire. The client-facing
SSE keepalive is fully canonical - a declared event model, the shared event-type
enum member, an allowlist entry - and carries `server_uptime_seconds`. The
worker-to-gateway IPC heartbeat is an undeclared raw dict carrying `worker_id`,
`active_threads` and `uptime_seconds`, dispatched by string literal at the
receiving end.

Not a duplicate: different transports, audiences and payloads, so they must not
be merged. The finding is that one contract is declared and the other is not,
while both answer to the same wire token - and their uptime fields differ by a
prefix, the kind of near-miss that reads as a typo and is actually two contracts.

Reachability checked before severity was assigned: the IPC heartbeat cannot reach
the SSE allowlist, because its receiving arm stamps state and does not relay. So
this is latent, not live - recorded at medium on that basis. What keeps it latent
is a dispatch arm, not a type distinction, and the allowlist keys purely on the
shared token: were the IPC payload ever relayed, every field it carries would be
silently dropped as unlisted, leaving a typed frame with no content.

### wire-vocabulary-cluster-was-closed-one-file-early | high | MISPLACED

The event-type vocabulary rehoming converted the IPC serializer's eleven literals
to the shared enum and stopped there. Five production sites still hand-copy the
twelfth member's value: the worker's heartbeat producer, the receiving `case`
dispatch, the SSE emitter's event name, the allowlist catalog key, and the shared
test frame reader.

Recorded as its own finding because a partially converted vocabulary is worse
than an unconverted one. The enum exists and has the member, so a reader checking
whether this vocabulary is canonical finds the declaration and stops - while the
actual wire path is still literal-driven end to end. The `case` dispatch is the
sharp edge: change the enum value and the serializer follows it while the
dispatch silently stops matching, dropping worker heartbeats into the fall-through
and starving the liveness signal the previous finding describes.

### the-attach-bearer-check-is-declared-twice | critical | DUPLICATE

The gateway's attach-credential bearer check is implemented twice in the API
layer, against the SAME credential in application state. One is the FastAPI
dependency guarding engine-facing routes; the other is the predicate the liveness
surface consults before disclosing the readiness projection. Both read the same
state attribute, both apply the test-only bypass, both build the same expected
`Bearer <token>` byte string, and both compare it in constant time.

Security-critical and therefore recorded at critical severity: this is the rule
that decides whether a caller may talk to the gateway at all, and a change to it
- tightening the header parse, admitting a second credential plane, correcting
the bypass - has to be made in two places that nothing forces to agree. A
divergence would not fail loudly; it would leave one surface enforcing the old
rule, and the weaker of the two becomes the real one.

Their independent authorship is visible in the code. One spells the comparison
`secrets.compare_digest` and the other `hmac.compare_digest` - the same function
object, verified in this session - reached through two different imports, which
is what two people solving the same problem separately produces rather than what
one shared rule produces.

Their differing behaviour on an unconfigured token is NOT a contract difference
that justifies two implementations: refusing with a 503 on a hard gate and
disclosing nothing on a disclosure gate are two error MAPPINGS of one verdict.

The correct pattern already exists in this repository and was simply not adopted
here: the internal-IPC bearer module is deliberately framework-free and returns a
verdict precisely so each caller can map it onto its own transport's failure. Its
docstring calls itself "the single home for the bearer rule", which is true only
for the plane it serves - the attach plane duplicates the same rule two files
away. Canonical home: one exact-match predicate consumed by both API sites, each
keeping its own error mapping.

Checked and ruled DISTINCT rather than folded in: the lifecycle ownership
capability check. It compares a bare value from a custom capability header with
no `Bearer` prefix, on a different credential plane, and its resemblance is the
constant-time compare alone.

### the-atomic-writer-cluster-closed-one-module-early | high | DUPLICATE

The atomic-write rehoming produced a canonical writer with four consumers, and
the desktop credential mint is not among them. It hand-rolls the whole sequence -
sibling temp, harden, rename-with-retry, unlink on any failure - beside a shared
module that already does it.

The duplication is exact where it is checkable. Its retry budget is declared
independently at the SAME value as the canonical module's, so the two agree today
by coincidence and a tuning change to either diverges silently with nothing
failing. Its rename helper reimplements the canonical retry-on-sharing-violation
loop. And the Windows rationale for that retry - that the rename is atomic but a
reader holding the target open can briefly deny it - is written out in both
modules, which is the signature of a copy rather than of two independent
solutions to one problem.

One part is genuinely NOT expressible against the canonical home today, and the
finding is recorded with that stated rather than as a flat "should have imported
it": the credential mint hardens through a platform helper that applies POSIX
mode bits OR a Windows private DACL, while the canonical writer's hardening
parameter takes an integer mode. A DACL is not an int, so this caller could not
have passed its requirement through the existing signature.

That argues for extending the canonical home with a hardening HOOK applied to the
temporary file before the rename, not for keeping a second implementation. The
inexpressible part is the hardening alone; the temp-and-rename, the retry loop
and the retry budget - everything else the fork exists to carry - are duplicated
with no such justification.

Recorded as the third instance of one pattern this campaign keeps finding: a
cluster reported closed that converted the sites which fit the new home and left
the site that needed the home to grow. The vocabulary cluster and this one failed
the same way, which is why closure now requires a grep proving no site still
reaches the old declaration.

### a-cap-whose-comment-says-matching-is-the-point | high | DUPLICATE

The streamed permission-description cap is declared as a named constant on the
schema side, with a comment stating that its value is "matched deliberately" to
the durable control writer's, and that "matching is the point rather than a
coincidence: the streamed frame and the row a reload replays from must not
disagree about how much of a description exists, or a panel would show text live
that vanishes on refresh."

The durable writer it names slices at a BARE LITERAL and does not import that
constant. So the invariant is documented on one side and magic-numbered on the
other, and nothing makes the two agree.

This is the strongest form of the prose-asserted-invariant pattern found so far,
because the comment states the exact user-visible bug that divergence produces.
Someone raising the streamed cap satisfies every check in the repository and ships
the "text that vanishes on refresh" the comment was written to prevent - the
comment cannot fail, and the literal it points at does not know it is being
pointed at.

Canonical home: the schema constant is the natural authority since it is already
named and exported. The durable writer imports it.

### the-workspace-root-length-bound-is-declared-nine-times | high | DUPLICATE

The maximum workspace-root length is stated at nine production sites: the database
column width, two separately named module constants that do not reference each
other, an inline comparison beside one of those constants, and five literal
occurrences in route query parameters and containment checks.

The real authority is the column width - exceeding it is a write failure, not a
validation refusal - so every other site is restating a database constraint from
memory. The two named constants are the tell: two modules each decided the bound
deserved a name, neither found the other, and both picked the same value, so they
agree today by coincidence exactly as the atomic-writer retry budgets did.

The failure mode is asymmetric and worth stating. Lowering the column without
lowering the eight restatements turns an accepted request into a write failure
deep in a transaction; raising the restatements without raising the column does
the same. Only tightening every restatement in lockstep is safe, which is the
definition of a constraint that should be declared once.

Excluded deliberately: the two occurrences inside a schema migration. A migration
records what the schema was when it ran, so a literal there is correct and must
not be replaced with an import that would rewrite history when the constant moves.

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

### correction-two-functions-share-the-name-canonical-project-root | medium | a naming collision my own earlier entry missed

My own `worker-ipc-domain-swept-and-found-clean` entry described
`providers/_acp_types.py`'s project-root reduction as "a documented DISTINCT
concept" without noting that it is declared under the IDENTICAL name as the
wire-side authority: both are named `canonical_project_root`.
`ipc/schemas.py::canonical_project_root` mints the run's active-project
spelling for the dispatch wire - strict (raises on blank or non-absolute), uses
`os.path.realpath` (symlink resolution, no case-folding), and its own docstring
calls itself "the single site that turns any spelling of a directory into the
run's canonical one." `providers/_acp_types.py::canonical_project_root`
reduces a project path for the ACP permission layer's scope-containment
comparison - non-strict (a path the OS cannot even resolve still yields a key
via an `os.path.abspath` fallback rather than raising), additionally strips the
Windows extended-length prefix, and additionally case-folds via
`os.path.normcase` for case-insensitive filesystems - and its own docstring
makes the parallel claim: "the single form enforcement compares against."
Neither module imports the other; confirmed by an exhaustive grep across the
tree, no import edge exists between them in either direction and every
consumer of each traces back to its own file. Verdict DISTINCT-with-a-naming-
hazard, the same shape as `admission-state-name-collision`, but sharper:
unlike that pair's genuinely unrelated vocabularies, these two do closely
related work - canonicalize a directory spelling to one comparable form -
under the identical name, with actually different canonicalization rules: one
case-folds, one does not; one raises on an unresolvable path, one never does.
A reviewer reading either docstring's "the single form" claim in isolation has
no reason to suspect a second, differently-behaved function of the same name
exists one layer over. No rename is proposed here, consistent with this
audit's convention for a naming hazard rather than a merge candidate; recorded
so a future sweep does not import the wrong one by IDE autocomplete, or
discover the collision by way of a cross-layer comparison that silently
disagrees on case-folding.

### outstanding-permission-status-set-declared-four-times | medium | actioned within one file

`src/vaultspec_a2a/database/permission_repository.py` asked "which permission
requests are still unsettled" four times, each restating the same two-member
set - `PermissionRequestStatus.PENDING` and `.ANSWERED_PENDING_APPLY` - rather
than reading it from one place. `get_pending_permission_requests` and
`get_threads_with_pending_permission_requests` built it with byte-identical
conditional logic (`[PENDING]`, appending `ANSWERED_PENDING_APPLY` when
`include_answered_pending_apply` is true); `supersede_permission_requests` and
`expire_pending_permission_requests` hardcoded the same two-item list
unconditionally, also byte-identical to each other. No canonical constant for
this set existed anywhere in the tree to import instead - unlike the
`NON_ACTIVE_STATUSES` case above, this was four inline declarations of a
concept with no home at all, not one hand-rolled site ignoring an existing
authority.

Verdict DUPLICATE, actioned: added a private module-level
`_OUTSTANDING_PERMISSION_STATUSES` tuple and pointed all four functions at it,
keeping the `include_answered_pending_apply` toggle explicit at the two call
sites that vary by it rather than folding the policy into the constant. Scoped
to `permission_repository.py` alone - no canonical export was added to
`thread.enums`, since that module belongs to a different sweep and the fix
needed nothing outside this file to be complete. 91 tests across the
reconciliation, repair-journal, permission-audit-log, and control-action-lease
suites pass unchanged; whole-tree `ty check` is clean.

### process-tree-kill-and-poll-loop-still-live | high | two prior findings re-verified at HEAD, neither actioned

Re-verified two prior findings in this newly-assigned domain
(`src/vaultspec_a2a/lifecycle/`, `src/vaultspec_a2a/utils/`,
`src/vaultspec_a2a/testing/`) before sweeping for anything new, per this
campaign's method. Both are STILL LIVE, unchanged from how they were
originally recorded.

`process-tree-kill-declared-twice`: `kill_pid_tree_async` in
`src/vaultspec_a2a/utils/process.py` (asynchronous) and `tree_kill` in
`src/vaultspec_a2a/lifecycle/manager.py` (synchronous) both still implement
the identical Windows-`taskkill`/POSIX-snapshot-then-escalate algorithm, each
with its own docstring still calling itself the canonical or single such
escalation. Not actioned. The consumer sets genuinely differ in call
convention, not just location: `tree_kill`'s callers -
`src/vaultspec_a2a/cli/service.py`, `reap()` in the same module, and (outside
this domain) `service_tests/harness.py` - are synchronous call sites with no
running event loop to await into, so collapsing onto the async version is not
a delete-and-import; it needs either a sync-safe wrapper (a fresh decision
about how it blocks) or converting those callers to async (a wider ripple than
this file). Recorded rather than merged because the fix is a real design
choice, not a mechanical dedup, and the existing precedent in this audit
(`a-mechanism-without-deletions-makes-it-worse`) rules out leaving a
compatibility shim as a middle path.

`bounded-wall-clock-poll-loop`: every site the original finding named in this
domain is still hand-rolled, unconverged onto any shared primitive. Confirmed
present: `src/vaultspec_a2a/utils/process.py`'s `_POLL_INTERVAL = 0.1` (two
call sites); `src/vaultspec_a2a/lifecycle/manager.py`'s three loops
(`_confirm_terminated` at 0.05s, `tree_kill`'s escalation wait, and the
0.1s-literal port-readiness wait); `src/vaultspec_a2a/lifecycle/singleton.py`'s
`_ORPHAN_LOCK_POLL_S = 0.05` with no jitter; and
`src/vaultspec_a2a/testing/leases.py`'s jittered acquire wait. Not actioned.
The severity that keeps this recorded rather than merged is the consumer set,
not the mechanics: the singleton lock guards the desktop application home's
sole-owner guarantee, and the kill escalation is the last line before a wedged
process is force-killed - both are exactly the kind of site where a
single-pass mechanical extraction, done to close an audit finding rather than
because each site's own failure semantics were individually reviewed, risks
introducing the defect the primitive was meant to prevent. A future actioning
step should review each site's deadline-vs-jitter-vs-diagnostic-on-expiry
behaviour individually against the shared primitive's shape before converting
it, not batch all five in one commit.

### detached-spawn-flags-now-exported | medium | closes the prior finding for this domain's member, verified and fixed

Re-verified `detached-spawn-flags-triplicated` against current HEAD:
`src/vaultspec_a2a/lifecycle/manager.py`'s `spawn()` still hand-rolled the
Windows-`CREATE_NEW_PROCESS_GROUP`-vs-POSIX-`start_new_session` branch inline,
exactly as recorded (`service_tests/harness.py`'s copy is outside this
domain and was not touched). ACTIONED for the in-domain member: exported the
decision from `src/vaultspec_a2a/utils/process.py` as
`detached_spawn_kwargs()`, and pointed `manager.py`'s `spawn()` at it.

The first version of this fix was wrong and is recorded rather than silently
corrected, per this audit's own precedent on method findings: it returned a
plain `dict[str, object]` splatted into `subprocess.Popen(**kwargs)`, which
passed `src/vaultspec_a2a/utils/tests/` and `ruff` cleanly but broke a
whole-tree `ty check` with `invalid-return-type` and `no-matching-overload` -
`Popen.__init__` is overloaded on its exact keyword set, and a splatted
`**dict` erases the static information the overload resolution needs, even
though every value in the dict was itself correctly typed. The corrected
version returns a frozen `DetachedSpawnFlags` dataclass with both fields
always populated (the inactive platform's neutral value, matching the
original inline code exactly), and the caller passes `creationflags=` and
`start_new_session=` explicitly rather than splatting. This is the concrete,
narrow form of the general caution above: even a "just extract this small
decision" fix needs its OWN verification, not an assumption that passing
tests plus a clean lint is sufficient - the defect here was invisible to both
and only a whole-tree type check caught it.

Verified after the correction: `src/vaultspec_a2a/utils/tests/test_process.py`
+ `test_process_containment.py` (29 passed),
`src/vaultspec_a2a/lifecycle/tests/test_manager.py` (39 passed, exercising
`spawn()` through `serve_up`/`resume`/`rerun` against real spawned processes),
the full `src/vaultspec_a2a/lifecycle/tests/` suite (151 passed), and a
whole-tree `ty check` (0 diagnostics, both file-scoped and whole-tree).

### port-reservation-misplacement-fixed-since-recorded | medium | a MISPLACED finding no longer describes the tree

Re-verified `port-acquisition-split-across-modules` and its correction
`correction-port-probe-was-a-reservation` against current HEAD. Both described
`src/vaultspec_a2a/tests/gateway_boot.py` as holding the reservation-scoped
port-acquisition implementation a tier away from its canonical home in
`src/vaultspec_a2a/testing/ports.py`, importing two of that module's privates
upward. That is no longer true. `gateway_boot.py` now imports
`reserve_scratch_ports`, `allocate_free_ports`, and
`hold_for_process_lifetime` directly from `testing.ports` (all three are
public exports of that module, re-exported through `testing/__init__.py`) and
contains no reservation logic of its own - only the call site that consumes
them (`spawn_until_ready`'s scratch-port-pair reservation before spawning a
gateway). The documented three-way boundary
(`reserved_port`/`free_port`/`allocate_free_ports`) that the canonical module
states for itself is intact and is the only implementation in the tree.
Verdict: FIXED SINCE RECORDED, not actioned by this sweep - already correct at
HEAD. Recorded per this domain's own standing instruction that a finding
quietly fixed is worth knowing as much as one still open, and so the next
sweep does not re-flag it as live.

### lifecycle-utils-testing-swept-and-found-clean | low | registry classification, discovery publication, and lease/session admission are single-homed

`classify_record` in `src/vaultspec_a2a/lifecycle/registry.py` is the sole
LIVE/STALE/DEAD verdict, consumed identically by
`src/vaultspec_a2a/lifecycle/manager.py`'s `reap()`/`resolve()`,
`src/vaultspec_a2a/testing/progress.py`'s `registry_watch`, and
`src/vaultspec_a2a/testing/endpoints.py`'s service resolution - no site
re-derives liveness from a bare pid check. `write_record` and the discovery
publication functions in `lifecycle/discovery.py` (versioned desktop record
and the general service.json record - two genuinely different wire shapes,
correctly not merged) both route through the one atomic-publish primitive in
`src/vaultspec_a2a/utils/atomic_write.py` rather than each hand-rolling
temp-then-rename. `src/vaultspec_a2a/testing/leases.py` owns the lease
acquisition mechanism outright, and
`src/vaultspec_a2a/testing/sessions.py` builds session admission and
fair-share worker-count policy strictly ON TOP of it (`acquire`,
`live_shared_holder_count` imported, not reimplemented) - mechanism and
policy correctly separated, matching this campaign's standing rule.
`src/vaultspec_a2a/testing/catalog_selection.py` is the already-consolidated
selection mechanism the `correction-selection-cluster-is-eleven-sites` finding
covers in depth; nothing new to add there. No new duplicate declaration was
found in this pass beyond the two re-verified findings above.

### alembic-version-reader-restated-across-a-package-boundary | low | mechanical only, recorded not actioned

`_read_alembic_version` in `src/vaultspec_a2a/database/compatibility.py` and
`_read_revision` in `src/vaultspec_a2a/desktop/migration.py` both open the
target SQLite file directly with the stdlib driver, query `SELECT version_num
FROM alembic_version`, and treat an `OperationalError` whose message contains
"no such table" as "no revision" rather than a fault - the same three-part
idiom typed out twice. The two differ only in what the caller needs: the
desktop module opens for read-write (staged migration inspects state before
mutating) and takes the first `fetchone()` row, while the compatibility module
opens strictly read-only via a `?mode=ro` URI (ordinary desktop boot must never
even attempt a write) and reads via `fetchall()`. Verdict DUPLICATE on the
mechanism only - the connection-mode difference is a real, load-bearing
distinction, not accidental drift, matching the same read-only-versus-writable
split this audit already protects for `checkpoint_pragmas()`'s callers.
Recorded rather than actioned: `desktop/` is a different package outside this
sweep's scope, and a shared helper would need a home neither module obviously
owns without crossing that boundary - a call for whoever holds both sides.

### attach-bearer-verification-reimplemented-for-health | medium | the same comparison, raising and non-raising

`src/vaultspec_a2a/api/auth.py::authenticate_request` and
`src/vaultspec_a2a/api/app.py::_http_attach_authorized` both verify the same
credential - `app.state.v1_service_token`, the attach-control bearer - against
an incoming request's `Authorization` header, and both open with the identical
test-bypass check (`app.state.allow_unauthenticated_v1_for_testing`). Beyond
that they diverge only in shape, not in what they check: `authenticate_request`
is the `Depends()` gate on every `/v1` route and raises `HTTPException` (503
when the token is unconfigured, 401 on a mismatch) using
`secrets.compare_digest`; `_http_attach_authorized` backs the `/health`
endpoint's authenticated-vs-liveness branch, returns a bare `bool` (treating a
missing or malformed token as `False` rather than raising, because `/health`
must keep answering when the process is unwell), and reaches for
`hmac.compare_digest` - the identical function, re-exported by `secrets`, so
this is not even a real implementation difference. Verdict DUPLICATE on the
comparison, not on the two call shapes: `/health` genuinely needs a
non-raising check (an external prober must get liveness even when
unauthenticated, never a 500), while every `/v1` route genuinely needs a
raising gate, so collapsing the two functions into one would force a shape
mismatch onto one of the two callers. What should collapse is the shared core
- build the expected `Bearer <token>` bytes, constant-time compare against the
presented header, return the token-missing and match verdicts as data - with
`authenticate_request` raising on top of that result and
`_http_attach_authorized` simply returning it. Today a change to the bearer
format, the header name, or the constant-time comparison itself has to be made
twice to stay correct, and nothing enforces that it was.

### plan-entry-defaults-bypass-the-typed-enum-event_adapter-already-imports | low | one file, two match arms, one style

`src/vaultspec_a2a/api/event_adapter.py::domain_to_wire` imports
`PlanEntryPriority` and `PlanEntryStatus` from `.schemas.enums` and uses them
correctly as validating constructors, but not as default sources: the
`PlanUpdate` case writes `PlanEntryStatus(e.get("status", "pending"))` and
`PlanEntryPriority(e.get("priority", "medium"))`, spelling the enum's own
default members out as bare strings rather than as `PlanEntryStatus.PENDING`
and `PlanEntryPriority.MEDIUM`. The same file's `PermissionRequest` case, code
earlier in the same match statement, gets this right for the sibling enum:
`PermissionOptionKind(opt.get("kind", PermissionOptionKind.ALLOW_ONCE))` reaches
for the named member rather than the bare string `"allow_once"`. Verdict
low-severity DUPLICATE-on-the-literal, scoped to one file: the fix is a
two-line edit swapping the bare strings for the members already in scope, and
it removes the only place in this module where a vocabulary's own default is
spelled out rather than named.

Separately, and NOT a defect, checked because it looked like the same pattern
at first read: `src/vaultspec_a2a/thread/models.py::PlanEntry`'s own dataclass
defaults (`status: str = "pending"`, `priority: str = "medium"`) and
`src/vaultspec_a2a/thread/snapshots.py::normalize_plan_entries`'s matching
`.get()` fallbacks restate the identical two literals, but `PlanEntry`'s own
docstring states this is deliberate: the domain layer is kept free of
"wire-protocol enum imports," and the plain-string values "correspond to
`PlanEntryStatus`/`PlanEntryPriority` members defined in `api.schemas.enums`."
That is a real architectural boundary - a domain module refusing to import a
wire-layer type - not an oversight, and merging it would cross the boundary the
comment exists to hold. Recorded alongside the actionable half so the two are
not conflated: the domain-layer restatement is DISTINCT by design, the
`event_adapter.py` restatement is not, because that module already pays the
enum-import cost the domain layer is explicitly avoiding.

### anchor-path-cap-contradicts-its-own-description | high | a third instance of the vault-index-cap defect class

Asked to check whether any OTHER `domain_config.py` setting's description
disagrees with how its consumers apply it, following the ruling on
`vault-index-cap-contradicts-its-own-description`. It does: `anchor_path_cap`
(default 10) is described as "Maximum anchor paths returned by the workspace
anchoring module" - singular, total-shaped, same as the language that turned
out wrong for `vault_index_cap`. Its sole consumer,
`src/vaultspec_a2a/context/anchoring.py`'s `build_anchoring_context`, applies
it PER DOC TYPE inside a loop over `vault_index.items()`:
`visible = paths[: domain_config.anchor_path_cap]`, once per stage, with no
running total across stages. With the same six stages this campaign has
tracked all sweep long, that is up to 60 paths surfaced under a setting that
claims 10 - and this block runs on EVERY node invocation once a feature is
active (`build_anchoring_context` is injected at message position [1] per
turn), not once per run the way `context_refs` is, so the same shape of
contradiction recurs on a tighter loop. `mount_token_ceiling` and
`min_remaining_tokens_for_mount` were checked as the two settings most likely
to share this defect, given they gate the largest injected block
(`graph/nodes/vault_reader.py`'s mount loop) - both are CORRECTLY applied as a
single running total across the whole turn, including the task-queue block,
matching their descriptions exactly; they are the contrasting clean case that
shows this is a per-field defect, not a systemic one. Not actioned, for the
same reason the lead gave for the sibling finding: making the cap a true
total would reduce what an agent sees, and making the description admit
per-stage application would legitimise a bound six times its stated number,
and choosing between those is a product decision about grounding breadth,
not a mechanical one. Breadth not fully re-established beyond this and the
mount-budget pair: the aggregator/debounce settings
(`debounce_map_max_entries`, `chunk_buffer_max_bytes`, `event_queue_maxsize`,
`tool_arg_truncate_len`) were spot-checked against their `streaming/`
consumers and found consistent with their descriptions on a light pass, but
`streaming/` is another sweep's domain and was not read in full here.

### cli-artifacts-telemetry-swept-and-found-clean | low | no unhomed artifact declaration, and the CLI is not another bearer-header site

Recorded for the negative space in this sweep's domain, answering the two
specific leads directly. First: whether the CLI hand-rolls anything the
gateway already owns. It does not. `src/vaultspec_a2a/cli/main.py`'s
`_request` helper builds its headers by calling
`gateway_auth.gateway_auth_headers(url)` and merging with `setdefault` -
it never formats an `Authorization` header itself - and
`src/vaultspec_a2a/cli/service.py`'s authenticated shutdown call does the
same. The CLI is therefore NOT an additional site for the low-priority
`bearer-header-string-template` finding; `src/vaultspec_a2a/gateway_auth.py`
(the shared credential-selection boundary the CLI and the MCP bridge both
consume) was already counted among that finding's declaring sites, not the
CLI itself. `_base_url` reads `settings.gateway_url` rather than re-deriving
it, and `_emit`'s JSON-render-and-exit-nonzero shape has no second
declaration anywhere in `cli/` - `cli/service.py`'s admin-shutdown call
checks a status code directly instead, a different response contract for a
different purpose, not a near-duplicate of `_emit`. Second: whether any
package declares a durable artifact without going through
`artifacts.ArtifactDeclaration`. None was found among the local writes this
sweep could reach - `cli/provision.py`'s workspace corpus,
`cli/service.py`'s app-home and store-parent `mkdir` calls (which fall under
`desktop/profile.py`'s already-declared `APP_HOME_STATE_TREE_DECLARATION`),
and `telemetry/` (which writes nothing to local disk at all - every signal
leaves over OTLP/gRPC to a collector) are all either declared or write
nothing durable. The absence of a central declaration registry is
deliberate, stated in `artifacts/__init__.py`'s own docstring
("cannot drift away from the call site it describes"), not a gap to close.
Eighteen modules across the tree already consume the vocabulary; this sweep
added none and removed none.

### team-selection-is-distinct-from-the-catalog-selection-cluster | medium | protected, not a twelfth site

Checked deliberately before touching `src/vaultspec_a2a/providers/team_selection.py`,
per the standing instruction not to re-litigate `correction-selection-cluster-is-eleven-sites`
without care. That cluster's discriminator is sharp: who READS a served catalog
and PICKS an entry on a caller's behalf. `team_selection.py` never picks. Its
two entry points, `freeze_team_selection` and `normalize_replay_selection`,
both take a `SelectionReference` the CALLER already named (provider_id,
execution_mode, catalog_revision, entry_id) and either validate it against live
catalog records (`_normalize_reference` - unknown lane, not selectable, stale
revision, unknown entry, unknown control option all refuse) or validate a
replay against what was previously accepted, with zero "first", "sorted", or
default-to-first-selectable logic anywhere in the file - confirmed by reading
it whole, not by name-matching. It is in fact the CONSUMER-SIDE enforcement of
the rule the eleven-site cluster measures every other site against: "a run's
artifacts are produced by what the caller chose," never a rank or a display
name. `api/routes/gateway.py`'s `_validate_and_freeze_selection_or_refuse`
calls straight into it. Verdict DISTINCT, recorded so a later sweep does not
fold this in as a twelfth site by name association alone.

### acp-json-narrower-trio-has-two-shapes-under-one-name | medium | one pair duplicated verbatim, a third same-named function is unrelated

`src/vaultspec_a2a/providers/acp_chat_model.py` and
`src/vaultspec_a2a/providers/_acp_rpc_handlers.py` each declare `_json_object`
and `_json_object_list` with byte-identical bodies (docstring wording aside):
degrade a malformed value to `{}` or filter a list down to its dict entries,
never raising. Verdict DUPLICATE, confirmed by direct comparison of both
bodies - the lenient-degrade behaviour is identical, not merely similarly
named. Both sit outside this sweep's three assigned files
(`_acp_authoring.py`, `model_profiles.py`, `team_selection.py`), so recorded
rather than actioned; a shared private helper in one of the two modules (or a
new co-located leaf) would close it cleanly since neither variance nor policy
distinguishes the pair.

Named alongside it because the collision is real and would mislead a
name-based search: `_acp_authoring.py` also declares a function called
`_json_object_list`, and it is NOT a third copy of the pair above. Its
signature is `(spec: JsonObject, field: str) -> list[JsonObject]` - it reads
one named field off an already-typed object and RAISES `ConfigError` naming
the field when the shape is wrong, the opposite failure mode from the
lenient-degrade pair. That difference is load-bearing: `_acp_authoring.py`
validates an authoring-bridge spec at a config-admission boundary, where a
malformed field must refuse loudly, not silently degrade to an empty list.
`_json_contract.py` (`providers/_json_contract.py`, already imported by
`_acp_authoring.py` for `JsonObject`/`JsonValue`) offers single-value raising
narrowers (`json_object`, `json_list`, `json_text`) in a third style again -
they narrow a bare value and raise `TypeError`, an internal-invariant signal,
never `ConfigError`. Three genuinely different failure postures under
overlapping names in one package; none of the three should be merged into
either of the others, and the name collision alone is the hazard worth
recording.

### frozen-assignment-digest-idiom-restated-across-schema-versions | low | breadth not established beyond two sites

`model_profiles.py::freeze_assignment` (the legacy profile-based frozen
assignment) and `team_selection.py::_digest_record` (the modern schema-v1
catalog-based frozen assignment) both compute a content digest the same way:
`json.dumps(record, sort_keys=True, separators=(",", ":"))` encoded and passed
through `hashlib.sha256(...).hexdigest()`. The two records digested are
genuinely different shapes belonging to the two coexisting schema versions
`graph/compiler.py` already parses by branching on `schema_version` (recorded
elsewhere in this audit's graph-domain findings) - RunStartResponse's own
docstring states both must stay readable, so this is not a migration to
collapse. Only the digest MECHANISM is duplicated, not the record it digests.
Grepped for the same `sort_keys=True, separators=` idiom paired with
`hashlib.sha256`: it recurs at least eight more times elsewhere in
`providers/` alone (`acp_catalog.py`, `codex_catalog.py`, `in_process_catalog.py`,
`kimi_catalog.py`, `openai_catalog.py`, `provider_catalog.py`, each for its own
catalog-entry or revision fingerprint) plus sites in `api/`, `database/`, and
`thread/`. Verdict DUPLICATE on the mechanism, low severity because the
convention itself has NOT drifted anywhere checked - every site uses the same
canonicalisation - so a shared one-line helper would remove typing, not fix a
disagreement. Breadth beyond the two files this sweep owns is not established
and is recorded as such rather than asserted.

### process-tree-kill-caller-inventory-and-consolidation-shape | high | full caller set established, decision escalated rather than implemented

Follow-up to `process-tree-kill-declared-twice`, done on instruction to
establish the shape of a fix without applying one. The full production caller
set of both declarations: `kill_pid_tree_async`
(`src/vaultspec_a2a/utils/process.py`) is called from
`src/vaultspec_a2a/control/worker_management.py` (two sites) and
`src/vaultspec_a2a/providers/_subprocess.py` (one site), all three already
inside `async def`, awaited. `tree_kill`
(`src/vaultspec_a2a/lifecycle/manager.py`) is called from seven sites internal
to that module across at least five different verb functions (`kill`,
`rebuild`/`rerun`, `reap`, and two arms of `serve_up`'s failure teardown),
plus `src/vaultspec_a2a/cli/service.py` (two leaf sites) and
`src/vaultspec_a2a/service_tests/harness.py` (one leaf site, a sync pytest
teardown method). Every sync call site traces to a Click CLI command or a
pytest sync fixture, never a running event loop, so a sync wrapper via
`asyncio.run()` is safe wherever it would be used.

Async-conversion of the sync side is NOT narrow: `tree_kill` is woven through
most of `lifecycle/manager.py`'s verb surface rather than confined to one
function, so making its callers async would ripple to most of the CLI
commands in `cli/main.py` that call into that module - moving the
`asyncio.run()` boundary outward rather than eliminating it, while touching
far more call sites than a sync wrapper would. A sync-wrapper direction
already has WORKING PRECEDENT in the tree, not a hypothetical:
`src/vaultspec_a2a/tests/gateway_boot.py`'s `reap_gateway()` is a plain sync
function that already calls
`asyncio.run(kill_pid_tree_async(proc.pid, term_timeout=10.0,
kill_timeout=5.0))`.

The one real obstacle a consolidation must resolve explicitly, not silently:
`tree_kill(pid, *, timeout: float = 10.0)` bounds the WHOLE kill (POSIX
poll-then-escalation combined, per its own docstring) with one caller-supplied
number, while `kill_pid_tree_async(pid, *, term_timeout=10.0,
kill_timeout=5.0)` takes two independently caller-supplied bounds, one per
escalation phase. Every current sync caller passes a single number, so
collapsing the signatures is a behaviour decision (map one number onto both
phases by some fraction, or grow `tree_kill`'s signature to match, breaking
its ten in-repo call sites) rather than a mechanical rename. Escalated to the
orchestrating agent for a ruling rather than actioned, per this campaign's
distinction between an unambiguous dedup and a design decision a sweep should
not make on its own momentum.

A related, narrower thread from the same follow-up:
`service_tests/harness.py`'s copy of the `detached-spawn-flags-triplicated`
finding (`_spawn_process`, only setting `creationflags` and never
`start_new_session`) is not a pure dedup either. Consuming the now-exported
`detached_spawn_kwargs()` there would newly detach that spawned child into its
own POSIX session, which it does not do today - a behaviour change the
harness's own owner needs to weigh against whatever the harness's teardown or
signal-propagation path currently assumes, not something to inherit silently
from an import swap. Recorded and handed to the harness-tier agent rather than
edited, since this domain does not own that file.

### desktop-catalog-derivation-repeated-the-just-fixed-billable-footgun | high | one sibling had already been fixed; this one had not

`src/vaultspec_a2a/desktop_tests/_catalog.py`'s `catalog_selection` took the
FIRST served lane satisfying `health.selectable and catalog.models`, with no
restriction to the in-process lanes. It was created during this campaign
(`1ab774b2`, "carry the catalog selection through every desktop run start") as
a sixth hand-rolled derivation, duplicating the already-landed canonical
mechanism (`src/vaultspec_a2a/testing/catalog_selection.py`, landed the day
before in `642f3333`) instead of consuming it. The most recent commit on this
file's own history, `a8904d12`, deleted the byte-identical failure mode from
its sibling `src/vaultspec_a2a/acceptance/_harness.py` - "carried its own lane
search, its own copy of the in-process id set, and a 'prefer in-process, else
take the first selectable' fallback" - and that commit's own reasoning applies
here unchanged: every desktop suite runs the `mock-success-single` preset,
pinned in its `.toml` to `provider = "mock"`, so a derivation that can return
ANY selectable lane is not a stylistic gap but a silent-substitution and
billable-lane risk on any developer box holding a live session for a real
provider - the exact hazard `first-selectable-lane-is-a-billable-footgun`
names. None of the six desktop suites armed `VAULTSPEC_SERVE_IN_PROCESS_LANES`
at their gateway spawn sites either, so the derivation had no in-process lane
to prefer even had it tried.

Verdict DUPLICATE on the mechanism, ACTIONED. `_catalog.py` now builds its
selection through `in_process_selection(payload, prefer_provider_id="mock")`,
keeping only what is genuinely local to this test tier - the httpx client and
the per-(base, workspace) cache, matching the guidance already recorded on
this cluster that the transport and the cache stay with the caller. The six
gateway-spawn call sites whose gateway is actually queried through
`catalog_selection` (`test_run_admission.py`, `test_lazy_worker.py`,
`test_owned_process_tree.py`, `test_terminal_settlement.py`, the primary spawn
in `test_ownership_prerequisites.py`, and both spawns in
`test_worker_provenance.py`) now arm `VAULTSPEC_SERVE_IN_PROCESS_LANES=true`
in the same change; two further `armed_gateway_env` calls in
`test_ownership_prerequisites.py` that never reach a catalog query (the
singleton-refusal contender and the stray-worker pairing probe) were
deliberately left unarmed. Verified by running all 21 tests across the six
affected files against real spawned gateways (all passed) and a whole-tree
`ty check src/vaultspec_a2a`. Not committed: this sweep's git access is
read-only status checks plus the audit-file commit described in its brief: the
code change is left in the working tree for the owning session to review and
commit.

### sse-frame-reader-duplicated-across-a-domain-boundary | medium | one mechanism, two owners, cannot be actioned from this domain alone

`src/vaultspec_a2a/acceptance/tests/_sse.py`'s `read_frame` and
`src/vaultspec_a2a/api/tests/test_progress_allowlist.py`'s `_read_frame` are
the same mechanism written twice: buffer `data:` lines, flush and JSON-decode
on a blank line, wrap the scan in `asyncio.wait_for` for a timeout, raise a
named `AssertionError` if the stream closes first. Found by four
differently-phrased `vaultspec-rag` searches - a behaviour-plus-nouns query, a
different-verb query, the failure-mode query, and the consumer's-view query -
of which only the second and fourth surfaced api/tests's copy; no third site
was found. The two differ only in caller-facing policy: the acceptance
version accepts `wanted=None` to match any non-heartbeat frame and skips
heartbeats explicitly, defaulting to a 30s timeout for a certification stack
that boots a real process tree; the api version requires an exact `wanted`
match with no heartbeat handling, defaulting to 5s against an in-process ASGI
app. Verdict DUPLICATE on the mechanism, POLICY correctly staying an argument.
Not actioned: a canonical home would need to sit above both `acceptance` and
`api`, and `api/tests` belongs to a different agent's domain in this
campaign - this sweep only reads outside `acceptance/`, `service_tests/`,
`desktop_tests/`, and `tests/`. Recorded for whichever domain ends up owning
the move; the acceptance-side call site and both timeout/heartbeat policies
are named above so a mover does not have to re-derive them.

### test-harness-tier-swept-and-found-clean | low | breadth covered without a new finding

Recorded for the negative space, since prior sweeps of this domain (the
selection cluster, the gateway-boot cluster, the JSON-assertion-helper
family, the terminal-status-in-service-tests duplicate, and the
detached-spawn-flags note handed off above) already cover most of this
tier's surface. Confirmed additionally clean by direct read rather than
inference: `service_tests/harness.py`'s docker-compose-orchestrated stack
(vidaimock, jaeger, worker and gateway as independently spawned uvicorn
processes under Docker) and `acceptance/_harness.py`'s direct armed-desktop
spawn (through the shared `tests/gateway_boot.py` primitives) are DISTINCT
lifecycles, not a duplicate wearing two names - one is Docker-owned
multi-service orchestration, the other a single production gateway process
that owns and spawns its own worker; their only real overlap, the
wait-until-healthy loop shape, is already recorded as DISTINCT probe content
under `correction-gateway-boot-is-three-probes`.
`service_tests/_provider_catalog_live.py`'s operator-authorized live-lane
selector is DISTINCT from the in-process mechanism by design, not an
uncounted twin of it: it validates against typed Pydantic catalog models
rather than raw dicts and additionally proves authentication and
completed-turn admission state, which is exactly the standard this
project's own served-profile admission rule requires and the in-process
mechanism explicitly does not check. `src/vaultspec_a2a/tests/` (the
package-root peer tier) holds only `gateway_boot.py`, already the
established canonical home, and `test_prerequisite_rule.py`, a real-subprocess
proof of the root conftest's external-prerequisite rule with no
duplicate-shaped logic found anywhere else in the four target directories.

### detached-spawn-flags-convergence-closed-in-service-harness | medium | closes the note handed to this domain, verified and fixed

Closes the `detached-spawn-flags-triplicated` copy this campaign's lifecycle
sweep explicitly handed to this domain rather than editing itself, because
consuming the canonical `detached_spawn_kwargs()` was flagged as a possible
POSIX behaviour change rather than a pure dedup. Established before touching
anything: `service_tests/harness.py`'s `_stop_process` tears every spawned
child down exclusively through `tree_kill` -> `kill_pid_tree_async`, which
discovers descendants by walking OS parent-child relationships
(`posix_descendant_pids`) and signals each pid directly - never through
`killpg` against a shared process group, which is the ONLY mechanism in this
codebase (`ProcessContainment`, layered separately in the provider RPC
handlers) that actually depends on the child sharing or owning a particular
POSIX session. Grepped `service_tests/harness.py` and its `conftest.py` for
any signal-propagation reliance (`SIGINT`, `signal.signal`,
`KeyboardInterrupt`, `atexit`) and found none. Direct precedent already exists
in this same tier for detaching a gateway-class child into its own POSIX
session while tearing it down through the identical pid-tree-walk primitive:
`tests/gateway_boot.py`'s `spawn_gateway(new_session=True)`, consumed by
`acceptance/_harness.py`. Verdict: the POSIX detachment is a deliberate,
correct convergence, not an accident being inherited silently - the site
previously read as written Windows-first with the POSIX half simply never
considered, and detaching it removes a real (if never yet observed) exposure
where a stray SIGINT delivered to the harness's own foreground process group
could kill the gateway or worker mid-`stop()`, out from under the diagnostics
capture that follows an unexpected teardown.

ACTIONED: `_spawn_process` now builds its flags through the canonical
`detached_spawn_kwargs()` instead of a bare
`getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)`, passing both
`creationflags` and `start_new_session` explicitly. On this Windows
development host the change is behaviour-identical (the canonical builder
also returns `start_new_session=False` there), which a fresh real-process
smoke test confirmed directly through the changed function - not merely
through the already-tested `tree_kill` primitive - spawning a process that
itself spawns a grandchild, then proving `_stop_process` fells both. The
existing `test_harness_process_stop.py::test_stop_process_tree_kills_grandchildren`
(marked `service`, needs no compose stack) was also re-run and passed
unchanged. The POSIX branch could not be exercised on this host; the verdict
above rests on the code-read evidence stated rather than on a live run, and is
recorded as such rather than overstated. Whole-tree `ty check src/vaultspec_a2a`
and `ruff check`/`format --check` on the touched file are clean. Left
uncommitted alongside the desktop-catalog fix above, for the owning session to
review and commit.

### structural-scan-finds-what-name-search-cannot | high | An AST scan normalizing away identifiers found duplicates the name-based guard was blind to, including a renamed clone of a concept that guard explicitly pins

Semantic search and grep both key on NAMES. A clone written under a different
name is invisible to both, and to the canonical-homes guard, which asserts a
declaration count for a spelling. Parsing every function, erasing every
identifier, and hashing the remaining structure keys on SHAPE instead, so it
sees a copy regardless of what its author called it. Run across `src/` it
reported 65 production groups of structurally identical function bodies.

Three were real and are now closed in `providers/`: two private `_json_object`
narrowers byte-identical to `lenient_json_object` in the same package (the
canonical-homes guard pins that exact concept to one declaration and did not
see them, because the clones were RENAMED); `kimi_catalog`'s own cancel helper,
written because the canonical `cancel_task` was over-constrained to
`Task[None]`; and a per-lane stderr drain.

Two limits of the method, both load-bearing when reading its output:

- It flags THIN BINDING SHIMS as duplicates. The `_read_response` wrappers in
  the ACP and Codex catalogs are structurally identical and CORRECT - each
  binds its lane's constants and error dialect to the shared reader. Consolidated
  code does not stop looking duplicated to a structural scan.
- It is blind to a clone that DIVERGED. See the next finding: an eighth site of
  a fragmented narrower differs by one argument and therefore hashes differently,
  so only semantic search surfaced it. Structure finds renamed copies; meaning
  finds drifted ones. Neither alone is sufficient.

### object-narrower-fragmented-across-control-worker-api | critical | One concept declared eight times across three packages, and the eighth silently accepts less than the other seven

Narrowing an untrusted value to a string-keyed object mapping - `TypeAdapter`
validate, return `None` on `ValidationError` - is declared independently in
`control/event_handlers.py`, `control/health.py`, `control/projection.py`,
`control/verdict_subscriber.py`, `worker/state_projection.py`, and
`api/routes/gateway.py`. No canonical home exists; semantic search for the
concept returns only the copies.

The critical part is not the count. `control/dispatch.py` declares the same
narrower with `strict=True`, so it REJECTS values the other seven accept - a
non-strict adapter coerces where a strict one refuses. Two competing answers to
one question are being consumed on different paths, and the divergence is
invisible at every call site because each reads a private helper with an
ordinary name.

A second, genuinely DISTINCT concept sits inside the same cluster and must not
be folded in: the `_json_object(encoded: str)` variants decode a JSON STRING
via `validate_json`, where the narrowers validate an already-parsed value.
Same posture, different input. `providers/team_selection.py` holds a third
posture - it RAISES a domain refusal instead of returning `None` - and is
correctly separate.

Rehoming requires deciding which acceptance is correct before choosing a home,
because consolidating onto the wrong one silently widens or narrows what six
call sites will accept. That decision is the work, not the move.

### object-narrower-consolidated-onto-strict-with-one-explicit-widening | high | Eight declarations converged on one home and one acceptance; the single site that could not inherit it widens visibly instead of dragging everyone lenient

Closes the fragmentation recorded above. The eight declarations now consume
`coerce_object_mapping` in `utils/coercion.py`, validated `strict`.

The decision rested on an EXECUTED probe rather than reasoning about pydantic
from memory, and the probe narrowed the question usefully: `MappingProxyType`
and hand-rolled `Mapping` implementations pass lenient validation and are
refused strict; `dict` subclasses and `OrderedDict` pass both ways; int-keyed
dicts, lists, and `None` are refused both ways. Lenient mode does not merely
accept a non-`dict` `Mapping` - it COPIES it into a `dict`, which is repair,
not narrowing. Strict was chosen because these sites sit at trust boundaries
where a value's provenance is precisely what is in question.

One site could not inherit that refusal, and it announced this itself.
`_checkpoint_id` in the worker state projection already tested
`isinstance(configurable, Mapping)` rather than `dict` - an existing statement
that a LangGraph config may arrive as a non-`dict` mapping. Under strict
validation its guard became self-contradictory: it would raise
"must be a mapping" about a value that IS a mapping, on a path that previously
worked. It now converts explicitly at that one call site, so the tolerance is
visible where it applies instead of every other caller silently inheriting a
lenient narrower to accommodate it.

Two neighbours were deliberately left DISTINCT: `_string_list` in
`control/dispatch.py` narrows to a list of STRINGS, a stricter contract than
`coerce_object_list`; and `providers/team_selection.py` RAISES a domain refusal
instead of returning `None`, a different failure posture serving a different
caller.

Process note worth keeping: the lane that did this work was lost to a
connection failure before it could report, so its reasoning had to be
reconstructed from the diff and its probe re-executed independently. The
self-contradictory guard was found during that re-verification, not by the lane
that wrote it. Work handed back without a report is not finished work, and
re-deriving the evidence is the only way to accept it.

### test-selection-helper-diverges-from-the-harness-it-copies | critical | A fourth copy of the served-lane selection drops the preset's pinned provider, so a mock-preset test is answered by the deterministic lane and asserts against the wrong tape

`service_tests/harness.py` resolves a served in-process selection by passing
`prefer_provider_id=_preset_in_process_provider(team_preset)` - it reads which
lane the preset PINS, and the docstring states why that pin is authoritative.
`test_dispatch_assignment_agreement.py` carries its own
`_served_in_process_selection` that calls `in_process_selection(response.json())`
with no preference at all, and `test_real_worker_run_completion.py` reaches the
same outcome. A third variant lives in `test_clarification_loop_stitched.py`.

The consequence is not a cosmetic difference. A test whose preset pins the MOCK
lane is answered by the DETERMINISTIC lane, then asserts content equality
against the mock tape. Today that surfaces as a failure. The dangerous case is
the inverse: an assertion loose enough to pass would report a mock-lane test as
green while a different provider answered it - the substitution pattern this
audit already names, now found live rather than hypothesised.

This is the campaign's signature shape at its sharpest. The canonical answer
exists, is documented, and explains itself; the copies did not adopt it, and
one of them silently dropped the argument that carries the whole meaning.
Rehoming here means consuming the harness's resolution, not re-deriving it.

### idempotent-permission-response-accepts-a-replay | high | A second permission response under the same idempotency key returns 200 where the contract says 409

`test_stale_second_permission_response_is_rejected_after_resume` expects a
replayed idempotency-keyed permission response to be refused with 409 and
observes 200. Reproducible in isolation, not a flake, and independent of the
test-scaffolding consolidation landed alongside it - every changed line in that
file is a mechanical call-site rename.

An idempotency key that does not refuse a replay is not an idempotency key. The
failing assertion is the contract, so the defect is in the responding path, not
the expectation.

### test-scaffolding-clusters-queued-with-verdicts | medium | Five duplicate clusters investigated and deliberately not actioned, each with a stated reason rather than silence

Recorded so they stay visible rather than becoming debt nobody named:

- The env-var set-and-restore mechanism is duplicated across three
  `control/tests/` modules, `lifecycle/tests/test_engine_serve.py`, and
  `cli/tests/test_desktop_serve.py` - a fifth site the original scan ranking
  missed. Mechanism-only, no policy divergence, no existing home. A
  `testing/environment.py` is the answer; deferred because it spans three
  packages with other lanes active in them mid-sweep.
- `_settings_override` in `cli/tests` and `api/tests` is byte-identical but a
  DIFFERENT mechanism from the env-var one: it mutates settings attributes
  rather than the process environment. Folding the two together would be the
  error; they are two concepts that look alike.
- `_install_receipt_graph` in the verdict-subscriber live/offline pair was
  checked specifically for a live dependency leaking into the offline path. It
  does not: both build against an unreachable bridge and an in-memory
  checkpointer, so the live file's live-ness is elsewhere. Safe, deferred.
- `_reply` across three `authoring/tests/` modules is a METHOD on an inline
  request-handler subclass, so extraction needs a shared mixin rather than a
  move - a different and larger change than the others.
- The `desktop_tests/test_runtime_singleton.py` group was truncated in the scan
  output and its partner could not be re-derived by search. It needs a fresh
  structural pass rather than a guess; the standing guard will surface it.

### served-lane-selection-fixed-and-the-inventory-that-was-wrong | critical | The lane substitution is closed, and the site that caused it was not among the three the triage named

Closes the selection-helper finding above, with two corrections to that entry
worth more than the fix itself.

**The named inventory was wrong in both directions.** The triage listed
`test_real_worker_run_completion.py` as a third copy; grep for the exact symbol
shows it has none. Its failure came from a FOURTH site nobody had listed -
`acceptance/_harness.py::CertifiedGateway._resolved_run_fields` - which every
`acceptance/tests` test and both certified service tests reach through the
shared gateway fixture. A triage list assembled from a structural scan and a
reading of three files missed the site with the widest blast radius, because
that site is not a copy of the named helper at all: it is the same MISTAKE made
independently. Deduplication finds copies; it does not find a shared error
reached by different routes.

**One copy was already correct by coincidence.** `test_clarification_loop_stitched.py`
pins the deterministic lane, which is also what registry order returns first
when both in-process lanes are served, so its missing preference produced the
right answer every time. It agreed by upkeep, not by declaration - the same
pattern this audit flagged for the reviewer verdict constants - and a change to
registry order or to that preset would have broken it silently.

**Layer verdict, settled from source rather than assumed.** The defect is in
the callers. `testing/catalog_selection.py` declares in its own docstring that
it owns the MECHANISM and that WHICH lane is the caller's decision;
`in_process_selection` documents its fallback as intentional; and
`providers/in_process_catalog.py`, the code that actually serves, has no concept
of team presets, so it cannot enforce a binding it cannot see. The single
caller that was already passing a preference demonstrates the intended pattern.
Fixing the eligibility layer would have moved policy into a module that
deliberately refuses to hold it.

`_preset_in_process_provider` is promoted from one test harness into
`testing/catalog_selection.py` as `preset_in_process_provider`, now that four
callers across three tiers need it.

### frozen-and-executed-model-disagree-independently-of-lane | high | The dispatch agreement test fails on model, not provider, and always did - a separate defect the lane fix does not touch

`test_dispatch_assignment_agreement.py` still fails after the lane fix, and
re-reading the evidence shows it was never the lane bug: `provider` agreed
between the frozen assignment and the executed agent in every run, before
(deterministic/deterministic) and after (mock/mock). The only field that ever
disagreed is `model` - the executed agent reads back `None` where the frozen
assignment names a concrete value such as `mock-high`.

Traced one level and stopped deliberately: `graph/compiler.py::_model_assignment_metadata`
renders `model` as a bare CAPABILITY tier (e.g. `mid`) or an empty string, and
`thread/snapshots.py::build_agent_descriptor` then passes it through
`coerce_model()`. Two readings remain open and they have opposite fixes -
either capability is genuinely unset for in-process pipeline nodes at compile
time, which is a real gap in the frozen-assignment contract, or the test is
comparing a compound catalog `model_name` against a bare capability tier, which
means two vocabularies were never meant to match and the assertion is wrong.

Recorded rather than guessed. Deciding it needs the frozen-assignment
disclosure contract, not this campaign.

### executed-side-cannot-disclose-which-model-ran | critical | The compiler holds the frozen model name, runs it, and publishes only a capability tier - so the one test checking frozen-versus-executed agreement compares two vocabularies and cannot pass

Resolves the open question recorded above. It is the first reading - a real gap -
but the gap is not "capability is unset at compile time". The frozen model name
is IN SCOPE at the publishing call site and simply is not passed.

The chain, read end to end:

- `_resolve_worker_model_preferences` returns four values, the fourth being
  `frozen_model_name` - the concrete catalog identifier such as `mock-high`.
- The factory is then called with `model=frozen_model_name` for the primary
  provider, so the worker GENUINELY RUNS the frozen model. The freeze is
  honoured in execution.
- But the node metadata is built by `_agent_node_metadata(agent_cfg,
  used_provider, capability)`, whose signature admits only the CAPABILITY tier.
  `_model_assignment_metadata` renders `model` as `capability.value`, or the
  empty string when capability is `None`.
- Node metadata is the only executed-side surface: `build_agent_descriptor`
  reads `summary.get("model")` and every agent-listing surface - the REST route,
  the thread snapshot, the broadcast - projects from it.

So the executed side reports a capability tier, or nothing, where the frozen
assignment promised a catalog model name. `test_dispatch_assignment_agreement`
compares `actual["model"]` against `promise["model_name"]`, which are two
different vocabularies, and it therefore cannot pass regardless of what runs.
The test's INTENT is correct and is the only check of this contract; its failure
is a TRUE POSITIVE reporting that the disclosure surface has lost the fact it
exists to disclose.

Why this is worth more than a failing test: the frozen assignment is the
authoritative start-and-commit disclosure for a run. A run can promise
`mock-high`, actually execute `mock-high`, and leave no observable evidence that
it did. Provider agreement works only because provider IS published; model is
the field with no witness. The same shape would hide a genuine substitution.

The fix is a contract decision and is NOT taken here, because node metadata's
`model` field is consumed by `/team/status`, the `team_status` broadcast, the
thread snapshot, and the REST agent route, all of which currently receive a
capability tier:

- Publish the concrete model name in `model`, making the field mean "what ran".
  Truthful, and the vocabulary the freeze speaks - but it changes what four
  existing consumers receive.
- Add a separate field carrying the concrete name and leave `model` as the
  capability tier. Non-breaking, but perpetuates two similarly-named fields in
  two vocabularies, which is the confusion that produced this finding.

Recommendation is the first, on the grounding that a disclosure surface should
report what happened rather than the tier it was requested at - but it is the
owner's call, and it needs the frozen-assignment disclosure contract rather than
this campaign.

### correction-the-tier-field-is-vestigial-not-merely-mismatched | critical | Supersedes the recommendation above: the capability field cannot hold a catalog name, and on the frozen path it is hardcoded to None for every run

The preceding entry's diagnosis stands but its RECOMMENDATION was wrong and is
withdrawn. It proposed publishing the concrete model name in the existing
`model` field. That is not a contract change, it is a type violation:
`graph/enums.py::Model` is a four-value `StrEnum` (`low`, `mid`, `high`, `max`)
and `api/schemas/events.py::AgentSummary` types the wire field as
`Model | None`. A compound catalog identifier such as `mock-high` cannot be
carried there at all.

Two facts sharpen the diagnosis beyond "the name is not passed":

- **Capability is hardcoded, not merely absent.** `_resolve_model_for_worker`'s
  frozen branch ends `return model, provider, None` - an explicit `None`, not
  missing data and not an artefact of the in-process lane. Since explicit
  selection is now required at every run start, that branch is taken for EVERY
  worker, so the capability the node metadata publishes is `None` on every
  production run.
- **The tier field is therefore vestigial on the wire, not just mismatched.**
  `AgentSummary.model` is now permanently `None` for frozen runs, and its own
  docstring states the field is optional only because "an agent can be observed
  before its model assignment resolves" - an invariant that is now false
  forever rather than transiently. A field documented as resolving has stopped
  resolving.

That also separates the two fixes cleanly, which the withdrawn recommendation
blurred. Populating a capability tier for frozen runs would still never make
`"mock-high" == "high"` true, so closing the disclosure gap and making the
agreement assertion pass are genuinely different changes, not one change viewed
two ways.

The corrected fix is ADDITIVE: carry the concrete `model_name` that
`_parse_catalog_preferences` already extracts through the resolver's return,
into `_agent_node_metadata`, and onto `AgentData` and `AgentSummary` as its own
field. Additive because the broadcast is consumed by a separate repository, so a
new field is safe where a retyped one is not. The agreement test then compares
`model_name` against `model_name` - one vocabulary, and an assertion that can
finally fail for the right reason.

## Method: what actually found these findings

Recorded because it is the campaign's most transferable output. Both lanes that
worked the hardest clusters reached the same conclusion independently, and it
contradicts how this campaign was originally framed.

### Counting sites found almost nothing

The question that produced every sharp finding was **"what else could a writer
have chosen?"** - not "how many sites are there?". Counting is what a converter
does, and a converter finds only the sites that already look alike. It found none
of: the guard rows pinned to one member of a set, the names promising narrower
contracts than their callers relied on, or the docstring asserting a guarantee its
code lacked.

Corroborating this from the other direction: **every site count handed to a lane
in this campaign was wrong on first issue.** Seven inventories were materially
wrong, one by being stale rather than incomplete. A count in a task title is a
hypothesis, and every brief now says so and requires re-derivation.

### The site left behind is the hardest one, by construction

The pattern hit three times - the vocabulary cluster, the atomic-writer cluster,
and the earlier hardening helper - and the first framing of it here ("a cluster
closed one file early") was too generous to the converter. The sharper statement:

> The site left behind was not overlooked. It was the site the home could not yet
> serve.

A converter working site-by-site converts everything that FITS and leaves exactly
the case that required the home to GROW. So the residue is not the leftover easy
work; it is the hardest case in the cluster, and it is guaranteed to be what
remains. The credential mint is the clean example: it could not pass a Windows
DACL through a parameter typed as an integer mode, so it kept its own
implementation, and no amount of care applied site-by-site would have converted
it.

**The cheap tell, available before any grep:** if the unconverted sites each carry
a LOCAL WORKAROUND, the home is too narrow - not the callers lazy. Workarounds
clustered around a canonical home are the shape of a home that does not cover its
subject. That is the same reading as the lying-name finding, seen from the caller
side.

### Searching for the domain word instead of the value

A lane sweeping for a wire literal searched the DOMAIN WORD and got back a config
setting and a route handler - both containing the word, neither being the wire
literal - and nearly reported a confirmed premise as unconfirmed. The token on the
wire was the enum's VALUE, and the two are adjacent enough to be indistinguishable
in a result list.

Recorded as a standing instruction: when checking whether a vocabulary is
hand-copied, **search the value the enum holds, not the concept it names.** The
same caution applies to this repository's observed identifier masking in search
output - a structurally surprising result is verified by reading the lines, not by
trusting the match.

### Two structural guards were considered and REJECTED, with reasons

Neither rejection is a concession that the rule is unenforceable; both are cases
where the available guard would have asserted something false.

- **A row pinning the lenient-narrower helper.** It could pin the helper's NAME,
  which a renamed copy passes - the original weakness that let the duplicate
  exist - or the SHAPE, which now legitimately occurs at five correctly-DISTINCT
  sites. Its count would therefore be either meaningless or actively misleading,
  implying five settled decisions were pending work. A guard that mislabels
  settled decisions as debt is worse than no guard.
- **Restating a precondition inside a consolidated reader.** Rejected in favour of
  ASKING the boundary function that owns the rule. A re-derived predicate is a
  second declaration that stops agreeing the moment its owner changes, and writing
  one reads as defensive rigour while being exactly the defect under repair.

### One layering question, settled

Where a vocabulary was shared across layers that must not import upward, the
resolution was to move the declaration DOWN to the layer where its subject is
defined, not to import upward from the lower layer. Recorded so the direction is
not relitigated per cluster.

### the-credential-mint-copied-a-private-function-by-name | high | sharpens the atomic-writer finding

Two corrections to the atomic-writer entry above, both established against `HEAD`
rather than the working tree.

**The duplicate is a wholesale copy, not a reimplementation.** Both modules define
a PRIVATE function of the SAME NAME, with the same body shape and the same two
constants. Independent authorship does not converge on another module's private
name. This is the cleanest evidence in the cluster that the author had the
canonical module open - stronger than the copied Windows rationale, because a
comment can be paraphrased from shared knowledge and a private name cannot.

**Only the hardening ever needed the home to grow.** The earlier entry left open
whether the rename retry also had to move. It did not: the canonical writer
already carried the retry budget, the retry parameter and the full retry loop,
with the same interval. So the retry was never a capability the home lacked - it
is duplicated with no justification at all, and deleting it removes work rather
than relocating it.

That narrows the general claim recorded in the method section. The residue is
still the case the home could not serve, but only PART of a residual site is
usually that case; the rest is ordinary duplication that travelled with it. A
converter should separate the two, because they have different fixes - grow the
home for one, delete outright for the other.

**The ordering inside the residual case is the load-bearing part.** The mint
hardens the TEMPORARY file before the rename, so the target never exists in a
briefly-readable state. A fold that hardens after the rename produces an identical
end state and silently loses the invariant, failing nothing and detectable only in
a timing window nobody observes. Recorded because it is the same silent-success
shape as applying file-shaped permissions to a directory: correct-looking, wrong
only where no one is watching.

### in-flight-edits-read-as-established-prior-art | medium | method hazard, live this session

While verifying whether the canonical writer could already express the mint's
requirement, both semantic search and the working tree showed a hardening
parameter that looked like long-standing prior art. It was another lane's
UNCOMMITTED work, written minutes earlier under this campaign's own brief.

Reporting it as pre-existing would have inverted the finding - it would have
recorded that the home always served the case and the caller simply failed to
adopt it, which is the opposite of what was true and would have retired a valid
cluster.

`git show HEAD:<path>` is the check that separates a lane's in-flight edits from
the baseline, and in a shared worktree with concurrent writers it must be run
before any claim that a capability "already exists". Recorded as a standing rule,
not an anecdote: this campaign runs several lanes in one tree by design, so the
hazard is structural rather than incidental.

### disclosure-gap-closed-and-the-two-seams-that-found-themselves | critical | The executed model is now disclosed; two of the three seams that had to admit the field were found by existing tests, not by reading the code

Closes the disclosure gap. `model_name` is threaded from the compiler's frozen
branch through node metadata onto `AgentData`, `AgentSummary`, and
`_AgentSnapshot`, and the agreement test now compares like with like and passes
for the first time.

The implementation lesson is where the field had to be REGISTERED, because
reading the code found only one of the three places:

- `api/schemas/snapshots.py::_AgentSnapshot` was surfaced by an existing
  parity test, which also explained the stakes better than the code did: its
  seam is `model_validate(asdict(...))`, which ignores unknown keys, so a field
  added on one side is dropped silently rather than loudly.
- `streaming/node_metadata.py::NODE_METADATA_FIELDS` is an explicit allowlist
  whose docstring states that adding a field there reaches every reader at
  once. Until the field was registered there the value stopped one layer short
  of the wire - and every type check passed, because nothing about the type
  system knows that an allowlist exists. The live test still returned `None`.

Both are canonical homes behaving exactly as designed, which is the useful part:
a correct-looking change threaded through five files was still incomplete, and
what caught it was a guard someone had written earlier for precisely this. The
same shape as the campaign's own structural guard, and evidence that the guards
this project already carries are worth more than a careful reading.

Two decisions worth keeping:

- The identifier is carried BESIDE the capability rather than replacing it. The
  capability field remains vestigial on frozen runs, which is recorded above and
  is a separate decision; overloading it was impossible anyway, since the wire
  types it as a four-value enum.
- The value is ABSENT rather than empty at the source, so a caller can tell an
  unfrozen run (no catalog identifier exists) from a frozen run that named none.

Verified the assertion can still fail: substituting the published identifier
turns the test red on all three roles, and reverting restores green. The test
was rewritten from one that could never pass, so proving it can now fail was
the only way to know it asserts anything at all.

## Domains swept and found HEALTHY

Recorded so later sweeps do not re-walk them, and because a campaign that only
records defects gives no sense of what fraction of the codebase is sound. Each was
reached by semantic search and confirmed by reading the candidate sites, not
assumed.

- **Untrusted-mapping coercion.** One home, twelve consumers, no rivals found.
- **Identifier validation and idempotency-key derivation.** One home, eleven
  consumers, including consumers in other packages. Notably it derives its grammar
  from the ENGINE's own validation macro and says so, rather than hand-copying the
  rule - the pattern this campaign wants for every cross-repo constraint. The
  nearest-looking neighbour, thread-nickname generation, is DISTINCT: it MINTS a
  friendly name, it does not validate an id.
- **Text capping policy.** The differing policies are documented contract
  differences, not drift: refuse at the producer so an elision is deliberate,
  refuse inbound where rejecting a malformed request is the safe answer, truncate
  outbound where raising would kill the frame it was bounding. Each states its
  reason. Only the two BOUND VALUES recorded above are defective, not the policies
  that apply them.
- **ISO-timestamp handling.** Looked like five duplicate sites and is not:
  serializing library timestamp variants, parsing to an epoch, and validating a
  producer's string WITHOUT normalising it are three different jobs. The semantic
  query matched loosely; reading the sites settled it.
- **Server-sent-event framing.** Two modules that read as duplicates are an
  ENCODER and a DECODER. The encoder additionally reads the frame-type key through
  its owner rather than inlining it, which is the behaviour the decoder is being
  corrected to match.

The negative results are worth as much as the findings here: three of these five
were candidate clusters that a count-based sweep would have opened as work. What
retired them was reading the sites and asking what each writer was actually FOR -
the same question that found the real defects.

### registration-lists-are-invisible-to-type-checking | critical | method, generalised from a live incident

Generalised from the disclosure-gap closure recorded above, because it is a
hazard this campaign CREATES rather than one it merely finds, and every lane
consolidating into a canonical home is exposed to it.

A canonical home often decides not just where a value lives but WHAT MAY PASS.
Four shapes seen in this codebase: an explicit per-event field allowlist, a
discriminated union, a `model_validate` over a dataclass dump that ignores
unknown keys, and a module's export list. All four are canonical homes behaving
exactly as designed.

All four are also **invisible to the type checker**. Nothing in the type system
knows an allowlist exists, so a value threaded correctly through every layer can
stop one layer short of the wire with every check passing. In the live case the
change touched five files, `ty` was clean, and the value arrived as `None`
because it had not been REGISTERED. Reading the code found one of the three
registration sites; guards written earlier for exactly this found the other two.

The failure is silent by DESIGN, which is what makes it dangerous. The event
catalog's own docstring states that an unrecognised frame is projected onto its
identity keys rather than refused - degrading rather than failing is the correct
choice for a droppable channel, and it means a mismatched key produces a frame
that is structurally valid and materially empty. Nothing raises. A test asserting
the frame's TYPE passes; only one asserting its CONTENT does not.

**The rule.** When moving a value into a canonical home, ask what REGISTERS the
things that may pass, not only what declares the value. And set the acceptance
bar accordingly: proving no old declaration remains proves the refactor happened,
not that it works. The bar is a real payload, from the real producer, arriving at
the real consumer with its fields intact.

**The corollary is the campaign's strongest evidence for guards over review.** The
two missed seams were found by tests someone had written earlier for precisely
this class of mistake - a parity test and an allowlist's own coverage. A careful
read found neither. This sits beside the two guards this campaign REJECTED: the
distinction is that these guards assert an invariant that must hold, while the
rejected rows would have asserted a name a rename defeats or a count that
mislabels settled decisions as debt. Guards are not the problem; guards pinned to
spellings are.

### a-closure-grep-nobody-ran-is-an-assertion | high | indicts this campaign's own process

This campaign requires a closure grep in every commit message as proof that the
old declarations were deleted. A lane then caught its OWN printed grep failing to
reproduce: it was written against a bare assignment while the declaration carried
a type annotation, so the pattern matched nothing. The claim was true and the
printed proof did not prove it.

That makes the requirement theatre in exactly the cases it exists for. A reader
auditing the campaign later runs the pasted command, gets no output, and cannot
distinguish "the deletion succeeded and the regex is wrong" from "the deletion
never happened" - and the second is the one the requirement was invented to catch.

**Rule, now standing: run the closure grep and paste its ACTUAL OUTPUT, never a
regex you believe should match.** A proof nobody executed is an assertion wearing
a proof's syntax. The corrected form was verified independently and returns
exactly one hit at the new home.

Recorded at high severity despite changing no production code, because it is a
defect in the campaign's evidence standard rather than in the codebase, and every
closure claim made before it rests on the same unchecked step. The lane was right
not to rewrite history to hide it.

### a-bound-restated-inside-an-error-message | high | DUPLICATE, the sharpest form

Re-deriving the workspace-root inventory turned up a tenth site the original nine
missed: the bound spelled out again inside the validator's error message string.

It is the sharpest restatement in the set because it is **the only one that can
drift into a LIE rather than into a wrong check.** Every other copy, when it
diverges, rejects the wrong inputs - bad, but self-evidently a bug once observed.
This one keeps rejecting correctly while TELLING THE CALLER THE WRONG LIMIT, so
the caller retries against a number the system does not enforce and cannot
discover the real one from the message. A wrong check fails loudly at the caller;
a wrong explanation sends them somewhere else.

It also sits directly beneath a named constant it does not use, and the correct
pattern - composing the sentence from the constant by interpolation - already
exists two modules away and was not copied.

Recorded also as evidence for the method section's claim that counts are
hypotheses: the inventory's nine were all real and all correct, and were still not
all of them. **A count can be wrong by being incomplete even when every entry in
it is right**, which is the failure mode a confident inventory hides best -
nothing about checking the nine would have revealed the tenth.

### the-same-two-modules-did-it-twice | high | DUPLICATE, out of the original scope

The feature-tag bound repeats the workspace-root pattern exactly: a column that is
the real authority, two separately-named module constants that do not reference
each other, and an inline restatement in a route parameter.

What makes it worth its own entry is that it is **the same two modules and the
same pair of naming decisions**, made independently a second time. This is not one
oversight that happened to recur; it is a habit with a stable signature - each
module reaches a bound, decides it deserves a local name, does not look for an
existing one, and picks the value from the column by reading rather than by
importing.

A third occurrence of the same number sits in one of those files and is DISTINCT
in subject: its authority is a grammar regex rather than a column. It is recorded
here precisely so it is not swept into the same constant on the strength of
sharing a value - the trap this campaign has now hit from both directions, since
six other sites sharing this cluster's other number were also correctly ruled
DISTINCT.

### epoch-ms-now-is-re-derived-around-a-name-collision | low | The canonical now_ms is re-derived at five production sites, and at three of them the local variable or parameter is itself called now_ms, which is why importing it was never the obvious move

`lifecycle/registry.py::now_ms` is exported and is the canonical epoch-millisecond
clock. `lifecycle/registration.py` imports and calls it. Five other production
sites compute `int(time.time() * 1000)` inline instead:
`lifecycle/discovery.py` (four occurrences), `lifecycle/singleton.py`,
`control/health.py`, `authoring/discovery.py`, and `testing/leases.py` (six).

All agree semantically - same unit, same epoch, no timezone divergence - so this
is duplicated, not diverged, and it is recorded as low.

The detail worth keeping is WHY it persisted, which a count of the sites does
not show. At three of those sites the re-derivation is written as
`now_ms if now_ms is not None else int(time.time() * 1000)`, or as a local
assignment `now_ms = int(time.time() * 1000)` - the caller-supplied override and
the canonical function have THE SAME NAME. A plain
`from ..lifecycle.registry import now_ms` would be shadowed by the parameter at
exactly the sites that most need it. Converging therefore requires renaming a
parameter or aliasing the import, which is a slightly larger change than the
finding's severity suggests and is the likeliest reason nobody did it.

Bundle it with the next change that touches these files rather than taking it
alone. Recorded so the name collision is discovered once rather than by each
person who tries.

### sweep-of-six-hardened-packages-returned-a-negative | medium | An agent sent to desktop, telemetry, workspace, lifecycle, authoring, and database re-derived findings the audit already held, which says more about the assignment than the packages

A discovery lane was dispatched to hunt the one pattern both of this campaign's
detection methods are blind to - the same MISTAKE made independently, where the
implementations do not look alike and so match neither a structural hash nor a
name search. It returned essentially clean.

The result is honest and the evidence is named: `telemetry/instrumentation.py`,
`telemetry/middleware.py`, `telemetry/aggregator_hook.py`,
`workspace/environment.py`, `workspace/concurrency.py`, `lifecycle/pairing.py`,
and `lifecycle/registration.py` were read in full and carry no internal
duplication; `is_pid_alive` was confirmed single-homed across the entire tree
including tests; and `workspace/environment.py`'s credential scrub set is the
sole declaration, correctly imported by its provider consumer rather than
re-derived.

The lane also refused a false positive worth recording: `httpx.Timeout` is
constructed with different budgets in `api/app.py`, `worker/ipc.py`, and
`authoring/client.py`. Three transports, three failure domains, and this
project's standing rule already entitles each to its own budget. Do not merge.

The finding is about the ASSIGNMENT, not the packages. Those six are the ones
this campaign has hardened hardest, and sending a fresh lane into them bought a
confirmation rather than a discovery. The packages carrying the most unexamined
surface are the ones the sweep has never targeted directly - the large route and
schema modules, the graph compiler, the streaming transformer, and the
thread/team/ipc/context/mcp/tools packages. Coverage should be steered by where
the campaign has NOT been, and that is not the same as where the code is
newest or least familiar.

### the-fork-was-better-than-the-home-in-two-ways | critical | inverts a campaign assumption

Folding the credential mint into the canonical writer did not simply retire a
worse copy. The fork carried TWO protections the canonical home lacked, and both
had to be moved INTO the home or the consolidation would have weakened the caller:

- **Refusing to follow a symlink** at the temporary path. Without it, a link
  planted at the predictable temporary name redirects a write the caller
  specifically asked to keep private.
- **Opening in binary mode.** Verified empirically on Windows: the canonical
  writer's permission-bearing path called `os.open` without the binary flag, so it
  opened in TEXT mode and translated line endings - while its own docstring
  claimed it "writes bytes directly". The audited, canonical, four-consumer home
  was not writing the bytes it was given, on this platform, for every
  credential-bearing record.

**This inverts an assumption the campaign has been running on.** The working model
was that a duplicate is a worse copy of a better home, so consolidation is a
strict improvement and the only risk is missing a site. Here the duplicate was
BETTER in two respects, one of them a live latent defect in the home, and neither
was discoverable until someone tried to merge them.

So consolidation must audit in BOTH directions. Moving a caller into a home
without asking what the caller knew that the home does not is how a fold silently
DOWNGRADES a security property - and it would have downgraded one here, quietly,
with every check green.

This is the deeper form of the tell already recorded ("if the remaining sites each
carry a local workaround, the home is too narrow"). The refinement: a local
workaround is not always a workaround. Sometimes it is the only correct
implementation in the codebase, and the canonical home is the copy that drifted.

**Corollary worth stating plainly.** The latent defect was found because a caller
with STRICT byte requirements was folded in. A home is only proven to the standard
of its most demanding consumer, so folding the hardest caller last means the home
goes longest unaudited - and every existing consumer inherited the defect in the
meantime. Two lifecycle records were being written with translated line endings
against a contract that promised otherwise.

### one-function-two-branches-two-security-postures | high | asymmetry inside a canonical home

Reported by the lane that closed the cluster and deliberately not fixed there,
since it is outside that cluster.

The canonical writer's two branches now disagree about symlink protection: the
permission-bearing path refuses a planted link at the temporary name, the plain
path follows it, because the latter uses the builtin open. One function, one
name, one docstring, two security postures selected by whether an unrelated
argument was passed.

Currently latent - every plain-path caller writes non-secret records - so it is
recorded rather than escalated. But it is the shape this campaign exists to
remove: a single canonical home whose guarantee depends on which branch you land
in, discoverable only by reading the implementation. A caller reasoning from the
function's name and docstring cannot know which posture it gets.


### structural-duplication-is-exhausted-and-that-bounds-what-is-left | medium | A scan at less than half the standing floor over the never-swept packages returned seven groups, every one of them correct design

The standing guard runs at a forty-node floor, which it documents as
deliberately hiding small copies. That leaves an obvious question the campaign
had not answered: what is under the floor in the packages the sweep never
targeted directly?

Scanned `api/routes`, `api/schemas`, `graph`, `streaming`, `thread`, `team`,
`ipc`, `context`, `mcp`, and `tools` at a floor of EIGHTEEN. Seven groups, and
none is a defect:

- Two are already allowlisted with reasons (the lazy-import shim, the debounced
  broadcast pair).
- `coerce_model`/`coerce_provider` and `_bool_field`/`_string_field` are the
  same shape applied to different enums and different types in one module - the
  parametrize-or-name-it trade-off the allowlist already documents, resolved in
  favour of naming.
- The remaining three are `streaming/aggregator.py` delegators. That module is a
  FACADE: every method forwards one line to a sub-manager. The repeated shape is
  the architecture this project mandates for sub-modules, correctly implemented.
  A structural scan cannot distinguish a facade from a copy, because at the AST
  level they are the same thing.

The useful conclusion is a BOUND, not a clean bill of health. Structural
duplication above eighteen nodes is now exhausted tree-wide: every surviving
group is either reviewed or is a pattern the project deliberately requires.
Whatever fragmentation remains is therefore NOT copy-shaped, and no amount of
further scanning will surface it.

That is consistent with what this campaign's most consequential findings looked
like. The lane-substitution defect was four sites making one mistake by
different routes with no shared shape; the disclosure gap was a value discarded
rather than duplicated. Neither would have appeared in any structural scan at
any floor. Remaining effort belongs on semantic search for concepts answered
independently, and on divergence between sites that already agree in shape -
not on finding more copies.

### correction-the-copy-was-more-factored-than-the-original | medium | sharpens the copy-direction evidence

An earlier entry here states that the credential mint and the canonical writer
defined a same-named private function "with the same body shape and the same two
constants". The last clause is wrong, and the true shape is better evidence than
the claim it replaces.

Verified against the pre-fold baseline: the COPY declared two named constants -
the retry budget and the sleep interval. The canonical home declared one named
constant and left the interval as a bare literal in its sleep call. Same name,
same body shape, same values; not a symmetric pair.

So the copy was MORE FACTORED than the original. That is the giveaway, and it
settles the direction of transcription: someone reading the canonical module
extracted its inline literal into a name while copying it. A copy that merely
drifted would be equally or less factored than its source; improving the thing you
are duplicating is the signature of deliberate transcription by someone who had
the original open and thought about it.

Recorded as a correction rather than an edit because the campaign's convention is
that withdrawn and amended claims stay visible. It also stands beside the finding
that the fork carried two protections the home lacked: in both respects the
duplicate was the better-tended copy, which is the opposite of the model this
campaign began with.

### a-docstring-narrating-someone-elses-convergence | medium | method hazard, second variant

A lane grounding itself found a module whose docstring already narrates publishing
through "the shared writer", which reads as proof that the fold it was dispatched
to perform had already happened. It had not. That module is a DIFFERENT consumer
which converged earlier; the target was still the last writer standing outside.

This is the second variant of the same trap and it is harder to see than the
first. The uncommitted-edits case at least requires a concurrent writer, and
`git show HEAD:` settles it. Here the text is committed, accurate, and long-
standing - it is simply ABOUT A DIFFERENT SUBJECT. No baseline check disambiguates
it, because nothing is wrong with it.

**What settles it is asking which consumer the sentence is about, not whether the
sentence is true.** In a codebase where several callers converge on one home at
different times, prose describing convergence accumulates in the callers that
already moved - so the more successful a canonical home is, the more surrounding
text will suggest that any given holdout has already adopted it.

Recorded because both variants were hit within an hour, in opposite directions,
by different lanes: one nearly reported an unfinished fold as done, the other
nearly reported another lane's in-flight work as long-standing prior art.

### the-orchestrator-dispatch-list-went-stale-twice | high | Two of five assigned clusters were already fixed, and a third assignment named a site that did not exist - in both cases the lane caught it because the brief required verification

Two dispatches in this campaign carried target lists that were wrong at the
moment they were sent:

- A lane was told to consolidate five provider-catalog clusters. Two of them -
  the `_local_id` trio and the `_display` pair - had already been consolidated
  into `_catalog_fields.py` by commits that landed BEFORE the dispatch. Only
  three were live work.
- An earlier lane was told a named helper existed in a module that has never
  declared it, and the site that actually caused the failure was not on the
  list at all.

The cause is the same both times and it is an orchestration defect, not a lane
defect. The target lists were derived from a scan snapshot and then dispatched
without being re-derived against `HEAD`. In a tree with several lanes committing
concurrently, a duplication inventory is stale almost immediately: the very
campaign that produces the list is also consuming it.

What prevented both from becoming wasted or destructive work is that each brief
required the lane to VERIFY the finding before acting, and to say so if a
judgement did not survive contact with the source. Both lanes did exactly that -
one checked `git log` and `git diff` and reported the clusters already resolved,
the other grepped for the exact symbol and reported it absent. Neither
"corrected" the brief silently, and neither implemented against it blindly.

The practice to keep: a dispatch list is a HYPOTHESIS, and the brief must say so.
Re-deriving the inventory at dispatch time would reduce the error but cannot
eliminate it while lanes commit in parallel, so the durable fix is the
instruction rather than fresher input. An agent told to execute a list will
execute a stale one; an agent told to verify first reports the staleness back.

### correction-the-liveness-writers-were-not-a-live-bug | high | withdraws an overstated hazard

The worker-liveness entry above states that the two readers "degrade silently"
and that such a degradation "presents as worker unreachable". The lane that
closed the cluster reports, and I accept, that **there was no live bug.** Every
one of the five writers happened to pick the same attribute name, so the old code
was functionally correct on every path.

The finding stands, but as a STRUCTURAL one: nothing made the five agree, and the
defaulted reads were the evidence that no reader could assume they would. What
does not stand is the implied live failure. I wrote a consequence that the code
did not have, and a hazard framing is exactly where an audit is most tempted to
overstate, because the fix looks more justified the worse the status quo sounds.

Recorded prominently because the lane could have delivered the fix under the
premise I supplied and let the stronger claim stand unchallenged. It declined to
manufacture a bug narrative and said so in the commit. **A structural finding does
not need a live bug to justify it**, and dressing one as the other spends
credibility this audit needs for the findings that ARE live - the byte-translation
defect and the containment relative-root, both of which were real.

### two-predicates-that-look-like-complements-and-are-not | high | widening done correctly

Consolidating the liveness readers surfaced a case where forcing one predicate on
both callers would have LOST a distinction, and the lane widened the home instead
of flattening the callers - the tell this campaign records, applied in the field.

The two readings are not complements. One asks whether contact is fresh (age
below the timeout); the other asks whether it is stale (age above it). At exactly
the timeout neither holds, and more importantly **a never-contacted worker is not
stale** - reporting it stale would hand the watchdog a crash signal for a worker
that is still starting.

So the home declares both predicates over one shared age computation rather than
deriving one from the negation of the other. Recorded because "these two booleans
are inverses" is the single most inviting simplification in a consolidation, and
here it would have introduced a real defect into code that had none.

### convert-the-whole-keyed-set-or-none-of-it | high | generalises the partial-conversion disease

The event catalog keyed all twelve of its entries by literal. The task named one.
Converting only the named entry would have left a single enum key among eleven
literals - which is the precise disease the task existed to remove, since a reader
checking whether the vocabulary is canonical finds a declaration in use and stops.

The lane converted every enum-covered key and left three literals that the enum
does not declare, with a comment recording why the mixture is correct rather than
residual.

The general rule: **a partially converted keyed set is worse than an unconverted
one.** An unconverted set is honestly uniform and a sweep finds all of it; a
mostly-converted set looks finished from any single site. This is the same
mechanism as the vocabulary cluster that was closed one file early, seen before
the fact rather than after, and it is why conversion scope should be defined by
the KEYED SET a lookup uses, not by the sites a task listed.

Also recorded from the same commit: the retired post-dispatch mark was deleted
outright rather than kept as a pass-through, because **its name asserted a state
it did not establish** - it recorded contact, while connectedness is derived. It
was also the site whose docstring had already drifted. A name that overclaims is
not worth preserving for the convenience of its callers.


### strenum-keyed-lookups-resolve-in-both-directions | medium | reference, settles a recurring doubt

Recorded so no future lane re-derives it or hesitates over it, because it gates
every conversion of a literal-keyed catalog to a shared vocabulary.

A lane converting a keyed catalog raised the right doubt: `Enum.__hash__` hashes
the member NAME, so a dict keyed by members and looked up by a raw string could
miss - and miss SILENTLY, degrading every frame to its identity keys with every
check green. Measured on this platform against the real enum rather than reasoned
from the class hierarchy:

    MRO: ServerEventType, StrEnum, str, ReprEnum, Enum, object
    hash(member) == hash(str): True      member == str: True
    dict keyed by member, looked up by raw string: RESOLVES
    dict keyed by string, looked up by member:     RESOLVES
    __hash__ owner: str.__hash__

`str` precedes `Enum` in the method-resolution order, so the string hash wins and
both lookup directions resolve. Converting a literal-keyed catalog to members is
therefore safe, and a mixed catalog - some keys converted, some not - still
resolves, which is precisely why the partial-conversion disease recorded above is
INVISIBLE at runtime rather than merely untidy.

The doubt deserved its answer even though the answer was benign. The failure it
described is real and was avoided by an ordering nobody chose deliberately; had
those two bases been ordered the other way, the conversion would have broken every
frame silently. Verifying rather than reasoning is what separates being right for a
confirmed reason from being right by luck, and this campaign has already recorded
one case where reasoning about a platform detail was wrong in the same file - the
canonical writer's permission path was translating line endings while its docstring
claimed it wrote bytes directly.

### run-identity-validated-on-input-and-forgotten-on-output | high | The path-safe identity types are consumed at 6 of 23 declarations, and two adjacent lines of one response model get opposite treatment

`api/schemas/gateway.py` declares `PathSafeRunId`, `ReservationId`, and `LeaseId`
- annotated types pinning a bounded, path-safe identity shape - and exports
them. An AST enumeration of every `run_id` / `reservation_id` / `lease_id`
annotation in that module finds 23 declarations. Six use the canonical types.
Seventeen do not: fourteen are bare `str`, three carry length bounds but no
pattern, so they still admit `/`, `..`, and control characters.

The INPUT side is safe and that is what makes this a real finding rather than a
theoretical one. `RunStartRequest` uses the validated types, and every REST
route handler types its path parameter as `PathSafeRunId`. The gap is entirely
on the RESPONSE side, where the same identity is redeclared per model.

The decisive evidence that this is oversight rather than policy is two ADJACENT
lines in one class: `RunPrepareResponse.reservation_id: str` at 389 and
`RunPrepareResponse.lease_id: LeaseId` at 390. The same admission flow then
inverts the asymmetry - `reservation_id` is validated on release OUTPUT but bare
on prepare output, `lease_id` is validated on prepare output but bare on commit
output. No docstring in the module mentions an intentional exemption.

Consequence is disclosure integrity, not an injection path. FastAPI validates a
response body against its `response_model` before serializing, so a validated
declaration fails LOUD when a builder produces a malformed identity - a stray
concatenation, a durable row predating an identity-format change, an upstream
join bug - while a bare one ships it silently to the client.
`RunStatusResponse.run_id` is the worst of them: that model is the authoritative
recovery snapshot callers reconcile all state from, and it is bare.

This is the same shape as the object-narrower finding already closed here - a
canonical answer exists, is exported, and most consumers never adopted it - but
found by a different method. No structural scan could have seen it: these are
FIELD DECLARATIONS, not function bodies, so there is no body to hash. It took
reading a module for a concept and noticing which sites answered it.

### the-allowlist-hazard-measured-not-argued | critical | upgrades an abstract warning to a demonstration

The registration-list hazard recorded above was reasoned, not shown. A lane has
now MEASURED it, by stranding a catalog entry - present, but keyed so the lookup
misses - and re-running the real encoder:

    stranded-key projection : {'type': 'heartbeat'}
    stranded-key frame      : event: heartbeat | data: {"api_version":"v1","type":"heartbeat"}
    frame still emitted, type still correct : True
    payload field SILENTLY dropped          : True

Every abstract claim in the earlier entry holds literally. The frame is emitted.
Its type is correct. Its payload is gone. Nothing raises, and no type check can
see it.

**The decisive part is the sensitivity result: the PREVIOUS assertion passes
against that broken case, and the replacement fails.** That is the difference
between a test that proves a refactor happened and one that proves it works, shown
rather than asserted - and it means the committed test would have certified a
silently-empty wire indefinitely.

The negative control was also ordered correctly: an uncatalogued kind must lose
its field, and that check runs FIRST, so the allowlist is proven live before the
positive case leans on it. Same discipline as asserting a trap is live before
exercising it.

One detail worth keeping: the real heartbeat's `metadata` field is dropped too, by
omission, as designed. So the projection is lossy on the correct path as well -
which is why "the frame arrived and looked plausible" was never evidence of
anything.

Recorded at critical because it converts the campaign's most dangerous class from
a caution into a demonstrated failure mode with reproducible output, and because
it was found by a lane auditing its OWN committed proof after the gap was pointed
out, rather than defending it.

**Independent confirmation of the platform fact.** The same lane measured the
StrEnum hash behaviour separately from the measurement recorded above, on the same
box, and reached the identical result - including the sharper form
`hash(MEMBER) != hash("MEMBER_NAME")`, which shows exactly which inherited
behaviour the catalog depends on and does not control. Two independent
measurements, one conclusion; it is now asserted in the test rather than assumed.

### multiplexed-session-convergence-refused-on-evidence | high | The two long-lived JSON-RPC sessions differ in message-class count, completion channel, and id contract - a shared primitive would have to be configured into being either one of them

The largest remaining fragmentation this campaign identified was the long-lived
multiplexed JSON-RPC session, implemented once in `codex_chat_model.py` as a
real client class and once across four ACP modules around a bare
`dict[int, Future]` type alias. `_stdio_rpc.py`'s docstring names it as where
that consolidation would land. It is REFUSED, and the evidence is specific
enough that it should not be re-attempted without new information.

**The id contract differs in kind, not dialect.** Codex allocates a monotonic
`_next_id` per call, so many requests of the same method may be in flight at
once. ACP uses RESERVED FIXED identifiers per RPC KIND - `AcpRequestId` is an
`IntEnum` numbering 1000-1009, one constant per operation - which is only sound
because every call site awaits its own response before reissuing that id. A
shared pending map cannot hold both: under Codex's contract ACP would gain
concurrency it never designed for, and under ACP's contract a second concurrent
Codex request of one method would silently overwrite a still-pending future.

**The completion channel differs.** Codex signals turn completion as a
NOTIFICATION on the same FIFO queue that carries content deltas, so ordering is
correct by construction. ACP signals it by RESOLVING the original
`session/prompt` REQUEST future - inspecting `stopReason` to flip a side-channel
flag - while content deltas arrive as notifications on a SEPARATE chunk queue. A
reader with one pending map and one notification queue has no honest home for
ACP's third channel, nor for "inspect a response body to set a completion flag",
a concept Codex does not have.

**ACP carries a message class Codex refuses outright.** Server-initiated
requests - permission prompts, filesystem and terminal operations - are real
bidirectional RPCs dispatched as background tasks that write their own replies
under a stdin lock. Codex answers any inbound request with `-32601` inline.

**And the ACP side has no API to converge onto.** Its futures dict is reached
into directly from four modules, each doing its own create-future and
wait-for. Consolidating would mean rewriting ACP's session setup, auth, and
model call sites first - authoring a shared abstraction, not extracting a
common one. That is the distinction between this and the one-shot reader that
consolidated cleanly earlier: that one was already the same mechanism written
twice.

A shared session object reconciling these would need flags selecting which
lane's id contract, completion channel, and inbound-request policy applied. That
is worse than two implementations, because it would look shared while behaving
as neither.

Also ruled out as an adjacent win: the two stderr drains differ substantively -
ACP's captures interactive auth URLs and resets the turn-deadline liveness clock
per line, Codex's only redacts into a bounded tail.

### acp-fixed-id-rpc-ceremony-repeats-nine-times | medium | The refused cross-lane convergence surfaced a real intra-lane one: nine ACP call sites each hand-roll allocate-future, write-under-lock, await-with-timeout

Found while establishing the refusal above, and it is the better-scoped work.
Within the ACP lane alone, the ceremony "allocate a future under this
operation's fixed id, write the frame under the stdin lock, await it with a
timeout, raise on expiry" repeats near-verbatim across `initialize_session`,
`setup_session`'s retry loop, `_select_config_option`, `setup_prompt`,
`_cancel_session`, `fork_session`, `list_sessions`, `set_mode`, and
`authenticate_rpc`.

No cross-lane reconciliation is involved, so none of the objections above apply:
one lane, one id contract, one completion model. This is what the ACP side lacks
and what its absence forced - the missing register/resolve/await API that made
the cross-lane consolidation impossible to attempt cleanly in the first place.

### attribution-the-warning-and-the-audit-were-different-acts | low | keeps the method record honest

A lane declined credit this audit had given it, stating that the weak test was
caught by the orchestrator's allowlist warning rather than by its own report. The
correction is accepted, and the accurate split is recorded because this campaign's
method record depends on knowing which kind of check found what.

The GENERAL warning was the orchestrator's: registration lists are invisible to
type checking, so a passing test may prove only that a refactor happened. It named
a class, not an instance, and it was issued to three lanes at once without knowing
whether any of them had the defect.

The SPECIFIC finding was the lane's: it went back to its own landed test, found
that it asserted the key rather than the content, and then MEASURED the failure by
stranding the entry and showing the old assertion passes where the new one fails.
Nothing in the warning identified that test or predicted that result.

Both matter and they are different acts. A warning that names a class is worthless
without someone willing to re-audit their own shipped work against it, and a
re-audit is unlikely to start without the class being named. Recording only one
side would teach the wrong lesson - either that broadcast cautions find defects, or
that lanes find them unprompted.

Worth noting the direction of the correction: the lane gave credit AWAY. Every
other attribution dispute in this campaign has run the same direction, which is a
reason to trust the record rather than to police it.

### a-negative-control-must-fail-by-a-different-mechanism | high | corrects the rule recorded above

The allowlist entry records "run the negative control FIRST" as discipline. The
lane that wrote that test has identified what actually makes it work, and the
ordering turns out to be downstream of the real rule:

> The control only works because it asserts a DIFFERENT frame kind. A negative
> control on the same kind would have been satisfied by the same broken lookup it
> was meant to detect.

**A negative control has to fail through a different mechanism than the one under
test, or the defect satisfies both.** A same-kind control would have passed under
exactly the stranded-key state it existed to catch: the lookup misses, the field
is dropped, and "the field was dropped" is what the control asserts. It would have
gone green for the wrong reason, at the moment it was most needed.

That makes a compromised control WORSE than no control, because it manufactures
confidence rather than merely failing to provide it. An absent check is visibly
absent; a check that is a hostage to the bug it guards reads as coverage.

The general form, since it reaches past allowlists: any "prove the guard is live"
step that exercises the SAME lookup, the SAME branch, or the SAME key as the
assertion it guards is testing that the machinery is CONSISTENT, not that it
WORKS. Consistency is exactly what a single shared defect preserves.

This applies to every non-vacuity proof this campaign has demanded, including
those already accepted. They are not re-opened here - most ran the deleted body
against the new case, which is a genuinely independent mechanism - but the
criterion is now explicit rather than incidental, and the ordering rule recorded
earlier should be read as a consequence of it rather than as the rule itself.

Recorded high because it revises a method claim this audit had already stated as
settled, and because the failure it describes is invisible: a compromised control
produces a green suite and a satisfied reviewer.

### the-sensitivity-probe-preserved-with-its-caveats | critical | reproduction for the allowlist finding

The allowlist finding was recorded on the strength of its output, and its
reproduction lived in a session scratchpad that would not survive. Preserved here
verbatim, with the author's own caveats, because a result nobody can re-run is the
same "proof nobody executed" problem this audit recorded when a closure grep
turned out not to reproduce.

```python
"""Sensitivity: does the committed content test FAIL when the catalog key strands?"""

from vaultspec_a2a.graph.enums import ServerEventType
from vaultspec_a2a.streaming import sse_frames

CATALOG = sse_frames._PROGRESS_CATALOG
entry = CATALOG.pop(ServerEventType.HEARTBEAT)

# The stranding: entry still present, keyed by the member NAME rather than its
# value -- what inheriting Enum.__hash__ (or a hand-typo) would produce.
CATALOG["HEARTBEAT"] = entry

projected = sse_frames.enforce_progress_allowlist(
    {"type": ServerEventType.HEARTBEAT.value, "server_uptime_seconds": 99.5}
)
print("stranded-key projection :", dict(projected))

raw = sse_frames.encode_sse_frame(
    {"type": ServerEventType.HEARTBEAT.value, "server_uptime_seconds": 42.5},
    event=ServerEventType.HEARTBEAT,
    thread_id="t-probe",
)
print("stranded-key frame      :", raw.decode().strip().replace("\n", " | "))

type_still_right = b'"type":"heartbeat"' in raw
content_lost = "server_uptime_seconds" not in projected
print(f"frame still emitted, type still correct : {type_still_right}")
print(f"payload field SILENTLY dropped          : {content_lost}")
```

Run from the repository root with the project environment active. It imports the
package and nothing else - no fixture, no conftest, no path dependency.

**Author's caveats, none edited out:**

1. It mutates module global state and never restores it, so it would corrupt every
   subsequent test in a shared session. That is why it is a probe and not a test.
2. It reaches into a private catalog name deliberately - the point is to break the
   lookup from the inside - and will break if that module is refactored.
3. The two printed measurements read DIFFERENT objects: the type check reads the
   encoded frame, the content check reads the direct projection. They agree here,
   but the pairing is loose; the honest reading is that the encoded frame
   independently shows the same loss in its own output line.

### correction-the-sensitivity-result-is-an-inference | high | downgrades a claim recorded above

The allowlist entry states that "the PREVIOUS assertion passes against that broken
case, and the replacement fails". The probe's author flags that this is an
INFERENCE, not a direct observation, and the correction is accepted.

What the probe demonstrates is the MECHANISM: with the key stranded, the frame is
emitted, its type is correct, and the payload field is silently dropped. It does
not itself execute the committed test under that state.

The inference is sound - the committed test asserts the uptime value on the
decoded frame, which is exactly what vanishes - but sound inference and direct
observation are different evidentiary grades, and this audit has spent the session
insisting on that distinction from other people's work. The finding stands at
critical on the mechanism, which IS directly observed. The claim about the two
assertions' relative sensitivity is downgraded to a reasoned consequence.

Recorded because the author volunteered a weakening of their own result that
nobody had asked for and nobody would have detected - the same direction every
correction in this campaign has run.

### a-guard-that-pinned-a-literal-in-place | medium | guard rejected for the right reason

The permission-cap cluster carried a guard that asserted the literal `[:4096]`
appeared in the durable writer's SOURCE TEXT. It was replaced rather than
retargeted.

It could only observe SPELLING, never behaviour: it passed for a writer that
truncated at the right width by coincidence and for one that truncated correctly
while spelling it differently, and it actively OBSTRUCTED the fix - the guard's
own success condition was the literal whose removal was the entire point.

This is the third guard this campaign has examined and the third to fail the same
test: a row pinned to a helper's NAME that a rename defeats, a row pinned to a
SHAPE occurring at five legitimately-distinct sites, and now a row pinned to a
literal's TEXT. Guards that assert an invariant are the campaign's best evidence;
guards that assert a spelling are debt wearing a guard's clothes, and this one had
become an obstacle to its own subject.

### idempotency-default-was-three-sites-not-four | high | Reported as one concept answered four ways; the fourth is a different concept, and converging it would have silently disabled restart recovery

A sweep reported that the default idempotency key for a run control action is
derived four times - twice through `thread/idempotency.py`, whose docstring
states it exists to stop exactly this, and twice inlined - and noted that one
inline copy is not even hashed, asking whether that was deliberate. The question
was the right one and the answer inverts half the finding.

`control/permission_service.py` inlining its own `sha256` was genuine drift and
is now consumed from the home as `default_permission_response_key`, keyed on
request AND option so a repeated identical answer deduplicates while a changed
answer does not collide with the first.

`control/clarification_service.py` must NOT converge. Its key is a readable
prefix rather than a digest because the restart-recovery sweep in that same
module selects unapplied actions with
`idempotency_key.like(f"{_IDEMPOTENCY_PREFIX}%")`. A digest has no queryable
prefix, so hashing the key would make that query match NOTHING: clarification
actions parked across a restart would never be redriven, and nothing would
raise. The difference is a requirement of the query, not drift from its
siblings.

What made it look like drift is that no comment said otherwise. A reader
comparing four key-derivations sees three digests and one concatenation, and the
only available inference is oversight. The correction is therefore not "leave it
alone" - it is to write the constraint down at both ends: the home now names the
exception, and the function states why it cannot move. An invisible constraint
is indistinguishable from a defect, and this campaign has now nearly removed one
twice.

Notable that this sits directly beside the already-recorded
`idempotent-permission-response-accepts-a-replay` defect. Idempotency in this
neighbourhood has cost the project once already, which is the argument for
stating the rules rather than leaving them inferable.

### role-count-bound-restated-as-a-bare-number-in-the-schemas | medium | The canonical bound is imported and cross-repo tested in one consumer and hardcoded in another, where nothing would move it

`thread/actor_tokens.py` declares and exports `MAX_ROLES_PER_RUN = 64`.
`control/admission.py` imports it, and a dedicated agreement test checks it
against the engine's own copy across repositories. `api/schemas/gateway.py`
hardcodes the same quantity twice instead:
`RunPrepareResponse.required_roles` and
`FrozenTeamAssignmentSummary.assignments`, both `Field(max_length=64)`.

`actor_tokens.py`'s docstring already anticipates this failure by name - it
warns that the prepare stage's role-list bound and the admission bound describe
ONE quantity, and that a run clearing one but not another is refused at whichever
boundary disagrees, after the caller was told its request was fine. The docstring
was written knowing about the admission and engine copies. It does not know a
third bare copy exists in the response schema.

Care is required in the fix and is the reason it is recorded rather than done:
`max_length=64` appears at nine sites in that module and seven are unrelated
STRING length bounds - `team_preset`, `option_id`, `repair_status`. Only the two
LIST bounds are the role count. A mechanical replace-all would silently retype
seven unrelated fields to a role limit.

Held rather than dispatched: another lane currently owns that file for the
identity-validation fix, and two writers in one schema module is the shape of an
earlier incident in this project.
