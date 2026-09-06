---
tags:
  - '#audit'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-09-06'
body_schema: 'body-v1'
body_hash: 'sha256:7a107a2cb7557d13575b7ddbcdb819c7678dd5ac58518af0e0e305b5edfaf421'
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

### p01-s11-execution-reentry-omits-frozen-assignment | high | resolved pending formal review

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

### p01-s11-thread-assignment-binding-depends-on-cache-residency | high | resolved pending formal review

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

### p01-s11-current-checkpoint-evidence-is-not-reconciled | medium | resolved pending formal review

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

### p01-s11-checkpoint-assignment-evidence-is-not-validated | medium | resolved pending formal review

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

### p01-s11-checkpoint-descriptors-are-not-closed-at-read | medium | resolved pending formal review

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

### p01-s11-team-status-drops-thread-association | medium | resolved pending formal review

Type: concurrent state projection. Team status now performs correct thread-scoped
metadata lookups, then flattens every active thread's agents into `AgentData`,
which carries no thread id. Two active runs with the same role names therefore
produce indistinguishable duplicate agents that a consumer cannot associate with
the separately served active-thread list. This does not restore cross-thread
metadata lookup, but leaves the combined projection ambiguous.

Ownership: add the originating thread identity to each team-status agent or
define one deterministic per-thread aggregation that preserves association.
Exercise two live threads with identical agent ids and distinct assignments.

### p01-s11-optional-cross-thread-agent-state-accessor-remains | low | resolved pending formal review

Type: API hardening. The emitter's agent-state accessor still permits an omitted
thread id and deliberately returns a historical cross-thread aggregate. Current
production callers pass a thread, so no present leakage was reproduced, but the
optional compatibility seam can reintroduce one silently.

Ownership: require thread identity in the accessor and move any deliberate
process-wide diagnostic to an explicitly named bounded method with no role in
run or team projections.

### p01-s11-reentry-and-durable-binding-correction | high | resolved pending formal review

Type: execution authority, concurrency and persisted-state integrity. The S11
correction introduces one exact current-schema resolver for startup, message,
permission, clarification, verdict and direct recovery graph re-entry. It
refuses absent, corrupt and retired authority before worker contact and supplies
the same closed compiler map everywhere else. Worker graph acquisition binds a
thread to the canonical complete-assignment digest before compilation, serializes
same-thread first delivery, retains the binding through LRU eviction, and checks
an existing checkpoint on a fresh worker. Equal concurrent deliveries share one
compile; different assignments, malformed checkpoint digests and valid-but-wrong
digests fail before construction.

Current checkpoint evidence is written on every message turn and atomically in
the real LangGraph resume `Command.update`. Read projection compares the exact
lowercase digest with the durable current freeze and accepts only closed bounded
agent descriptors whose identity cannot be overridden. Agents retain their run
identity through history, team status and SSE projection; the optional global
agent-state accessor is removed. Focused cache, checkpoint, schema, OpenAPI and
projection checks pass, as do the real worker clarification message/new-prompt/
decline/startup-redrive cases and the production current-schema restart.

### p01-s11-pre-resume-state-update-invalidated-interrupt | high | resolved pending formal review

Type: recovery and graph-state integrity. While adding checkpoint evidence, the
first correction called `aupdate_state` immediately before `Command(resume=...)`.
A real worker clarification test showed that this minted a new checkpoint and
invalidated the parked interrupt, so the accepted action never executed. Evidence
now travels in the resume command's own atomic `update`, while ordinary turns
carry it in graph input. A current-schema checkpoint missing those evidence fields
is reconciled from the exact validated durable assignment during the real resume;
malformed or mismatched present bindings remain terminal. No migration,
translation, provider substitution or retired authority is accepted.

### p01-s11-fast-clarification-replay-lost-accepted-result | high | resolved pending formal review

Type: idempotency and control messaging. A fast production worker could consume
the parked clarification between the first accepted response and identical
concurrent replays. The replay path found the matching durable action but then
treated the vanished questionnaire as a new invalid request and returned 409.
It now returns the matching accepted action once request identity and canonical
resolution fingerprint agree. The real loopback worker test proves six concurrent
same-id replays remain accepted while the single graph resume completes.

