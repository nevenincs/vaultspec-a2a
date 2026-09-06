---
tags:
  - '#audit'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-09-06'
body_schema: 'body-v1'
body_hash: 'sha256:496a6772d5eade4fc33caf2113ea58bf01ee1b790268018aaa19ccb2a04db548'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---
# `provider-model-catalog` audit: `implementation review`

## Scope

Review S01's normalized catalog contracts, canonical selection identity,
structured health, TTL refresh behavior, S02's prompt-free ACP discovery,
S03's Codex app-server catalog discovery, and S13's Dashboard catalog
adapter/composer migration against the accepted provider-owned catalog
decision.

## Findings

### provider-expiry | high | Local TTL initially outlived provider catalog expiry

Resolved in S01. Cache publication now clamps its monotonic deadline and served
expiry to the provider catalog's earlier expiry, and immediately treats a
provider-stale result as stale. Direct coverage proves a long local TTL cannot
make an expired provider catalog fresh.

### forced-single-flight | medium | Concurrent forced callers initially refreshed serially

Resolved in S01. Forced callers now retain the entry generation observed before
waiting and reuse a peer's completed refresh, preserving one discovery call per
concurrent refresh wave. Direct coverage exercises twelve concurrent forced
callers.

### shallow-immutability | high | Caller-owned lists could mutate frozen contracts

Resolved in S01. Every sequence-bearing contract now detaches caller-owned
inputs into tuples during construction. Direct coverage mutates the original
model, capability, native-control option, control, and selection lists and
proves the normalized records remain unchanged.

### invalidation-fence | high | In-flight discovery could overwrite invalidation

Resolved in S01. Per-lane generations now fence refresh publication and raise a
typed invalidation error when the lane changes during discovery. Direct
concurrency coverage invalidates a blocked refresh and proves no result is
published.

### resource-bounds | medium | Catalog payloads and cache indexes were unbounded

Resolved in S01. Catalog text and sequence fields now enforce explicit ceilings.
The cache has a configured lane ceiling, evicts expired inactive lane state, and
refuses growth when no safe eviction candidate exists. Direct coverage proves
display metadata rejection and expired-lane eviction.

### s12-provider-catalog-loopback | medium | Catalog route was only structurally tested

Resolved in S12. The Rust route now has a real TCP loopback proof through the
public handler: it performs discovery and health probing, forwards the bounded
catalog read, and preserves opaque provider, entry, native-control, and
structured-health values inside the Dashboard envelope. The focused Rust suite
passes 30 tests after this proof was added.

### s13-legacy-run-projection | medium | Direct migration initially hid existing legacy assignments

Resolved in S13. `run-status` now reads legacy persisted `assignments` only
when no current `frozen_assignment` is present, retaining a separate read-only
projection for existing-run roster/restart inspection. The legacy row cannot
produce a new provider catalog selection.

### s13-unneeded-catalog-query | medium | Catalog discovery initially ran outside team mode

Resolved in S13. The Dashboard catalog query now requires both a resolved
workspace and an active selected team preset; single-agent authoring does not
trigger provider discovery or refresh.

### s13-wire-regression-proof | medium | Direct provider-catalog wire coverage was initially incomplete

Resolved in S13. Raw-envelope adapter tests now prove unknown/omitted and
stale health fails closed, revision/control drift invalidates a held selection,
and legacy status stays readable. The Composer feature render path asserts the
exact opaque `selection` body that reaches run start.

### acp-error-redaction | high | Provider diagnostic text crossed the safe discovery boundary

Resolved in S02. ACP JSON-RPC errors are classified into static local messages
without retaining provider-controlled diagnostic text. Direct coverage proves a
credential-like value in an error message cannot escape.

### acp-output-budget | medium | Discovery output was not bounded across the operation

Resolved in S02. Stdout and stderr share one one-MiB operation budget. Oversized
stdout fails closed and oversized stderr terminates the contained provider tree
before surfacing a protocol error. Per-frame and response-count bounds remain.

