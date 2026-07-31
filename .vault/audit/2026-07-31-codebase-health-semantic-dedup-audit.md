---
tags:
  - '#audit'
  - '#codebase-health'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
body_hash: 'sha256:70ac29f30c2f88863cad570d5740de955247facd7df17265b0871c06e15f2c35'
related:
  - "[[2026-07-19-codebase-health-audit]]"
  - "[[2026-07-19-codebase-health-plan]]"
---
# `codebase-health` audit: `semantic deduplication sweep`

## Scope

A semantic deduplication sweep of the production tree, driven by `vaultspec-rag`
semantic code search rather than by symbol or keyword matching. The target class
is the non-canonical redeclaration: one concept implemented more than once,
under different symbol names, where at least one copy is not the audited or
documented home for that concept.

This pass exists to close a blind spot the 2026-07-25 consolidation sweep
recorded against itself. That sweep found duplicated symbols and divergent
mandates, and noted that duplicated multi-step protocols are invisible to an
axis that looks only for duplicated symbols. Semantic search is the instrument
that sees them, because it matches on described behaviour rather than on shared
identifiers.

Five investigators swept in parallel, one per axis: duplicated multi-step
protocols; redeclared rules, policies, and constants; duplicated resolution and
derivation logic; duplicated mapping, serialization, and schema translation; and
duplicated lifecycle, cleanup, and resource reclamation. Each was required to
lead discovery with semantic search, read both sides of a suspected pair in full
before asserting anything, and confirm locators with a targeted grep. Every
finding below was independently re-verified against source by the coordinator
before being recorded; nothing rests on an investigator's report alone.

The exclusion list carried by every investigator was the thirteen findings and
six adjudicated non-findings already recorded by the 2026-07-25 sweep, so
nothing here re-litigates settled ground. One entry deliberately extends an
existing open finding rather than raising a new one, and is labelled as such.

Two results deserve note before the findings. First, two investigators working
independent axes - the redeclared-rules axis and the mapping axis - converged on
the same live defect from different directions, each reaching it through its own
search path. That convergence is the strongest evidence this pass produced.
Second, the highest-value findings are not merely duplicated code. They are
cases where one copy is explicitly declared canonical, in a module docstring or
in a comment naming the hazard, while siblings implementing the same concept
were never brought in. A consolidation recorded as complete is precisely where
nobody thinks to look again, and three separate findings below have that shape.

## Findings

### plan-approval-rejection-predicate-diverges-from-vocabulary | high | A rejected plan is durably recorded as approved because three predicates use three different rejection vocabularies

Found independently by two investigators on separate axes; verified against
source.

Two vocabularies exist for a permission response. An ordinary tool-call
permission answers with an ACP option kind, and the canonical
`REJECT_OPTION_IDS` in `graph/enums.py` is derived from the members of
`PermissionOptionKind` whose value begins with `reject`. That enum holds only
`allow_once`, `allow_always`, `reject_once`, and `reject_always`, so the frozen
set provably contains exactly `reject_once` and `reject_always`. A plan or
document approval answers with a different vocabulary entirely: the literal
strings `approve` and `reject`, built as options in `control/projection.py`,
persisted verbatim as the response option, and confirmed at submission time in
`control/permission_service.py`, which derives its resume value from an equality
test against `approve`.

Three sites in the same rule family compute "was this a rejection", and each
answers differently. `control/permission_service.py` tests membership in
`REJECT_OPTION_IDS` or equality with the literal `reject`, covering both
vocabularies, and is correct. In `thread/permission_fsm.py`,
`compute_permission_resolution_effects` tests membership in `REJECT_OPTION_IDS`
alone. Its sibling `compute_progress_applied_effects` tests equality with the
literal `reject` alone. Each of the latter two implements one half of the rule.