### p01-s11-retired-root-authority-can-accompany-current-freeze | high | resolved pending formal review

Type: compatibility removal and execution-authority validation. The shared
`resolve_execution_authority` seam closes and validates the nested schema-v1
`provider_catalog_selection`, but it checks only the top-level `model_profile`
sentinel before accepting that selection. Independent execution added each of
`profile_id`, `default_profile_id`, `profile`, `default_profile` and `MODEL_MAP`
to otherwise exact current metadata; all five records resolved and produced the
same executable compiler digest. Thus retired durable authority can coexist with
and pass the supposedly closed current execution envelope. The existing restart
matrix labels root-profile cases but inserts those keys into the nested selection,
where exact-key validation already catches them, so it does not discriminate this
boundary.

Ownership: P01.S11. Before parsing the current selection, refuse the complete
ADR/S10 retired root-authority key set, including documented aliases, with the
bounded `retired` incompatibility reason. Never reflect its value or contact a
worker/provider. Add current-valid-freeze-plus-retired-root-key controls for every
key and a real redispatch zero-contact discriminator.

### p01-s11-precompile-checkpoint-read-bypasses-worker-capacity | high | resolved pending formal review

Type: bounded concurrency and degraded-storage handling. `/dispatch` admits and
schedules work while capacity is measured only by `_active_ingests`. The Executor
does not acquire that slot until after graph acquisition. The correction's
`get_or_compile_graph` creates a distinct thread lock/user entry and awaits
`checkpointer.aget_tuple` with no deadline before reaching that slot. Under a
hung or degraded checkpoint backend, authenticated distinct-thread dispatches
therefore remain accepted and can accumulate scheduled tasks, locks and user
entries without the configured concurrent-thread bound. Cancellation cleans an
individual lock user, but it does not bound the number admitted while reads are
stalled.

Ownership: P01.S11. Reserve bounded worker execution/compile capacity atomically
before scheduling or checkpoint lookup, apply the configured bounded checkpoint
read deadline, and release the reservation on success, refusal, timeout,
exception and cancellation. Concurrent admission tests must hold the real
checkpointer read, exceed the limit, observe bounded task/lock state and 429 or
typed refusal, then prove cancellation and timeout return capacity.

### p01-s11-terminal-thread-bindings-are-unbounded | high | resolved pending formal review

Type: bounded resource lifecycle and identity isolation. Every compiled run adds
entries to `_thread_assignment_digests` and `_thread_to_cache_key`; neither map
has a per-thread retirement path. Terminal `_mark_ingest_done` drops token,
catalog and node metadata only, and `GraphLifecycleManager.clear` releases the
identity maps only when the whole worker stops. A long-lived worker therefore
grows permanent state with every completed, failed or cancelled run. Reusing a
deleted thread identity can also inherit the stale digest. The compile lock/user
maps themselves are correctly reference-counted and cleaned after ordinary,
failed and cancelled callers.

Ownership: P01.S11. Add one terminal-only lifecycle release invoked for every
completed, failed, cancelled and error settlement while retaining interrupted or
reconciling runs. Remove only the thread mapping/digest and aggregator association;
do not evict a graph cache entry shared by other threads. Prove high-volume
terminal traffic leaves the maps bounded, every terminal class releases, parked
interrupts retain binding, and any late terminal re-entry is rejected from
authoritative durable terminal state rather than an immortal in-memory mapping.

### p01-s11-cache-key-compilation-is-not-single-flight-across-threads | medium | resolved pending formal review

Type: concurrency and provider construction. The new lock correctly serializes
compilation for one thread, but locks are keyed only by thread id. Concurrent
first dispatches for different threads with the exact same four-element
`GraphCacheKey` can all miss the cache, compile equivalent graphs concurrently,
and overwrite the same cache entry. This amplifies provider and authoring graph
construction during bursts; the unreserved precompile path above makes the herd
unbounded until that HIGH is corrected.

Ownership: P01.S11. Add a bounded key-scoped compilation future or equivalent
single-flight after each thread's immutable digest binding. Exact-key callers
must share one compile result, failures/cancellation must wake callers and clean
the flight, and distinct keys must remain independent.

### p01-s11-reentry-authority-correction-formal-rereview | high | FAIL