### acp-lifecycle-proof | medium | Normalization tests did not exercise discovery cleanup

Resolved in S02. Two service tests invoke `discover_acp_catalog` through the
production spawn path against the installed Claude ACP adapter. They prove the
initialize/session-new-only path returns after cleanup and cancellation also
completes containment cleanup; no provider prompt is sent.

### acp-bound-alignment | medium | Adapter limits exceeded the S01 contract limits

Resolved in S02. ACP normalization rejects more than 256 models, 32 native
controls, or 128 control options with `AcpCatalogProtocolError` before immutable
S01 construction. Direct coverage exercises the control and option ceilings.

### codex-failure-lifecycle-proof | medium | Failure cleanup initially lacked production-path evidence

Resolved in S03. Direct real-process tests now drive provider RPC failure with
credential-shaped diagnostic text and aggregate stderr exhaustion through
`discover_codex_catalog`, then prove the contained process tree is gone. The
output-budget failure is surfaced after independent cleanup rather than being
masked by the stdout EOF caused by terminating the over-budget process.

### codex-pagination-method-proof | low | Cursor forwarding and prompt-free sequencing were initially inspection-only

Resolved in S03. A bounded malformed-process fixture records the exact request
stream through a repeated-cursor failure. The proof observes `initialize`,
`initialized`, `account/read`, and cursor-bearing `model/list` only before
failure, with no thread, turn, prompt, or completion-bearing method; successful
installed runtime coverage continues through
`modelProvider/capabilities/read`.

### codex-control-scope | high | Model entries initially did not identify their applicable native controls

Resolved in S03. `ModelCatalogEntry` now carries immutable bounded
`native_control_ids`, and `ProviderCatalog` rejects any reference that does not
name an advertised control. ACP binds its session-wide controls to every model;
Codex binds only each model's own reasoning-effort and service-tier controls.
Catalog revisions cover the association, and direct tests prove both shared and
model-scoped behavior.

### kimi-secret-bearing-provider-list | high | Configured provider discovery exposes raw credential fields

Resolved in S04. The adapter consumes `kimi provider list --json` only inside
the discovery boundary, validates model references by provider-table membership,
and retains no provider record or diagnostic output. Static protocol errors and
installed-CLI coverage prove a configured API-key value does not cross the
normalized result boundary.

### kimi-pipe-drain-order | high | Waiting for process exit before draining output could deadlock

Resolved in S04 before final review. Stdout, stderr, and process exit are awaited
concurrently under one timeout and one aggregate one-MiB budget. A real spawned
process emits a valid response above a typical pipe capacity; discovery returns
and the process tree is reaped.

### kimi-current-env-contract-drift | medium | Existing factory variables do not configure the installed CLI catalog lane

Open and assigned to S06 registration/factory integration. The installed CLI
used for S04 recognizes the temporary configured-lane names
`KIMI_MODEL_API_KEY` and `KIMI_MODEL_BASE_URL`; the existing factory and
readiness path inject and gate on the older `KIMI_API_KEY` and `KIMI_BASE_URL`
contract. S04 remains truthful by reporting only what `provider list --json`
serves. S06 must reconcile launch, readiness, and catalog configuration against
one verified installed-CLI contract before the Kimi lane is registered.
### kimi-real-subprocess-boundary-proof | medium | Initial tests did not exercise both pipes, aggregate breach, or timeout cleanup

Resolved in S04 after independent review. Real spawned-process coverage now
writes above typical pipe capacity to both stdout and stderr, breaches the
shared one-MiB budget across the two streams, and hangs past the discovery
timeout. Each path proves its static failure where applicable and full process-
tree reaping; configured and unconfigured installed-CLI enumeration remain
separate prompt-free proofs.
### p01-s11-catalog-route-host-state | medium | Resolved: route evidence follows observed catalog state