The live consequence follows the primary path. A user rejects a plan, and
submission correctly records the thread approval state as rejected. The
confirming `permission_resolved` event - the standard settlement event for this
request class, not a rare fallback - then reaches
`compute_permission_resolution_effects`, where the literal `reject` is not a
member of `REJECT_OPTION_IDS`, so the rejection flag computes false. Because the
pause cause does correctly identify this as a plan approval, the effects
descriptor carries an approved status, and `control/event_handlers.py` writes it
through `set_thread_approval_state`, overwriting the correct rejected value. The
worker node gates its "plan rejected by user, revise the implementation plan"
system message on the approval status reading rejected, so that message never
fires and the rejected plan proceeds to execution.

Two aggravating facts. Severity is raised by a recent change rather than lowered
by it: the refactor that made execution approval read from the approval status
field alone removed the corroborating signal that might otherwise have masked
this, so the overwritten field now solely determines whether a rejected plan
executes. And the module is untested - `thread/permission_fsm.py` has no test
file anywhere in the tree, and the event-handler tests exercise only the replay
guard and the unknown-request-id path, never a rejection payload. The defect
survived because nothing ever asserted the behaviour.

### atomic-write-protocol-still-triplicated | high | The declared single home for atomic file writes has three unconverted siblings

`lifecycle/atomic_write.py` declares itself, in its own module docstring, the
resolution of an earlier duplication: three separate implementations of the
write-temp-then-fsync-then-rename pattern existed, none of which removed its
temporary file on failure, and only one of which rode out the transient Windows
sharing violation. That module states it is the single audited version, and its
hardening is real - it fsyncs before the rename, retries a permission error on
the replace for a bounded window, and unlinks the temporary file on any
exception before re-raising.

Only two call sites consume it, both in the same package. Three further sites
implement the same sequence from scratch, each missing part of the hardening the
canonical module exists to provide. `lifecycle/singleton.py` writes the owner
record with a raw descriptor, fsyncs, and calls a single-shot replace with no
cleanup on any failure path and no retry window; it sits in the same package as
the canonical module, does not import it, and its own docstring nonetheless
claims the atomicity guarantee it only partly implements. `providers/gemini_auth.py`
writes the OAuth credential file through the same unprotected shape.
`desktop/credentials.py` comes closest, unlinking the temporary on an error
around the hardening and replace step, but leaves the preceding write and fsync
without failure cleanup and its replace is likewise single-shot.

The consequence is a latent trap rather than a present outage. A future fix to
the canonical writer - widening the retry window, or correcting a Windows
sharing-violation edge case, which is exactly the class of fix that module was
created to hold - silently does not reach the singleton lock record, the Gemini
OAuth credential, or the worker IPC secret. All three are liveness- or
security-relevant files. The trap is baited by the docstring: the consolidation
reads as finished, so the next engineer has no reason to search for siblings.

### windows-tree-kill-taskkill-has-no-timeout-in-sync-lifecycle-path | high | The synchronous kill path can block forever on a wedged taskkill that its async twin explicitly bounds

The Windows and POSIX process-tree kill escalation is implemented twice.
`utils/process.py` states in its module docstring that it exists to be the
single async escalation shared by the worker-management shutdown and the ACP
subprocess reaper, and it holds that contract for those two callers. The
synchronous twin, `tree_kill` in `lifecycle/manager.py`, reimplements the same
algorithm by hand for every CLI- and registry-driven teardown.

They diverge on the error path that matters. The async implementation launches
`taskkill` and bounds the wait explicitly, force-killing the `taskkill` process
itself and returning failure if it hangs; a comment names the hazard directly,
stating that the wait is bounded so a wedged `taskkill` cannot hang the caller.
The synchronous implementation invokes the same command through a blocking
subprocess call with no timeout argument at all. The timeout parameter that
function accepts is applied only to the post-kill liveness poll, never to the
call that can block - so the function takes a timeout and does not bound the one
step that needs it. A `taskkill` wedged by antivirus interception, by a target
stuck in an uninterruptible kernel wait, or by a jammed service-control
subsystem blocks the calling thread indefinitely.