Type: formal implementation review disposition. Exact correction
`3ee6529d2eb533ba7088e871b90169560bbb4880`, parent
`454a3db6d475d77a644129076aed4d43c3e8aa8e`, resolves the prior omitted re-entry,
cache-residency binding, resume checkpoint mutation, clarification replay,
checkpoint projection and thread-association defects. All non-cancel production
graph re-entry constructors use the shared resolver; cancel remains correctly
outside graph compilation. Current-schema checkpoints missing the new evidence
are reconciled only after exact durable current authority resolves, while absent,
corrupt or retired nested authority refuses. Resume uses `Command.update`, and
real clarification message, new-prompt, decline and redrive behavior remains
intact. Closed descriptors and exact expected digest degrade safely at read, and
history/team/SSE retain explicit thread association with no global accessor.

The three open HIGH findings above block P01.S11 and remediation W01.P02.S05:
retired root authority is accepted beside a current freeze, checkpoint lookup can
bypass capacity without a deadline, and terminal thread identity state is
unbounded. The cross-thread exact-key compilation herd is MEDIUM and remains
queued. Independent review passed 115 authority/cache/snapshot/executor/live
clarification tests in 27.82 seconds plus the specialist's 18 focused and two
real clarification controls. The committed 462-control, 121-worker, 80-focused,
60-production, 183-projection and 13-final evidence and static/Core results are
consistent with the corrected positive paths, but cannot establish boundedness
or the missing retired-root boundary. S11 stays open; this review changes no
runtime or plan row.

### p01-s11-bounded-authority-lifecycle-correction | high | resolved pending formal review

Type: implementation review queue disposition. The shared resolver now checks
the complete six-key retired root set before reading the current freeze and
returns only the bounded `retired` reason. Resolver and real database redispatch
controls pair every key with an otherwise exact current selection, prove its
value is neither interpreted nor reflected, and trap any worker contact.

`/dispatch` atomically reserves configured ingest/resume capacity before
dispatch-ID admission or task scheduling. Direct executor entry reserves through
the same seam before preflight, checkpoint or graph-lock work. Preflight and
assignment-binding reads share one configured total checkpoint deadline; all
success, refusal, timeout, exception and cancellation exits release capacity.
Real held-`AsyncSqliteSaver` controls exceed the cap, observe only the configured
number active, receive endpoint 429 before dispatch-ID admission, and prove
timeout and cancellation leave zero capacity and compile-lock state.

Completed, failed and cancelled settlement removes the thread assignment digest,
cache-key association and aggregator metadata without evicting a graph shared by
other threads; interrupted settlement retains it. High-volume and all-terminal
controls drive retained identity to zero, and late dispatch is refused again from
durable failed-checkpoint evidence after in-memory identity release. A ref-counted
exact-`GraphCacheKey` flight now compiles once across different threads sharing a
complete key, while different assignment digests compile concurrently; success,
failure and cancellation clean flight state.

The focused exact-authority, redispatch, cache-identity, endpoint-admission,
executor and state-projection suite passes 145 tests; its new concurrency and
lifecycle subset passes 32 tests. The only warning is the already queued
Starlette `BlockingPortal` alias deprecation. P01.S11 remains open for independent
formal review.

### p01-s11-capacity-release-has-a-thread-id-aba-race | high | resolved pending formal review

Type: concurrency admission and reservation ownership. Endpoint and direct
entry now reserve capacity before checkpoint or compile work, but the reservation
is a plain thread-id set entry and one successful dispatch releases it twice.
`_mark_ingest_done` discards the entry during settlement, then
`handle_reserved_dispatch` unconditionally discards the same thread id again in
its outer `finally`. A new dispatch can reserve the same thread between those two
release sites; the older dispatch's final release then removes the new owner's
permit. Capacity becomes under-counted and a third same-thread or over-capacity
dispatch can be admitted while the second is live.

Independent review reproduced the exact ABA sequence with production reservation
methods and a controlled real Executor task: A reserved and settled, B reserved
while A remained inside its handler, and A's final release changed the active
count from one to zero. The committed tests verify ordinary timeout/cancellation
cleanup but do not interleave a new owner between the two releases.