Type: test contract drift. Status: the ER19 route defect is corrected at `7d8c04df06299dc58ae8fd1a5f4092291f3042ab`; owning step `P01.S11` is reopened and pending. The authenticated real-ASGI route test no longer assumes OpenAI and Z.AI enumeration are unavailable at fixed array positions. It keys the parsed v1 response by provider identity, accepts only an observed available or unavailable catalog result for those environment-dependent lanes, and validates the corresponding payload: catalog and health status agree; an available catalog has entries, revision, expiry, and authenticated evidence; an unavailable catalog has no entries and carries a bounded reason. Both exact lanes remain `not_admitted` and non-selectable regardless of catalog availability, so discovery cannot become completed-turn evidence. The focused 49-test behavior set passes across cold catalog discovery, stale and invalid selection refusal, independent health, served-entry validation and freeze, same-ID replay/conflict/race, durable modern restart, legacy frozen-profile disclosure, and exact frozen ACP backend reuse. Formal review `16066b83983a90a6a7dc067f98510e3fc5c040fc` correctly found that this battery proves legacy disclosure rather than a real persisted legacy startup redispatch, and that preceding policy-retirement step `P01.S10` remains open. S11 cannot close until S10 completes and a fresh gateway/worker restart proves exact persisted legacy redispatch without catalog re-resolution.

### p01-s11-legacy-restart-proof-absent | high | The 49-test battery does not exercise a real legacy restart

Type: behavioral evidence completeness. Status: open; review-blocking for `P01.S11` at `7d8c04df06299dc58ae8fd1a5f4092291f3042ab` and therefore for remediation S05. P01.S11 explicitly requires legacy restart with real behavior. The selected live gateway test seeds a pre-catalog `model_profile` row and proves only run-status disclosure. `test_restart_prefers_modern_selection_over_legacy_profile` is a pure helper check that a modern selection wins when both metadata forms exist. No selected or repository test seeds a real legacy frozen assignment in durable stores, boots a fresh second gateway and worker, drives startup reconciliation/redispatch, and observes that provider construction uses the exact persisted legacy provider/model/control values without current catalog resolution. The Step Record and audit therefore overstate the 49-test battery as legacy-restart proof. Ownership: reopen P01.S11 and add the real persisted legacy restart/redispatch discriminator before review closure.

### p01-s11-premature-plan-closure | high | S11 is closed while its preceding policy-retirement implementation remains open

Type: plan sequencing and lifecycle accuracy. Status: open; review-blocking. Core reports P01.S10 open and next while P01.S11 is checked. S10 removes provider/model policy from new product presets and preserves legacy restart; S11 is the following proof step and cannot close its full served-validation and legacy-restart promise before that implementation boundary lands. The host-state route correction is independently valid, but closing the whole S11 row conflates one ER19 repair with the step's broader post-S10 verification contract. Ownership: reopen S11, complete or explicitly restructure the P01.S10/S11 dependency through Core, then close S11 only after its full real-behavior suite passes.

### p01-s11-formal-review | high | FAIL - host-independent route fix passes but S11 evidence is incomplete

Type: implementation review disposition. Status: open. The reviewed commit's exact parent is `f0e7fe9d4c6bd4422b0db45ca02ea4b388a02502`; its seven committed paths contain only the catalog test/lifecycle documentation and exclude the separately landed resource-lifetime work. The provider-keyed route assertion is deterministic across credentialed and uncredentialed OpenAI/Z.AI hosts: it accepts only typed available/unavailable catalog states, keeps catalog status synchronized with the catalog health axis, requires complete available or unavailable payload invariants, and independently requires exact-mode `not_admitted` plus `selectable=false`. The focused 49 tests pass and cover discovery/cache behavior, stale and invalid served-selection refusal, independent health, freeze/validation, replay/conflict/race, modern durable restart, legacy disclosure, and exact frozen ACP backend reuse. Dedicated coverage preserves deny-by-default, provider-plus-execution-mode identity and non-transferable admission. Ruff, ty and format checks are recorded, no deprecated API or option is introduced, and feature Core is clean. The two preceding HIGH findings mean the passing subset is not enough to close P01.S11 or unblock remediation S05.