The blast radius makes this high rather than moderate. Every synchronous
teardown verb in the process registry routes through it. The port-band retry
loop in the serve path relies on it to fell a child that failed to bind, and
while it hangs the loop cannot reach the block that releases held reservations,
so those stay claimed. Most seriously, `cli/service.py` falls through to this
call as the last-resort stop path when the authenticated shutdown route is
unavailable - and that function's own docstring records that a stop verb which
can hang or silently fail would break the dashboard's restart contract. The one
path designed as the guaranteed recovery from a hang can itself hang, with
nothing bounding it. POSIX is not exposed: both implementations bound every wait
on that branch and escalate correctly.

The restart verb inherits it too, since it composes stop and start and the stop
half falls through to the same unbounded call. Worth contrasting with a
neighbour that gets this right: the ACP terminal handlers, which sit in the same
code region, reap exclusively through the shared bounded async escalation and
carry no hand-written kill path of their own. The correct pattern is already
present in the tree; the synchronous path simply never adopted it.

### provider-eligibility-admission-gate-ignores-credentials | high | The execution-ready fact is computed from command resolution alone while a credential-aware resolver exists beside it

"Is a provider available to run a request right now" is answered by two
structurally different resolvers feeding two different gates in the same request
path. `_eligible_provider_names` in `control/health.py` iterates a hardcoded
candidate tuple and calls only the command-classification seam, which its own
docstring describes as resolving a provider's command purely from filesystem and
configuration. It never reads the Claude OAuth token, the Gemini or Google API
key, or the Kimi API key. The credential-aware resolver,
`probe_provider_readiness` in `providers/model_profiles.py`, checks the
credential first for Claude, Gemini, and Kimi and only then falls through to the
identical command classification. The two agree on Codex alone, because Codex is
the one provider that skips the credential check in both.

The divergent input is ordinary rather than exotic: a host where the provider
CLI binary is on PATH but the corresponding token or key is unset - a normal
transient state during setup. The weak resolver reports the provider eligible;
the credential-aware one reports it not ready with an explicit no-token reason.
The inverse also holds for providers the weak resolver never examines at all.

Both consumers of the weak signal are load-bearing. It feeds the desktop
readiness assembly and therefore the admission value whose enum docstring
describes it as the execution-ready fact, meaning a reachable worker and an
eligible provider, surfaced directly to the dashboard operator. The same signal
is the fail-closed staged admission gate, consulted both to grant a reservation
and again at commit, consuming one of a small bounded pool of slots. The
credential-aware resolver runs only later, inside the shared run-creation core,
which does refuse the run - so nothing executes uncredentialed. But a bounded
admission reservation has already been granted and burned against a promise of
execution-readiness, and the operator-facing readiness surface has already
reported a fact that is wrong.

### progress-fallback-loses-tool-permission-rejection | medium | The lost-event backstop records every settled permission as applied, including denials

The durable status of a permission request must become rejected, not applied,
when a tool call was denied. The primary settlement path honours this:
`compute_permission_resolution_effects` selects the target status from the
rejection flag, and `control/event_handlers.py` passes that status explicitly to
the repository.

The progress-inference backstop, used when the confirming `permission_resolved`
event is lost, does not. `compute_progress_applied_effects` hardcodes the
applied status unconditionally and never selects rejected regardless of the
response option it is given. The write site confirms the behaviour reaches the
database: the progress path calls the repository's mark-applied function with no
status argument, so the repository default of applied is stored, in contrast to
the primary path which passes the computed status explicitly.

The consequence is a durable audit falsehood on a path that exists precisely for
degraded conditions. The status field is exposed through the REST schema and the
gateway and teams routes, so whenever the backstop is the settling path, a
denied tool call is reported to a dashboard reader as applied. This finding and
the plan-approval finding above share one root: the rejection semantics of a
permission response are recomputed independently at each settlement site rather
than derived once.

The scope is wider than the backstop, and the evidence for that is in the
repository's own fixtures. The canonical set is matched against the response
option identifier, not against the option kind, and those are different fields
carrying different vocabularies. The Kimi permission fixture - written for that
provider's real enforcement path - pins an option whose identifier is the bare
literal `reject` while only its kind is `reject_once`. A second fixture
exercises a `deny_once` identifier. Provider option identifiers are therefore
free-form strings independent of `PermissionOptionKind`, confirmed in-repo
rather than assumed.