Ownership: P01.S11. Give each admitted dispatch an opaque reservation token or
generation and release only on matching ownership, or establish one exclusive
release site after all settlement work. A terminal cleanup must never release a
newer dispatch's capacity. Add an orchestrated A-terminal/B-reserve/A-finally
control proving B remains counted and blocks a third same-thread dispatch, plus
completion, failure, timeout, cancellation and endpoint/direct variants.

### p01-s11-bounded-authority-lifecycle-formal-rereview | high | FAIL

Type: formal implementation review disposition. Exact correction
`3f5ef6e7d401506fb9a5ee3fb471162af6e8fe91`, parent
`6c3e6fcbb3cf62b14de06e5de206bcbb2e4616a6`, resolves the four prior findings in
their direct paths. The complete six-key retired root set is checked before the
current freeze and returns a bounded non-reflecting refusal with zero worker
contact. Endpoint and direct ingest/resume entry reserve configured capacity
before checkpoint and graph-lock work, and preflight plus assignment binding
share one total checkpoint-read deadline. Timeout and cancellation clean the
thread/key lock reference counts. Terminal emission precedes thread identity
cleanup, interrupted runs retain it, shared graph cache entries survive, and
high-volume terminal traffic leaves no per-thread binding. Exact four-element
cache keys now single-flight across threads with reference-count cleanup, while
different assignment digests compile independently. No provider/profile default,
translation, migration or legacy execution authority was restored.

The new HIGH ABA finding above means capacity ownership is not yet atomic across
settlement and subsequent dispatch, so P01.S11 and remediation W01.P02.S05 remain
blocked. Independent review passed 139 authority, redispatch, cache, worker,
endpoint and timeout tests in 28.41 seconds and reproduced the race separately.
The committed 145 focused and 585 expanded results, eight known server-profile
environment failures, six OpenAPI checks and static/Core evidence are consistent
with the reviewed positive paths. S11 stays open; this review changes no runtime
or plan row.

### p01-s11-capacity-generation-ownership-correction | high | resolved pending formal review

Type: concurrency admission and reservation ownership. Each admitted ingest or
resume now receives an opaque process-local reservation object with a monotonic
generation. The active map retains that exact object, and cleanup removes a slot
only when object identity still matches. Endpoint duplicate/schedule-error paths,
direct dispatch, terminal settlement, pre-run refusal, timeout and cancellation
all carry or recover the owning token; their outer finalizers may repeat release
safely because a stale token cannot remove a newer generation.

The orchestrated ABA control queues A's release and B's same-thread reservation
on the production lock, proves B acquires a different generation before A's stale
final release, fills the remaining configured slots, and proves a third dispatch
is refused while B remains counted. Existing real endpoint, completion, failure,
held-SQLite timeout and task-cancellation controls exercise every cleanup class.
P01.S11 remains open for independent formal re-review.

### p01-s11-concurrent-duplicate-can-report-a-false-capacity-refusal | medium | resolved pending formal review

Type: idempotency response and worker admission ordering. The worker endpoint
checks dispatch-ID membership, then awaits thread-capacity reservation, then
admits the ID. Concurrent identical ingest or resume requests can both observe
the ID absent. The first reserves, admits and schedules; the second then sees the
same thread's capacity token and returns 429 without rechecking that its exact
dispatch ID is now admitted. The original request still executes once, but an
identical replay or ambiguity reconciliation can receive a false capacity failure
rather than the established idempotent `dispatched` response. The committed
worker duplicate test uses `cancel`, which owns no capacity, so it cannot
exercise this ordering.

Ownership: P01.S11; correction is required before closure. Make the
dispatch-ID and capacity decision one atomic endpoint admission operation or
recheck exact admitted identity before returning 429, without admitting a
different same-thread dispatch. Add concurrent identical ingest and resume
endpoint controls that hold the admission lock, prove one scheduled task, two
successful identical responses and no permit leak; retain 429 for different
same-thread IDs and true process-cap exhaustion.

### p01-s11-capacity-generation-final-formal-rereview | high | FAIL