## Recommendations

Keep catalog normalization, redaction, containment, aggregate output ceilings,
invalidation fencing, provider expiry, single-flight refresh, Dashboard
selection gating, and legacy-run read boundaries in focused tests. No open
critical, high, medium, or low S01/S02/S12/S13 finding remains after remediation.

- For `p01-s11-legacy-restart-proof-absent`, seed a real pre-migration frozen profile in durable stores, restart fresh gateway and worker instances, and prove redispatch constructs the exact persisted legacy assignment without catalog re-resolution.
- For `p01-s11-premature-plan-closure`, reopen S11 and preserve the valid ER19 route correction while P01.S10 and the missing real-behavior proof are completed.
### p01-s11-rag-data-plane-version-drift | medium | open

Type: test environment and repository tooling. Status: open and nonblocking for
P01.S11 runtime behavior. The S11 broad provider, gateway, redispatch, IPC and
compiler run passed 964 tests with 36 deselected and one environment failure:
`test_the_declared_channel_is_the_servers_own_root_authority`. Its real MCP
subprocess reached the shared vaultspec-rag endpoint at PID 56028 on
`127.0.0.1:8766`, but the service did not report a version compatible with the
0.4.23 client, so `search_vault` returned the typed service-down error before
the test could inspect project confinement. A read-only `vaultspec-rag server
start` probe confirmed the running service cannot be attached and requires an
operator-owned restart. Owner: embedded-runtime-remediation `W01.P02.S06` and
vaultspec-rag service lifecycle. The shared process was not stopped or restarted
inside P01.S11.
### p01-s11-cold-catalog-shutdown-timeout | medium | open

Type: provider-degradation test stability and resource lifecycle. Status: open
and nonblocking for the reviewed S11 test changes. A post-broad focused rerun
observed one existing restart evidence test spend 91.79 seconds in a cold
provider-catalog refresh, log a Claude discovery `TimeoutError`, and then exceed
its five-second Uvicorn shutdown wait while the cancelled request and SQLite
connection unwound. The same test passed in the preceding 71-test focused run
and the 964-pass broad run, and the final changed-path discriminator run passed
20 tests, so this is intermittent host/provider degradation rather than a
repeatable selection-authority failure. Owner: embedded-runtime-remediation
`W01.P02.S06` and provider catalog resource-lifecycle tests. Preserve the
failure for a bounded cold-refresh/shutdown discriminator; do not widen S11's
test timeout as a substitute.
### p01-s11-restart-proof-bypasses-production-worker | high | open

Type: behavioral evidence completeness. Status: review-blocking for P01.S11 at
`ba9f70bd4d280ca95a3f31131443949317a0ae9d`. The positive current-schema
restart test uses a real SQLite record and production
`redispatch_reconciling_threads`, but invokes that function directly and sends
the request to `_InProcessWorker`, the shared minimal FastAPI recorder reached
through `httpx.ASGITransport`. It does not boot a fresh gateway, cross a real TCP
worker boundary, enter `create_worker_app` or its Executor, or prove the exact
frozen assignment is accepted and consumed by a fresh production worker. This
contradicts the plan's explicit real-behavior and no-fake/no-mock acceptance
boundary. Owner: P01.S11. Seed the schema-v1 selection in real durable stores,
boot fresh production gateway and worker instances over their real transport,
drive startup recovery, and prove the production worker consumes the exact
provider, execution mode, model and controls without catalog re-resolution.

### p01-s11-wire-refusal-type-is-not-asserted | medium | open