It follows that the primary settlement path, not merely the backstop, fails to
recognise a genuine rejection for at least one shipped provider. A human denying
a Kimi tool prompt submits the raw identifier, which is validated against the
offered list and accepted, persisted verbatim, and then tested for membership in
a set that cannot contain it. The durable status records applied for a call the
user denied.

The precise blast radius is worth stating, because it differs from the plan
case. The tool itself is still correctly denied: the ACP handler enforces the
denial at the wire level using its own permissive substring predicate, which -
architecturally inconsistent though it is - happens to be more correct for the
identifiers it actually receives than the canonical set would be. So for tool
permissions this is a durable reporting and audit defect rather than an
execution defect. For plan approvals, as recorded above, it is an execution
defect. One incomplete vocabulary produces both.

### authoring-bearer-fallback-documented-but-never-implemented | medium | A docstring promises a discovery-file fallback that no code performs, while the fallback value sits unused in scope

"Which engine bearer authenticates a run's authoring-bridge traffic when the
run-start payload carried none" is answered two ways: one documented, one coded,
and they disagree.

The documented answer is explicit. The engine-bearer field on the actor-token
bundle in `thread/actor_tokens.py` is typed optional, and its docstring states
that when the bearer is absent the worker resolves it from the engine discovery
file instead. The gateway forwards the bundle through with no backfill, so the
absent-bearer shape reaches the worker exactly as sent, and the type system
permits it.

No code performs that fallback. The token store returns the bundle's bearer as a
bare pass-through with no resolution logic. Both production consumers treat
absence as give-up rather than fall-back. The authoring binding provider - whose
own docstring calls it the production construction site, so no other home for
the fallback exists - returns nothing when the bearer is missing, leaving the
bridge unarmed. The run-end session close is the sharper case: it calls the
engine resolver on one line, obtaining an endpoint whose bearer field is
non-optional and therefore always populated, and on the very next line gates on
the token-store bearer and returns. The documented fallback source is not merely
available; it has already been resolved and is sitting in scope, unused, at
exactly the point the docstring says to consult it.

The consequence for a run whose bundle carries per-role actor tokens but no
engine bearer is silent and total: the authoring bridge never arms for any
worker, because a null binding is treated as leave-the-surface-unchanged rather
than as an error, so the coding agent simply never receives the propose and read
tools. The run-end session close then no-ops instead of using the bearer it
fetched moments earlier. No test covers it - the binding tests exercise only the
no-bundle-at-all case, never a registered bundle with a null bearer.

Rated medium rather than high because reachability is established per contract
rather than observed: the type, the docstring, and the unconstrained forwarding
path all permit the shape, but whether current engine traffic ever sends it was
not confirmed. Confirming that it does would make this high. The code and its own
documentation disagree regardless of how often the input occurs.

### ws-heartbeat-interval-scoped-to-websocket-also-drives-sse | low | A knob documented under the WebSocket section also retunes the SSE stream heartbeat

The heartbeat-interval setting is documented in the environment example beneath
a WebSocket section header, flanked by two genuinely WebSocket-only knobs, which
presents it as governing that transport alone. It is declared once and consumed
twice: by the WebSocket keep-alive cadence, which is the documented use, and by
the heartbeat cadence of the Server-Sent Events thread and run stream endpoints,
which is a different transport entirely.

There is no value disagreement - both consumers read the one setting, so nothing
diverges numerically. The defect is the documented scope, and it is the same
shape as the already-recorded finding in which an MCP-scoped variable is aliased
onto the global gateway URL. An operator who reads the WebSocket section and
changes this value to tune keep-alive cadence silently retunes the SSE progress
stream too, which has its own independent interaction with reverse-proxy idle
timeouts. The two neighbouring WebSocket knobs were traced and are clean,
single-consumer, and correctly scoped, which is what makes this one an outlier
rather than a section-wide labelling issue.

### process-containment-handle-leaks-when-the-spawn-call-itself-raises | medium | Three spawn sites release the OS containment on every failure except the spawn call raising