Type: formal implementation review disposition. Exact correction
`bded79c79ba3437fc9f34bcbf82ab1d8d395797c`, parent
`fdd23ce18b8086e5de206bcbb2e4616a6`, resolves the final review-blocking ABA
race. Each accepted ingest/resume receives one frozen monotonic reservation
object. The active map retains that exact object, release succeeds only on object
identity, and a stale generation cannot remove a newer owner for the same thread.
Endpoint admission passes the token into the scheduled task; direct entry creates
one through the same atomic seam; settlement, refusal, timeout, exception,
cancellation and the outer finalizer can offer repeated cleanup safely. Terminal
identity cleanup still precedes the owning token's release and follows terminal
emission, while interrupted runs preserve identity. The orchestrated A-release,
B-reserve, stale-A-finalizer and third-dispatch control proves B remains counted,
full capacity refuses the third dispatch, and all tokens can be drained.

The full six-key retired sentinel, total checkpoint deadline, bounded terminal
identity lifecycle and exact-key cross-thread compile flight remain intact. No
legacy provider/profile/default, translation, migration, compatibility or
deprecated authority was restored. Independent review passed 139 worker,
endpoint, authority, redispatch and cache tests in 25.41 seconds; the committed
61-executor, 130-worker, 12 OpenAPI/zero-retired and static/Core evidence agrees.
The MEDIUM duplicate-response ordering issue is review-blocking because
same-ID replay is an explicit P01.S11 contract: an accepted duplicate must not
report a false capacity refusal even though execution remains single and bounded.
P01.S11 and remediation W01.P02.S05 remain blocked pending atomic dispatch-ID and
capacity admission plus concurrent ingest/resume replay evidence. This review
changes no runtime or plan row.

### p01-s11-concurrent-duplicate-admission-correction | medium | resolved pending formal review

Type: idempotency response and worker admission ordering. After awaiting the
capacity lock, the endpoint now rechecks the exact dispatch ID before returning
429. An identical request admitted during that wait receives the established
`dispatched` response, while a different ID for the same active thread and true
process capacity exhaustion retain the bounded 429 response. The check does not
release another request's generation token or admit the duplicate again.

Real concurrent endpoint controls hold the production admission lock until two
identical ingest or resume requests are queued, then prove two equal 200 bodies,
one retained ID, one generated capacity owner and no leaked owner. A distinct-ID
same-thread control proves exactly one 200 and one typed 429, and the existing
full-capacity control remains green. P01.S11 remains open for final formal
re-review.

### p01-s11-concurrent-duplicate-final-formal-rereview | low | PASS

Type: formal implementation review disposition. Exact correction
`6db8cd3b384872b8cdb8b5b731fa4495fd4d7bbd`, parent
`c13e5a1feac160c0fc3c9468e0c2bfab54dceac0`, resolves the last review-blocking
same-ID replay ordering defect. The endpoint rechecks the exact dispatch ID after
an awaited capacity refusal. A concurrent identical ingest or resume admitted
during that wait returns the same bounded `dispatched` response without creating
a second reservation, admitting the ID twice or scheduling another task. A
different dispatch ID on the active thread and true process-cap exhaustion still
return the typed 429 response.

Real endpoint controls queue two requests on the production capacity lock and
prove identical ingest and resume each return two equal 200 bodies, retain one
ID, generate one capacity token and drain it. The distinct-ID control returns
exactly one 200 and one 429, and full-capacity admission remains before ID
retention or scheduling. The recheck cannot release or replace the first request's
opaque frozen generation; all settlement, refusal, timeout, cancellation and
stale-finalizer ownership invariants from the preceding correction remain intact.

Independent review passed all 64 dispatch-admission and full Executor tests in
28.54 seconds. The committed 133-worker, 12 OpenAPI/retired-state and static/Core
results agree. The known Starlette `BlockingPortal` alias warning remains in its
existing queue. The six-key retired root sentinel, exact current-schema re-entry,
checkpoint digest/descriptor projection, bounded total checkpoint deadline,
terminal identity cleanup, interrupt retention, exact-key compile flight and
clarification replay remain unchanged. No legacy provider/profile/default,
translation, migration, compatibility or deprecated execution authority was
restored. No CRITICAL, HIGH or review-blocking MEDIUM finding remains. P01.S11
formal implementation review passes and is ready for its separate Core lifecycle
closure; this review changes no runtime or plan row.