Type: test precision. The retired-input matrix proves HTTP 422 and zero recorded
dispatch, but accepts any non-empty `detail`; it never verifies that each refusal
is the expected typed field or stale-membership outcome, nor that the retired
value is absent from the response. The source currently returns closed-schema
validation or bounded selection errors, so this is an evidence defect rather
than a confirmed runtime bypass. Owner: P01.S11. Assert the exact error type and
field location for forbidden schema keys, the bounded domain reason for stale
catalog identity, and absence of each retired value from the rendered response.

### p01-s11-test-only-formal-review | high | FAIL - production restart evidence is incomplete

Type: formal implementation review disposition. The reviewed test-only commit
has exact parent `bc0d59984946789e8eaf6fcbd4ec40708fa79d67` and exactly five test
paths. ConfigOptions wins over or exclusively refuses
`models.availableModels`; existing live ACP process coverage exercises the
production discovery boundary. The assembled source and tests preserve stale
refusal, independent health axes, served-entry validation and freeze, same-id
replay/conflict/race, exact current provider/mode validation, zero-contact
retired-state refusal, ER19's provider-keyed observed availability, and the
seven external plus conditionally armed deterministic/mock inventories without
a Gemini lane. No runtime contract defect was found.

Independent changed-path verification passes 51 tests in 53.19 seconds; Ruff,
format, Ty and diff checks pass. The recorded 964-pass broad run's one RAG
service-version failure and the intermittent cold-catalog shutdown timeout are
correctly classified as MEDIUM, owned by remediation W01.P02.S06, and do not
invalidate the passing S11 behavior subset. The HIGH production-restart gap and
MEDIUM refusal-typing assertion gap prevent P01.S11 closure. Keep S11 and
remediation W01.P02.S05 open pending correction and formal re-review.
### p01-s11-validation-error-input-reflection | medium | resolved

Type: runtime security and response disclosure. Tightening the P01.S11 retired
input discriminator exposed that FastAPI's default request-validation response
returned the rejected caller value in each error object's `input` field. A
retired provider, model or profile value was therefore refused before dispatch
but reflected through the public 422 response, violating the no-disclosure
contract. The gateway now owns a bounded `RequestValidationError` handler that
retains the actionable validation `type`, field `loc` and safe `msg` while
removing `input` and `ctx`. Real loopback tests prove exact typed field errors,
exact bounded stale/domain reasons, absence of every submitted retired value,
and preservation of actionable current-schema validation. Resolved in the
P01.S11 correction following `ba9f70bd`; formal re-review remains required.

### p01-s11-production-worker-boundary | high | resolved

Type: behavioral evidence completeness. Correction
`550f26fc944182eca92d5afe007f925dd3e9d388` replaces the minimal
`ASGITransport` receiver on the positive restart path with a child production
gateway, its lazily auto-spawned production worker, real loopback HTTP, seated
durable SQLite state and the production Executor. A seeded schema-v1 run with a
revision absent from the live catalog reaches completion and worker-produced
history under its frozen deterministic lane. The prior production-boundary HIGH
is resolved.

### p01-s11-validation-error-contract | medium | resolved

Type: runtime security and response compatibility. The bounded
`RequestValidationError` handler removes only Pydantic's reflected `input` and
`ctx`, retains actionable `type`, `loc` and `msg`, and matches the fields declared
by the OpenAPI validation-error schema. Direct loopback assertions cover each
retired request field, exact stale/unknown-lane domain reasons, absence of the
submitted retired values, and a current schema-version error. No handler-wide
compatibility or serialization regression was found. The prior refusal-typing
MEDIUM is resolved.

### p01-s11-full-frozen-identity-is-sampled-not-compared | high | open