Three sites hand-implement the same protocol - create an operating-system
containment, then spawn a process into it - and all three release the
containment correctly when the spawned process dies or never becomes ready. None
releases it when the underlying spawn call itself throws.

On Windows the containment eagerly opens a job-object kernel handle at creation;
on POSIX it allocates nothing until assignment, which never runs on this path,
so the defect is Windows-only by construction. In `providers/_subprocess.py` the
spawn is wrapped in a handler that logs and re-raises without closing the
containment, whose handle then goes out of scope with no remaining reference and
no finalizer. In `control/worker_management.py` the containment is created by
the caller before the spawn, and every other failure mode is handled correctly -
the exited-early path closes it explicitly, the never-ready path terminates
through it - but the raw process construction is wrapped in no handler at all,
so a bad command path or a resource-exhaustion error propagates out with the
reference neither closed nor cleared. The caller's own comment asserts that a
failed spawn has already released its containment, which is true for both
return paths and false for a raised one. In `providers/_acp_rpc_handlers.py` the
terminal-create handler has an outer handler that converts the exception into a
well-formed RPC error, but never touches the containment on the way out.

Each occurrence leaks one job-object handle, reclaimed only when the owning
gateway or worker process exits - not per request, run, or retry. The worker
path sits behind automatic respawn, so a persistent misconfiguration or a
resource-exhaustion condition that makes the spawn call fail leaks one more
handle per retry in a long-lived process, compounding the exhaustion that
triggered it. Rated medium rather than high because the trigger is narrower than
the crash and timeout paths, which are all handled correctly; the accumulation
claim under retry is inferred from the surrounding backoff structure rather than
from reading the watchdog loop line by line.

### queue-tool-permission-kinship-overstated | medium | A docstring claims a dispatch equivalence that does not hold, and a co-occurring tool call is dropped

The queue-tool dispatcher in `graph/nodes/worker.py` states in its own docstring
that it dispatches the queue tool the same way the permission gate handles the
ACP permission request. Checked against the gate it names, the claim fails in
three provable ways. The dispatcher invokes a real bound tool and requires a
routing command result, raising otherwise; the gate invokes no tool object at
all, calling a plain async function that raises the interrupt and then
hand-builds a single tool message, with no routing command anywhere on its path.
The dispatcher collects every matching call and merges all their state patches
before one follow-up turn; the gate processes the first matching call and
immediately returns a fresh model response. And the two return different shapes,
one carrying a state patch and one not.

The consequence follows from the second divergence and the order of execution:
the gate runs first, and its return value is what the dispatcher subsequently
inspects. If a single model turn emits both a permission request and a
queue-tool call, the gate answers the permission, abandons the sibling call
without ever answering it with a tool message, and returns a brand-new response
that replaces the original - so the queue-tool call is never dispatched, never
durably marked complete, and its identifier is discarded. This is plausible
precisely on the deterministic mock provider the gate exists to serve.

Reachability was investigated specifically and settled at reachable in
principle, not proven reachable. No shipped test constructs the mixed turn: the
two call types are exercised in entirely separate test classes, and the two
other suites referencing the queue tool invoke it directly without passing
through the dispatcher or the gate at all. The canned responses that would
decide the question are not in this repository - the mock chat model is a thin
proxy to an external tape server, and no per-agent tape lives in the tree - so
the fixture side is genuinely out of reach rather than merely unchecked.

The response path, however, has no structural barrier. The tool-call extractor
returns an unfiltered list, and the stream builder iterates every entry,
appending each to one chunk with no cap and no filtering on tool name, then
yields them together in a single message chunk that standard accumulation merges
into one response. A tape emitting both names in one array would therefore
produce exactly the message this finding's drop scenario requires, and nothing
in the parsing path would object.

The finding stays at medium on that basis, and the actionable gap is a missing
test rather than a latent bug: nothing asserts what the gate and dispatcher do
when a single turn carries both names, and nothing constrains the tape layer
from ever constructing one. Two fix shapes are available - correct the docstring
to state the real and much narrower relationship, or merge the two into one
dispatch loop that collects every recognised call before building a single
follow-up turn. The second makes the multi-call case safe by construction rather
than by the continued absence of a triggering tape, which is the difference
between a fix and a reprieve.