Type: replay and restart evidence integrity. Status: review-blocking for P01.S11
at `550f26fc944182eca92d5afe007f925dd3e9d388`. The real-process test checks each
role's provider, execution mode, model, controls and catalog revision from the
status disclosure, then checks only provider and model in worker-produced
history. It never compares the complete persisted/disclosed frozen selection or
its digest with the seeded record, and it does not expose the exact assignment
accepted by the production worker. The test can remain green if entry IDs,
display identities, provenance, defaulted-control identity, roles, fallbacks or
digest drift; its deterministic lane also has empty controls, so dropping a
non-empty control would not discriminate. Owner: P01.S11. Assert full canonical
frozen-assignment JSON and digest equality before and after recovery and bind
that exact complete assignment to production-worker consumption, using a
non-vacuous controlled lane where necessary, without a recording fake or patch.

### p01-s11-correction-formal-rereview | high | FAIL - complete frozen identity is not proven

Type: formal implementation review disposition. The correction has exact parent
`a93ab85292667e5c170df20914059d8790434f8c`, changes the gateway validation
handler and two S11 test paths, and resolves both preceding findings at their
reported production-process and typed-error boundaries. The source still meets
the current-only catalog contract; no runtime selection, restart or global
validation-response regression was found. The new full-identity HIGH prevents
S11 closure.

The four-test correction selection first reproduced the queued resource-lifecycle
class: after a worker health `ReadTimeout`, the seeded run remained reconciling
and the discriminator failed in 158.88 seconds. After concurrent Dashboard live
processes were stopped, the exact discriminator passed in 61.71 seconds; the
other three correction tests passed. This intermittent host/process contention
remains MEDIUM under remediation W01.P02.S06 and does not replace the separate
exactness blocker. The recorded broader 136-pass, OpenAPI six-pass, Ruff,
format, Ty and diff evidence is consistent with independent static checks;
feature Core checks have zero diagnostics. Keep P01.S11 and remediation
W01.P02.S05 open pending exact-identity correction and formal re-review.
### p01-s11-graph-cache-omits-frozen-assignment | high | resolved pending formal review

Type: execution state isolation and restart integrity. The full-assignment
production discriminator exposed that the worker graph cache keyed only on team
preset, canonical workspace and autonomous mode. Concurrent runs with different
schema-v1 frozen assignments could therefore share whichever graph compiled
first, silently substituting one run's provider/model/control/fallback authority
for another's. The P01.S11 correction makes the canonical semantic digest of
the complete closed IPC model assignment the fourth required cache-key element,
rejects a changed assignment on an already mapped thread, and retains reuse only
for exact equal assignments. Real child gateway/worker recovery now drives two
equal freezes and one distinct freeze at the same topology/workspace/mode and
proves separate per-thread checkpoint digests; direct cache tests cover equality,
partitioning, and changed-assignment refusal. No three-element compatibility
constructor remains. Owner: P01.S11; formal re-review is required before closure.

### p01-s11-node-metadata-is-not-thread-scoped | high | resolved pending formal review

Type: execution state isolation and truthful disclosure. While binding complete
assignment evidence, a distinct concurrent run revealed that the control
surface's graph node metadata cache was global by node name rather than scoped by
thread. Histories or team projections for runs sharing node names could therefore
show provider/model metadata from the most recently registered graph. The S11
correction keys live graph metadata by thread and node at registration, cache-hit,
relay, emission, team-status and snapshot seams, with no global lookup. The
production Executor also writes the graph's safe node descriptors and complete
assignment digest into each run's LangGraph checkpoint; completed-run history
prefers that durable thread-scoped authority. A real child gateway/worker recovery
with concurrent equal and distinct assignments proves each run retains its own
provider, model and digest, and a direct relay test proves one thread cannot
overwrite another. Owner: P01.S11; formal re-review is required before closure.

### p01-s11-execution-reentry-omits-frozen-assignment | high | open

Type: messaging, resume and restart integrity. Status: review-blocking. The new
worker cache correctly compares a mapped thread's complete assignment digest,
but the production dispatch constructors for message follow-up, permission
response, clarification response, verdict resume and direct-control recovery do
not carry `model_assignment`. The closed IPC model therefore supplies `{}`. A
current-schema run with a non-empty accepted assignment is rejected before its
next graph turn because the empty digest does not match the graph it already
compiled. Independent review reproduced that exact production-shape refusal
against a cached graph. Startup redispatch carries the frozen map, so the
three-run restart test does not exercise the broken follow-up and resume paths.

Ownership: introduce one shared current-schema execution re-entry resolver that
loads and validates the exact authoritative frozen selection, produces its
compiler map, and supplies it to every ingest/resume constructor. Message,
permission, clarification, verdict and direct-control recovery must all use that
single seam so a new route cannot omit the authority again. Absence, corruption,
retired keys or an old schema must produce a bounded typed incompatible refusal
before dispatch, with no translation, repair or disclosure. Add real current-run
message, permission, clarification, verdict and recovered-action tests proving
the same complete digest reaches the worker and the graph turn executes.

### p01-s11-thread-assignment-binding-depends-on-cache-residency | high | open

Type: concurrency and execution authority isolation. Status: review-blocking.
`get_or_compile_graph` compares the mapped thread's digest only when its graph is
still resident in the bounded LRU. Normal graph eviction leaves the thread-to-key
mapping but skips the comparison, allowing a changed assignment to compile and
replace the mapping. A fresh worker has no in-memory thread mapping at all, and
checkpoint preflight never compares the checkpoint's assignment digest with the
incoming current freeze, so restart has the same bypass. Two first dispatches
for one thread can also cross the compile await with different assignments before
either installs a mapping; both construct graphs, and the later cache write wins.
The committed refusal test covers only the cache-resident sequential case. Thus
assignment immutability is not guaranteed independently of cache lifetime,
worker lifetime or concurrent delivery.

Ownership: atomically bind each thread to its accepted digest before compilation
and compare every later dispatch against that binding whether or not the graph
is resident. On a fresh worker, compare the incoming exact current-schema digest
with checkpoint and durable frozen authority before construction. Serialize
same-thread compilation or reserve one in-flight compile so concurrent equal
dispatches share it and concurrent different assignments receive the same typed
mismatch before any provider construction or graph execution. Preserve
cross-thread reuse only for exact four-element key equality. Add eviction, fresh
worker, concurrent first-dispatch, equal duplicate, changed duplicate and
compile-failure cleanup discriminators.

### p01-s11-current-checkpoint-evidence-is-not-reconciled | medium | open

Type: durable evidence continuity. The safe agent descriptors and complete
assignment digest are written only when checkpoint preflight calls an ingest
`is_first_ingest`. A current-schema run whose checkpoint already existed before
this correction can restart from its exact database freeze, but its checkpoint
never gains these fields; once live metadata is pruned, history can return no
assignment digest or agents. The production restart discriminator seeds database
rows with no existing checkpoints, so it exercises first ingest rather than this
upgrade boundary.

Ownership: when a checkpoint lacks the evidence fields, reconcile them only from
the exact validated current-schema authoritative frozen assignment and the graph
compiled from it. Never accept, repair, translate or migrate missing/old provider
schema state. If no exact current freeze exists, return the existing typed
incompatible outcome before provider contact. Add a fresh-worker test with a
pre-existing current checkpoint and exact freeze, plus corrupt, absent and
retired frozen-authority negative controls.

### p01-s11-full-assignment-isolation-positive-controls | low | verified

Type: architecture and compatibility. The cache key is now exactly preset,
canonical project, autonomous posture and SHA-256 of canonical JSON for the
complete closed compiler assignment; no three-tuple constructor or alias remains.
The digest covers nested role, provider, mode, catalog revision, entry, model,
controls, fallback and provenance values. Equal assignments reuse a graph and
distinct assignments partition it. Live node metadata is keyed by thread and
node across registration, worker relay, team status and history fallback, while
checkpoint descriptors take precedence. The API exposes only the bounded
64-character digest and existing safe agent projection. No global node fallback,
retired provider/profile authority or deprecated compatibility path was found in
the 28-path correction.