Recorded in this audit because it is the same family as the rejection findings -
code asserting a shared convention with a sibling it does not actually implement
equivalently - and because it was found by checking a docstring's claim rather
than trusting it, which is the method this whole pass argues for.

### approval-interrupt-gate-protocol-duplicated | medium | Two live human-approval gate factories share a declared lineage and no conventions

Two factories implement one protocol - park the graph on an interrupt for a
human decision, parse the resume payload, then route to an approved-path node or
to a rejected-path node carrying a revise signal - and both are wired into the
compiled graph today, so neither is dead code.

The plan-approval node in `graph/nodes/supervisor.py` is a single node that
parses its resume as an approved boolean or the literal approve string and
returns a plain dictionary state patch, carrying the revise prose in a
routing-error string. The phase gate in `graph/nodes/phase_gate.py` is
deliberately split into two nodes so the correlation identifier commits to the
checkpoint before parking - its docstring explains that a single-node gate would
write the identifiers only in its post-resume return, leaving nothing to
correlate while parked - and it parses an enum-shaped verdict with notes,
returning a routing command object and carrying the revise prose in a
validation-errors list.

The lineage is declared and unreconciled: the phase-gate module docstring states
that it generalizes the plan-approval pattern into a factory parameterized by
document phase, yet the older node was never migrated onto it. The divergence is
structural rather than cosmetic - return shape, resume payload shape, and the
name and type of the revise-signal field all differ for the same conceptual
step. Whoever adds a third gate, or changes how a rejection routes back with a
note, faces two incompatible conventions and no cross-reference naming either as
canonical. The older convention is already load-bearing in a fragile way: the
worker message builder substring-matches the phrase "Plan rejected by user"
inside the routing-error string, a coupling the newer list-shaped convention
neither shares nor generalizes.

### port-ownership-verification-diverges-by-mechanism | medium | Two independently designed gates answer "does our child own this port?" with disjoint evidence

Two production spawn-readiness gates solve one problem - a bound port does not
prove that the process we spawned owns it, since an un-reaped orphan or a racer
can squat the same port - by unrelated mechanisms. The worker spawn path in
`control/worker_management.py` checks liveness first, then a TCP fast path, then
an HTTP-level ownership check in which the worker self-reports its gateway
lifetime and spawn generation; under the armed desktop profile only an owned
classification is accepted, while unarmed profiles fall back to a lenient
declared-URL comparison. The generic managed-process spawn path in
`lifecycle/manager.py` also checks liveness first, then gates the bound port on
an operating-system-level ownership classification that walks process ancestry
to confirm the listening process is the child or a descendant, degrading to the
bare bound-port signal with a logged warning when ownership cannot be resolved.

That these are one concept implemented twice, rather than two contracts, is
established by their docstrings, which describe the same threat in nearly the
same words. The divergence is that each carries its own independent fail-open
fallback, authenticated by evidence the other cannot see: an HTTP self-report on
one side, resolved process ancestry on the other. Neither can be expressed in
terms of the other.

The consequence is a coordination failure rather than a present defect. The
`lifecycle/manager.py` docstring already records that a readiness gate on a
security-relevant port should require the stricter ownership classification
instead of accepting an unresolved result. Whoever acts on that note has no way
to discover that a second, independently designed ownership gate exists for the
identical threat and needs the equivalent hardening.

### boot-harness-protocol-triplicated-not-duplicated | medium | A third boot harness the consolidation never reached, and its poll loop is not death-aware

This entry extends the open `boot-harness-protocol-duplicated` finding rather
than raising a new one. That finding recorded two real-process boot harnesses as
parallel implementations of one boot-and-retry protocol and asked for analysis
of which parts are genuinely one protocol.

Part of that has since been answered by consolidation: the acceptance harness
now imports the spawn-until-ready and readiness helpers from the shared gateway
boot module, so that pair is unified. The analysis owed should record that the
consolidation did not reach a third implementation. The service-test harness
imports only the free-port helper from the shared module and rolls its own wait
loop, used by both its start path and its process-health wait.

The gap is diagnostic rather than cosmetic. The shared readiness helper is
death-aware: it checks the spawned process's exit status on every iteration and
raises a typed boot error immediately, carrying the exit code and a log tail,
the instant the bind-race failure occurs. The service-test wait loop never
checks the spawned process's liveness at all. It polls the HTTP probe until a
generic deadline and then raises a timeout carrying neither exit code nor log
tail. A compose-stack gateway that dies on the bind race therefore sits through
the full deadline before failing, with materially worse diagnostics than the
consolidated path already produces elsewhere.

For the shared-core analysis the original finding requested, the reachable
conclusion is this: the death-aware-poll-first shape and the typed
exit-and-log-tail failure are the genuinely common core, while how the process
is reached and spawned - a subprocess handle against a compose-managed container
- is the seam that must stay pluggable. The acceptance harness's typed error,
which its own retry loop catches in order to reap before retrying, must survive
any merge.

### triplicated-node-metadata-extraction | medium | One five-field node-metadata projection is typed out three times across two subpackages

The same five-field extraction from a graph node's metadata - role, display
name, description, provider, and model, each coerced through the same
string-with-empty-default idiom - is implemented three separate times with no
shared helper. `worker/graph_lifecycle.py` reads it from the compiled graph's
node metadata in the worker process to build the outgoing registration payload.
`streaming/subscribers.py` reads it from the compiled graph's node metadata
in-process to populate its node-metadata cache. `streaming/emitters.py` reads
the same five keys from the relayed payload to populate the equivalent cache on
the gateway side.

All three agree today, field for field, so this is latent rather than live. It
is recorded because the field list is typed out three times across two
subpackages and the split between the direct readers and the relayed reader is
exactly the distance that invites a future field - a capability key, for
instance, which the model-profile layer already carries - being added to one and
not the other two. The failure mode would be silent: a field present in the
worker's payload and absent from one cache, with no error anywhere.

### duplicated-workspace-identity-normalization-formula | low | The workspace identity formula is hand-copied across the write and read seams

The normalization that produces a workspace identity - case-normalizing the real
path - is hand-copied in two places rather than shared: the write seam in
`database/thread_repository.py` that builds the discovery selectors, and the
read seam in `control/run_discovery_service.py` that normalizes an incoming
workspace argument. Both were read in full and are byte-identical today, same
formula and same order, so workspace-scoped active-run discovery round-trips
correctly.

Latent, and the trigger is specific: because the normalized value is hashed into
a workspace key, an edit to only one side - stripping a trailing slash, or
swapping the real-path call for a resolve call to harden symlink handling -
silently desynchronizes the write-time hash from the read-time hash. Workspace
scoped run discovery would then return empty results with no error surfaced
anywhere. The severity is low only because both sides currently agree; the
failure mode, if they diverge, is silent and hard to attribute.

## Recommendations

The rejection-semantics family is the urgent one and should be taken as a single
repair rather than three, and the repair is larger than it first appeared. The
canonical set is tested against the response option identifier while carrying
the vocabulary of the option kind, and the repository's own fixtures prove those
are different fields with different spellings - a shipped provider offers the
identifier `reject` with kind `reject_once`. So the fix is not to add a missing
literal to one predicate. It is to decide which field carries the rejection
verdict, derive that verdict once, and have every settlement site call it: the
submission path, the resolution path, and the progress backstop.

Deriving from the option kind rather than the identifier is the more promising
direction, because the kind is the field with a closed vocabulary while the
identifier is provider-defined and free-form; that choice should be recorded,
since it changes what the durable record means. The repair must land with tests:
`thread/permission_fsm.py` has no test file at all, which is why two live
defects in it went unobserved, and the missing assertions are a rejection
payload driven through the real resolution handler and a provider whose
identifier is not its kind. Two further denial-shaped predicates exist, in the
ACP RPC handlers and the streaming option-kind mapper. Neither is a defect where
it sits - the ACP one is, by accident, closer to correct for the identifiers it
actually receives than the canonical set is - but both belong in the inventory
when the canonical predicate is chosen, because they are evidence that the
current canonical set does not serve every consumer.