Independent verification reproduced the omitted-assignment failure and passed
63 focused cache, node-metadata and snapshot-schema tests. The committed evidence
reports the broader 53- and 77-test selections, six OpenAPI checks, Ruff, format,
Ty, diff and feature Core green. The production three-run test compares the full
frozen disclosure/digest, differentiates a non-empty controlled fallback, and
observes distinct checkpoint digests through a real child gateway and worker;
it does not cover the re-entry, eviction or existing-checkpoint cases above.

### p01-s11-full-assignment-correction-formal-review | high | FAIL

Type: formal implementation review disposition. Commit
`aae2ac389ddb63a891b90c77b9236b6bb6e7db29`, exact parent
`d8c7668fc9c860ea3f7140cc45b4d3be66db9d59`, fixes cross-thread cache identity
and live metadata scoping, but does not preserve frozen authority across normal
message/resume dispatches or independently of LRU residency and concurrent first
delivery. The two HIGH findings block P01.S11 and remediation W01.P02.S05. Keep
S11 open, correct the shared re-entry and atomic thread-binding seams, add the
specified evidence, and obtain formal re-review. This review changes no runtime
or plan row.

### p01-s11-checkpoint-assignment-evidence-is-not-validated | medium | open

Type: persisted-state integrity and bounded failure. Snapshot enrichment accepts
any string as `model_assignment_digest`; the public schema later requires exact
lowercase 64-hex, so malformed checkpoint state can turn history serialization
into a server error instead of a typed degraded/incompatible result. A
well-shaped but incorrect digest is also never reconciled with the exact durable
current-schema frozen authority. The public frozen-selection digest and compiler
map digest cover different canonical objects, so clients cannot establish this
equality themselves.

Ownership: derive the expected compiler-map digest server-side from the exact
validated current-schema freeze and compare it with checkpoint state. Missing,
malformed or mismatched evidence must degrade or refuse with a bounded typed
state outcome; absent, old or retired provider authority remains incompatible
and is never translated or repaired. Test malformed and valid-but-wrong digests
through the real history route.

### p01-s11-checkpoint-descriptors-are-not-closed-at-read | medium | open

Type: persisted-state validation. Snapshot enrichment accepts every descriptor
dict and spreads its fields after the checkpoint-owned node name, allowing a
corrupt descriptor to overwrite `node_name` and `agent_id` and pass arbitrary
values toward the response model. The write path emits a safe projection, but
restart reads must treat checkpoint state as fallible rather than relying on that
provenance forever.

Ownership: validate exact allowed descriptor keys, bounded string values and
command-bound node identity at checkpoint projection. Reject overrides of node
or agent identity and surface malformed state as a bounded degraded snapshot.
Add corrupt descriptor and safe current descriptor controls at the history
route.

### p01-s11-team-status-drops-thread-association | medium | open

Type: concurrent state projection. Team status now performs correct thread-scoped
metadata lookups, then flattens every active thread's agents into `AgentData`,
which carries no thread id. Two active runs with the same role names therefore
produce indistinguishable duplicate agents that a consumer cannot associate with
the separately served active-thread list. This does not restore cross-thread
metadata lookup, but leaves the combined projection ambiguous.

Ownership: add the originating thread identity to each team-status agent or
define one deterministic per-thread aggregation that preserves association.
Exercise two live threads with identical agent ids and distinct assignments.

### p01-s11-optional-cross-thread-agent-state-accessor-remains | low | open

Type: API hardening. The emitter's agent-state accessor still permits an omitted
thread id and deliberately returns a historical cross-thread aggregate. Current
production callers pass a thread, so no present leakage was reproduced, but the
optional compatibility seam can reintroduce one silently.

Ownership: require thread identity in the accessor and move any deliberate
process-wide diagnostic to an explicitly named bounded method with no role in
run or team projections.