The provider-eligibility gate should answer its question with the resolver that
already exists. The credential-aware probe is the more complete implementation
and the weak command-only resolver feeds a value whose own enum docstring
promises execution-readiness. Reconciling them is a behaviour change on an
operator-facing surface and a fail-closed admission gate, so it wants a recorded
decision rather than a silent swap - specifically on whether readiness should
report per-provider reasons rather than a flat eligible list.

The three declared-canonical-with-siblings findings share one remedy and one
lesson. Convert the three atomic-write siblings onto the audited writer, and
give the synchronous kill path the same bounded wait its async twin documents.
The lesson is that a module docstring claiming to be the single home for a
concept is an assertion, not an invariant, and nothing in the tree currently
enforces it. A cheap durable guard would be a test per canonical seam asserting
it is the only implementation of its shape - the kind of check that would have
caught all three of these at the moment the sibling was written.

The two gate and harness protocol findings need a decision before code. For the
approval gates, name one convention canonical and record it, because the choice
between a dictionary state patch and a routing command object is architectural
and a third gate is otherwise guaranteed to pick arbitrarily; the fragile
substring match on the revise-signal string should not survive that decision.
For the boot harnesses, the shared core is identified above and the pluggable
seam is named; what remains is whether the third harness adopts it or is retired
in favour of the consolidated helper.

The two latent findings - the triplicated metadata projection and the copied
workspace identity formula - are correctly deferred but should not be forgotten,
because both fail silently rather than loudly. Each is a small extraction and
neither carries architectural weight.

Finally, on method. Two investigators on independent axes converged on the
plan-approval defect through different search paths, which is the strongest
signal this pass produced and an argument for running redundant axes rather than
partitioning the tree cleanly between them. The investigators also returned
roughly thirty adjudicated non-findings - correctly divergent pairs that a
naive duplicate hunt would have flagged - including two provider turn loops that
must not be merged because the wire protocols genuinely differ, three sweep
functions that correctly use different signals because their artifacts carry
different evidence, and a permission-option adapter that is a documented thin
layer rather than a second implementation. Those adjudications are the reason
the findings above can be trusted, and they are recorded so the same ground is
not swept again.

Coverage was not complete, and the gaps are known and named rather than papered
over. Closed during follow-up passes: the `ipc/` package holds no process,
connection, or resource lifecycle code at all, only schemas, so there was
nothing on that axis to find; the ACP terminal handlers were opened and cleared,
delegating correctly through the shared bounded escalation; and the desktop
credential path authority was confirmed to be genuinely single, with the
settings property delegating to the profile layout rather than restating it.

The environment example is now swept in full rather than sampled. Every declared
knob across the watchdog, websocket, internal IPC, ACP, OAuth, MCP, database,
authoring-subscriber, and context-sizing families was checked against its
declaring field default and then traced to its consumers for scope. Exactly one
scope mismatch surfaced, recorded above; every other default matched exactly.
The only names not comparable are the third-party passthrough variables read
directly from the process environment by external SDKs, which have no declaring
field to compare against and no second binding site in the tree. A negative
result of that breadth is worth recording, because it bounds where this class of
defect can still hide.

The mock-fixture question was investigated and settled at reachable in
principle, recorded in that finding. It surfaced a standing limit worth keeping:
the canned responses that drive the mock provider are not in this repository at
all, so no audit of the mock path can settle a question about what a mock turn
emits from this tree alone.

Still unreached: the database repository row mappings and the `team/` preset
translation on the mapping axis; the HTTP-transport half of the ACP authoring
binding, where only the stdio path was read end to end; and the watchdog restart
loop, which the containment-leak finding's accumulation claim infers from
surrounding structure rather than direct reading - that claim should be read as
inferred until someone reads the loop.
