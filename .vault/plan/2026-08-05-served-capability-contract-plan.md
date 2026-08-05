---
tags:
  - '#plan'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_hash: 'sha256:4398a523103a8a501d7085e521dce1aa91342ec1a9bfe6a2f471d66b7fef2c99'
tier: L3
related:
  - '[[2026-08-05-served-capability-contract-canonical-vocabulary-adr]]'
  - '[[2026-08-05-served-capability-contract-research]]'
---

# `served-capability-contract` plan

## Description

Triages every finding in the feature's gateway contract audit through to
closure. The audit is a LIVING record and this plan grows with it: new findings
are triaged into new Steps appended at the next free identifier, and no existing
identifier is ever renumbered or reused. A Step that turns out to be unnecessary
is retired in place rather than removed and backfilled.

Every Step names the audit finding it closes by its stable `F` number. A Step
carrying no `F` number is either a prerequisite the audit implies without
recording (the value capture in `W03.P05`), a decision the vocabulary record
deferred (`W04.P07`), or an end-to-end proof no single finding owns
(`W01.P11.S36`).

**Highest product impact is the delivery path, not the typing.** The product can
AUTHOR - the audit records a real validated proposal in the engine ledger,
confirmed three ways. It cannot DELIVER: zero files were written to the vault
across six live runs. `W01.P11` closes that path and outranks everything else
here. A document that cannot be applied is indistinguishable from one that was
never written.

An earlier framing of this plan attributed the authoring failure to a mis-valued
capability string. That hypothesis is REFUTED (audit F16's correction): the
mechanism is F24, a default deny with no elicitation path wired. F24's own
mechanism detail has since been corrected once more by live protocol
reproduction, so the Step text is authoritative over any earlier description of
it - in particular, the remedy is to wire the elicitation rung with
frame-correlated tool identity and a fail-closed default, NOT to relax a
provider policy.

F41 is causally upstream of this whole Wave and sits in `W05` only because it is
a cross-repository change. The approve and apply verbs existed the entire time;
this repository never called them because they were visible only by reading
another language in another repository. An unserved contract is what let the
delivery path stay broken, so treating F41 as documentation tidy-up would miss
that it CAUSED the highest-ranked phase here.

The governing decision is the canonical-vocabulary record in `related:`. Note
its deliberate scope limit: it governs a served value's DOMAIN and explicitly
does NOT claim the findings where a correctly typed field carries an untrue
value. `W03` executes that record; `W04` handles what it ruled out of scope, and
opens the separate transition decision those findings need. Closing `W03` must
not be read as closing F17, F20, or F22.

**The breaking and additive split, which sequences this plan alongside severity.**
`W02` is additive and unilateral - it only describes behaviour already on the
wire, so it can land at any time. `W05` is breaking: every Step changes what a
served field MEANS or removes it, and the edge contract with the consuming
repository is frozen.

Per owner ruling, cross-repository coordination is the ROUTE for that set, NOT a
reason to park it. A served field that contradicts itself is not made acceptable
by documenting the contradiction, and no Step here may be discharged by writing
around a defect: the product must deliver what it claims, with one canonical
definition per concept. F2, F4, F5, F7 and F35 are therefore not optional and
not deferrable behind documentation. `W05.P10`'s F9 Step remains the one most
likely to be mishandled - it merely executes an already-ruled amendment and
needs no new decision, yet it removes fields the dashboard consumes today, so
"already ruled" must not be read as "safe to land alone". `W03`'s narrowings are
breaking for the same reason and are gated behind the value capture in
`W03.P05`.

**The client guide is an output, not a parallel track.** It is blocked on the
canonicalization rather than on writing effort: written today it would either
document workarounds, which the owner forbade, or describe intent the API does
not deliver. It is therefore the last Step of `W03.P06`, gated by the acceptance
test in Verification.

**Work in flight, represented rather than specified.** Every Step in `W02.P03`
is already dispatched to another agent and is tracked here only so it can be
taken off the board when its owner reports; two of them have since landed as
commits `cbcc841e` and `167310b7`. Do not re-specify or re-execute them.
Separately, the worker and gateway pairing fix landed as commit `00a84258`, and
the six live runs that produced the F24-F38 tranche are complete - neither is
carried as a Step.

## Steps

## Wave `W01` - prove and repair the core authoring path

The product's primary function reports success while delivering nothing (audit F16). Nothing else on this plan matters if a completed document run cannot produce an applyable artifact, so this Wave diagnoses before it fixes and closes both halves: the missing proposal and the silent green that hid it.

### Phase `W01.P01` - diagnose, and stop killing healthy runs

One diagnostic that must precede any provider-policy change, and one watchdog fix that stands on its own evidence. The earlier framing of this Phase rested on a hypothesis the audit has since refuted.

- [x] `W01.P01.S01` - F24 diagnostic - ANSWERED. The capability field has exactly ONE consumer, a served-response field that gates nothing at runtime, while the runtime submitter gate is an independent read of the same topology key. The two are parallel projections of one variable, which is why the correlation looked perfect and was a correlation between two symptoms. The capability derivation is therefore ORTHOGONAL to F16 and must never be credited with closing it. Remaining work moved to S34; `src/vaultspec_a2a/providers/_codex_config_home.py`.
- [x] `W01.P01.S02` - F25 DONE in commit 088bd603 - the ingest-stall bound is now derived from the compiled graph rather than a flat global, so a run's own declared step timeout is honoured and presets without one keep the previous floor; `src/vaultspec_a2a/streaming/ingest.py`.

### Phase `W01.P02` - close the false green

Restore the missing artifact and remove the silent success that concealed it; either alone leaves the next failure looking identical.

- [ ] `W01.P02.S03` - F16 - make the document editor submit its authored output as an engine proposal so the review lane has something to apply; `src/vaultspec_a2a/authoring/submitter.py`.
- [ ] `W01.P02.S04` - F16 safety half - refuse to report a document-authoring run completed with empty degradation when it produced no artifact, the silent green being a separate defect from the missing proposal; `src/vaultspec_a2a/control/run_start_policy.py`.
- [ ] `W01.P02.S05` - F21 - gate authored document content on structural validity before submission so the review lane never receives a document with duplicated sections; `src/vaultspec_a2a/authoring/submitter.py`.
- [ ] `W01.P02.S06` - F29 PARTIALLY RETRACTED - the half claiming no route here serves the document body falls with F57, since the dashboard reads proposal detail direct from the engine. What SURVIVES is an engine content gap: the proposal fetch returned an empty review-documents array and the diff and preview routes 404. VERIFY THAT AGAINST THE DASHBOARD'S LIVE CLIENT before acting - it may be a dev-config artifact - and verify through the CONSUMER, not the declaration; `src/vaultspec_a2a/api/routes/gateway.py`.

### Phase `W01.P11` - restore the delivery path

A produced document has no route to disk. This is the highest product impact on the plan - a document that cannot be applied is indistinguishable from one never written.

- [ ] `W01.P11.S34` - F24 and F42 - wire the MCP server elicitation rung, recovering tool identity by correlating with the tool-call notification that arrives immediately before on the same thread and turn, because the elicitation payload carries no tool-name field and parsing its prose message is forbidden. FAIL CLOSED to decline on any correlation miss and log it, or the remedy becomes a latent blanket approve that the exact-name allowlist rulings forbid. Do NOT rely on the generated automatic-approval config key - F42 proves it is inert on these server blocks; `src/vaultspec_a2a/providers/_acp_rpc_handlers.py`.
- [x] `W01.P11.S35` - F30 DONE in commit cb7f856e - approval forwarding wired through the engine decision and apply verbs, proven by a real document reaching disk. What it added is a SECOND consumer of those verbs, a programmatic path with no human at a browser. The human path already worked directly against the engine, so the earlier claim that no frontend could reach them was F57, now retracted; `src/vaultspec_a2a/authoring/session.py`.
- [ ] `W01.P11.S36` - Prove the whole delivery path end to end with a live run - instruction in, proposal created, body served to a reviewer, approval forwarded, file on disk - which no run has yet achieved. The retry and idempotency half must drive a REAL ENGINE, because the engine is what dedupes on the idempotency key: a same-process assertion proves only that the key is stable, never that the document was applied once. That distinction is a drift guard versus a real proof, and only the second closes this Step; `src/vaultspec_a2a/acceptance/tests`.
- [ ] `W01.P11.S48` - F30 deferred half - report the engine's apply outcome honestly on the permission-respond response, since Option A wires the engine calls without touching the response shape and leaves the success path reporting accepted_not_applied, which is UNDERSTATED rather than wrong. Blocked on the schema module being released, and should land together with the document-body route which is blocked on the same file for a different reason rather than contending for it twice. Do NOT encode new outcomes into the action-status string - it is an undeclared vocabulary clients branch on, and growing it mid-capture would hand the containment proof a moving target; `src/vaultspec_a2a/api/schemas/gateway.py`.
- [ ] `W01.P11.S54` - F57 RETRACTED - the premise was wrong and this Step has no work. The dashboard reaches the engine review and apply verbs DIRECTLY, so the human delivery path was complete before this campaign began. Retired in place rather than removed so the wrong premise stays visible. Under V9 a proxy here would have been a mirror of another authority's surface; `src/vaultspec_a2a/api/routes/gateway.py`.

## Wave `W02` - additive contract corrections

Findings whose remedy only ADDS description of behaviour that already exists on the wire. These are unilateral on this side of the frozen edge and need no cross-repository coordination, so they may land in any order and in parallel with every other Wave.

### Phase `W02.P03` - corrections in flight

Work already dispatched to other agents, represented here for tracking only. Do not re-specify or re-execute; close each Step when its owner reports.

- [ ] `W02.P03.S07` - F1 correction half IN FLIGHT with agent contract-audit - correct the stale streaming route and the false claim that legacy api routes remain; `docs/a2a-edge-conformance-verb-mapping.md`.
- [ ] `W02.P03.S08` - F14 IN FLIGHT with agent contract-audit - correct the module docstring that claims three topology types where four are dispatched; `src/vaultspec_a2a/graph/compiler.py`.
- [ ] `W02.P03.S09` - F3 IN FLIGHT with agent contract-audit - declare an HTTPBearer security scheme, apply it to the versioned and admin surfaces, drop the hand-rolled authorization parameter and declare 401 responses; `src/vaultspec_a2a/api/app.py`.
- [ ] `W02.P03.S10` - F1 guide half IN FLIGHT with agent contract-audit - publish a client-facing API guide covering auth, discovery and the run lifecycle; `docs/index.rst`.

### Phase `W02.P04` - residual additive findings

Mechanical contract corrections with no owner yet, each independent of the others.

- [x] `W02.P04.S12` - F11 DONE in commit 1022ba08 - the five underscore-prefixed snapshot models were renamed and exported, the parity test updated, and zero underscore-prefixed schemas remain in the published contract, verified against the committed artifact; `src/vaultspec_a2a/api/schemas/snapshots.py`.
- [ ] `W02.P04.S13` - F13 - serve topology structure on the preset so a frontend can render what a preset will do rather than only its name; `src/vaultspec_a2a/api/routes/gateway.py`.
- [ ] `W02.P04.S14` - F15 registry half ONLY - the logging halves landed in 2b978a35. Populate log_path from the boot CALLER, which is where the null originates rather than in the registry, and reap the duplicate port-18110 records. Deliberately deferred as a separate pass because reaping is destructive against a registry two agents are live against, so it needs lifecycle quiet; `src/vaultspec_a2a/lifecycle`.
- [ ] `W02.P04.S15` - F15 unowned gap RULED as the failure-observability record - execute its five clauses. The operations documentation half returns to its owner only AFTER this lands, and may state the guarantee only for paths that satisfy it, since 2b978a35 made the guarantee truer without establishing it; `src/vaultspec_a2a/lifecycle`.
- [x] `W02.P04.S16` - Document the OpenAPI artifact regeneration command, which exists only inside the test file that enforces it; `docs/development.rst`.
- [ ] `W02.P04.S37` - F26 - split the engine serve command without POSIX semantics on Windows and propagate the launch error instead of collapsing it into a port-allocation message; `src/vaultspec_a2a/lifecycle/engine_serve.py`.
- [ ] `W02.P04.S38` - F27 - honour the explicit data seat as the vault root, or refuse a seat that resolves into an enclosing git worktree, since the guard is currently defeated by exactly the case it exists for; `src/vaultspec_a2a/lifecycle/engine_serve.py`.
- [ ] `W02.P04.S39` - F34 - raise or split the run-start forward budget and warm the provider catalog before forwarding, so a cold catalog stops surfacing as a transport connect error with no run and no log line; `src/vaultspec_a2a/api/routes/gateway.py`.
- [ ] `W02.P04.S40` - F36 - demote the health poll and the unreachable-collector telemetry export, and log authoring tool calls and rejections with the run identifier, since the logs cannot currently answer what a run did; `src/vaultspec_a2a/lifecycle`.
- [ ] `W02.P04.S51` - F51 latent - route execution_readiness assignments through the same coercion helper repair_status already uses, since both columns share a type but only one is gated on write, and serving the field as an enumeration turns a silently accepted bad value into a 500 on run-status days later. Blocked on the owning repository module being released; `src/vaultspec_a2a/database/thread_repository.py`.
- [ ] `W02.P04.S53` - F56 - add a mechanical module-size gate, since the mandate is currently enforced by nobody and two modules already exceed it. A mandate depending on someone remembering is the same shape as a terminal state nothing is obliged to advance; `dev/toolchain.py`.
- [ ] `W02.P04.S55` - F58 - make a stale-candidate skip in engine discovery say so, naming the candidate and why it was rejected, since a correct refusal that cannot explain itself cost two agents real time. This is the failure-observability record's swallowed-condition clause applied to discovery; `src/vaultspec_a2a/authoring/discovery.py`.

## Wave `W03` - canonical vocabulary

Executes the canonical-vocabulary decision across the served surface: one declaration per concept, emit sites deriving rather than restating, and every narrowing subset-proved against live payloads before it lands. Depends on W01 only for the capability field, whose remedy branches on W01's gating verification.

### Phase `W03.P05` - prove the value sets

Every narrowing is a breaking change unless the live value set is provably contained in the proposed enumeration; the capture comes first and gates the rest of the Wave.

- [ ] `W03.P05.S17` - Capture the value set each candidate vocabulary actually serves from live payloads and prove containment in its proposed enumeration, which gates every narrowing in this Wave; `src/vaultspec_a2a/api/schemas/gateway.py`.

### Phase `W03.P06` - declare and derive

Give each served vocabulary one owning declaration and make every emit site derive from it.

- [ ] `W03.P06.S18` - F23 shape one - serve the TopologyType enumeration that already exists in code instead of a bare string, and reconcile provider_id with the typed Provider enumeration served beside it; `src/vaultspec_a2a/api/schemas/gateway.py`.
- [ ] `W03.P06.S19` - F23 shape two - declare owning enumerations for the vocabularies that have none, covering origin, repair_status, execution_readiness, provider_condition, worker_status, semantic_status, semantic_phase, replay_status and the degraded_reasons members; `src/vaultspec_a2a/api/schemas/gateway.py`.
- [ ] `W03.P06.S20` - F7 - correct the document editor authoring_capability and populate supported_capabilities across presets, gated on the S01 verification because the remedy branches on it; `src/vaultspec_a2a/team/team_config.py`.
- [ ] `W03.P06.S21` - Enforce import-from-owner for served vocabularies so no surface redeclares or re-exports one, keeping the two distinct AdmissionState concepts separate rather than merged; `src/vaultspec_a2a/api/schemas/gateway.py`.
- [ ] `W03.P06.S43` - F37 - declare and serve a summarization capability or drop the product claim, since no served preset advertises it and the nearest path is the false green of F24; `src/vaultspec_a2a/team/team_config.py`.
- [ ] `W03.P06.S47` - Write the client-facing API guide as the OUTPUT of this Wave rather than a parallel track, using the wireframe acceptance gate as its completion test - the guide cannot be written honestly until the served semantics are canonical; `docs/index.rst`.
- [ ] `W03.P06.S52` - F53 and F54 - derive the role capability and assignment-source fields from their existing owning enumerations and remove the restated default literal, both being shape-one items F23 did not list. Their omission is why F23's inventory is a starting point rather than a closed set; `src/vaultspec_a2a/api/schemas/gateway.py`.

## Wave `W04` - truthful run projection and the live interaction surface

Findings where a correctly typed field still carries an untrue value, plus the streaming and interaction surface the audit could not exercise live. These are state and transition defects that the vocabulary decision explicitly rules OUT of scope, so this Wave opens the transition contract they need before fixing them piecemeal.

### Phase `W04.P07` - rule the transition contract

The vocabulary decision governs a value's domain, never whether a written value is true. These findings need a decision on terminal states and the obligation to reach them.

- [ ] `W04.P07.S22` - Transition-contract decision AUTHORED as the state-truthfulness record - execute its five clauses across the state vocabularies. TWO findings have already landed on it since it was written: the terminal-partition question in F45, and F52's semantic_status which has no producer at all and is permanently its default. F52 is T2's obliged-writer problem and is NOT closed by typing it; `src/vaultspec_a2a/thread/enums.py`.

### Phase `W04.P08` - repair the run projection

Fix the projections that serve untrue values on completed and failed runs.

- [ ] `W04.P08.S23` - F17 two breaks not one, and the file attribution was wrong - the live half drops terminal status because the stream transformer reads only chunk content and never inspects tool_call_chunks, while the snapshot half infers COMPLETED only when a matching ToolMessage exists, which provider-internal actions never produce, so every call falls to PENDING permanently. COMPLETION CRITERION - a REST read of a SETTLED run must show terminal status with locations and content populated where the provider supplied them, because the aggregator state is pruned at settle and fixing the live half alone would leave the audited symptom unchanged. Also give the emitters a way to carry status and locations, which the event type already declares; `src/vaultspec_a2a/streaming/transformer.py, src/vaultspec_a2a/streaming/emitters.py, src/vaultspec_a2a/control/snapshot.py`.
- [ ] `W04.P08.S24` - F18 - scope the agents projection to the run topology so a one-worker pipeline stops reporting the eight-agent roster of a different topology, noting that the F8 team-status half is retracted as non-reproducing and is not part of this Step; `src/vaultspec_a2a/api/routes/gateway.py`.
- [ ] `W04.P08.S25` - F20 - define what reconciling means, how long it may persist and how a run leaves it, then provide the recovery path a stranded run currently lacks; `src/vaultspec_a2a/control/run_discovery_service.py`.
- [ ] `W04.P08.S26` - F22 - stop serving healthy on every structured health field of a failed run, so a frontend gating on machine-readable fields is not forced to parse prose; `src/vaultspec_a2a/api/routes/gateway.py`.
- [ ] `W04.P08.S41` - F31 - fold the authoring session reference into thread state on the submitter path as well as the bridge path, so a run discloses the session the engine recorded for it; `src/vaultspec_a2a/authoring/submitter.py`.
- [ ] `W04.P08.S42` - F32 - preserve the recorded approval outcome across a terminal transition, so pruning a pending request stops erasing the decision a human made; `src/vaultspec_a2a/control/thread_state_service.py`.
- [ ] `W04.P08.S50` - F47 LIVE - the harness-readiness verdict is computed for the document editor on every run start and then discarded, so byte-identical harness incompleteness refuses a research_adr run and admits a doc-editor one. Fix the root cause rather than the branch: the topology-only predicate stands in for a question about roles and declared surfaces, so a point fix in the eligibility branch leaves the misclassification everywhere else. The probe helper's docstring also describes behaviour its code does not implement; `src/vaultspec_a2a/control/run_start_policy.py`.
- [ ] `W04.P08.S56` - F61 - consult the checkpoint before resolving an abandoned run to failed, so a graph that already reached its end is recognised rather than timed out. This is the only FALSE RED in the audit and it belongs against the same non-contradiction clause as the false greens, which does not care which way a contradiction points; `src/vaultspec_a2a/control/run_discovery_service.py`.

### Phase `W04.P09` - drive and specify the live surface

The audit could not exercise this surface. It must be driven live before it can be documented honestly, and it carries a known defect to fix while there.

- [ ] `W04.P09.S27` - Drive the streaming and interaction surface live and specify it - event taxonomy, frame schema, reconnect protocol and terminal semantics - across the stream, history, messages and both respond routes, and fix F19 where last_sequence is zero on a completed run; `src/vaultspec_a2a/api/routes/gateway.py`.

## Wave `W05` - breaking semantics requiring dashboard coordination

Findings that change what a served field MEANS, or remove it. The edge contract is frozen, so every Step here lands in lockstep with the consuming repository and none may be taken unilaterally - including the one that merely executes an already-ruled amendment.

### Phase `W05.P10` - coordinate the breaking set

Each Step changes what a served field means and requires agreement with the consuming repository before it lands.

- [ ] `W05.P10.S28` - F2 BREAKING - either retire the eligible flag and profiles from the preset listing consistently with the catalog amendment, or redefine eligible as runnable-given-a-valid-selection and scope each reason to the preset it applies to; `src/vaultspec_a2a/api/schemas/gateway.py`.
- [ ] `W05.P10.S29` - F4 BREAKING - separate product presets from certification fixtures on the served surface by a declared classification rather than a name prefix, so a frontend can request product-only; `src/vaultspec_a2a/api/routes/gateway.py`.
- [ ] `W05.P10.S30` - F5 BREAKING - reconcile eligible_providers with the catalog admission predicate so the two discovery surfaces cannot disagree about which providers are usable; `src/vaultspec_a2a/api/routes/gateway.py`.
- [ ] `W05.P10.S31` - F6 BREAKING - rule whether an unreachable authoring backend degrades the service, then define the readiness vocabulary and stop serving a worker check that reports ok beside a disconnected worker; `src/vaultspec_a2a/api/routes/gateway.py`.
- [ ] `W05.P10.S32` - F9 BREAKING but ALREADY RULED - remove the empty roles and assignments from run-status per the catalog amendment, which needs no new decision yet still removes fields the dashboard consumes today; `src/vaultspec_a2a/api/schemas/gateway.py`.
- [ ] `W05.P10.S33` - F12 BREAKING - make workspace_root consistent between the two sibling discovery routes, either by requiring it or by disclosing that no workspace resolved; `src/vaultspec_a2a/api/routes/gateway.py`.
- [ ] `W05.P10.S44` - F35 BREAKING - wire the acceptance gate to a real signal or remove the term, and make eligible mean the same thing on the preset listing and the run-start response instead of permanently false on one and true on the other; `src/vaultspec_a2a/api/routes/gateway.py`.
- [ ] `W05.P10.S45` - F33 BREAKING cross-repo - reconcile the engine's run metadata shape with a2a's model and fail loudly rather than reporting it absent, since workspace provenance is currently dropped silently for proxy-started runs; `src/vaultspec_a2a/api/schemas/gateway.py`.
- [ ] `W05.P10.S46` - F28 cross-repo - publish an engine schema, declare the conditional requirement of feature_tag in a2a, align workspace_root across the two surfaces and return proxy errors with a non-200 status; `src/vaultspec_a2a/api/schemas/gateway.py`.
- [ ] `W05.P10.S11` - F10 BREAKING not additive - declare the discriminator on the run-start response union, which requires adding a stage const to RunStartResponse since the other three members already carry one and it alone does not, so it touches a payload the dashboard parses. Cheap once sequenced - one const field plus a discriminator block, with three members already establishing the pattern; `src/vaultspec_a2a/api/schemas/gateway.py`.
- [ ] `W05.P10.S49` - F41 cross-repo and causally upstream of W01.P11 - serve the engine's existing route-fixture table as a machine-readable description at a stable path and stop returning application HTML from the schema path, preserving the per-route named-refusal list which is the valuable part. This is unserved work rather than missing work, and it is the demonstrated cause of F30; `src/vaultspec_a2a/api/schemas/gateway.py`.
- [ ] `W05.P10.S57` - F62 BREAKING and it BLOCKS THE CAPABILITY RE-KEY - a deliberately-failing certification fixture declares real document-authoring roles and is served as an ordinary preset because the mock predicate is a name prefix. Re-keying capabilities off roles would make it advertise three document kinds it is built to fail. The declared classification and the re-key MUST land together or the remedy manufactures the defect it removes; `src/vaultspec_a2a/team/team_config.py`.

## Parallelization

Waves are sequenced by default, but this plan deliberately relaxes that in one
direction: `W02` is additive and unilateral and may run concurrently with every
other Wave, including its own in-flight Phase. `W01` gates nothing structurally
but should lead on priority - it is the only Wave addressing a defect that
makes the product report success while delivering nothing.

Real dependencies, none negotiable. Every narrowing in `W03.P06` is gated on
`W03.P05`, because a narrowing without a proven value set is an unverified
breaking change. The guide Step at the end of `W03.P06` is gated on the whole of
`W03` plus the group-B Steps in `W05`, because those are what make it writable.
`W01.P11`'s end-to-end proof is gated on the two repair Steps above it. And
`W01.P01.S01` gates `W01.P11.S34`: dump the generated provider config before
changing provider policy.

The capability Step in `W03.P06` is NO LONGER gated on `W01.P01.S01`. That
dependency existed only under the refuted gating hypothesis; correcting the
capability value is now an ordinary declaration fix and can proceed immediately.

`W05` is internally parallel - its Steps touch different fields - but each
requires its own agreement with the consuming repository, so throughput is
bounded by coordination rather than by engineering. That bound is a scheduling
fact, not permission to defer: per owner ruling the coordination is the route.

## Verification

The plan is complete when every Step is closed AND every finding in the feature
audit is either closed by a Step or explicitly owned elsewhere with that
ownership recorded in the audit. F38 is closed by classification - it records
the admission rule working as designed and must not be "fixed".

**The acceptance gate for the canonicalization is the client-guide wireframe,
not the type declarations.** The guide enumerates what a client author must be
able to learn from the served contract ALONE. If any entry still needs a caveat
once the Steps land, the canonicalization is not done. This turns each
unlearnable entry into a checkable line rather than an assertion that the enums
are typed now. The gate decomposes into three groups that must NOT be
conflated - the vocabulary work closes only the first.

Group A, closed by the vocabulary Steps in `W03`: which presets are real product
versus scaffolding; whether a provider can actually be selected; what a preset
will do; what a preset can produce; and which run-start response shape came
back. The provider entry must preserve the two distinct admission concepts
rather than merging them.

Group B, NOT closed by typing and requiring the `W05` Steps: whether a preset is
runnable; why a preset cannot run, which is a misattribution defect invisible to
a domain rule; which providers are usable, which is a derivation defect rather
than a domain one; and what a run committed to, which is an already-ruled
decision incompletely applied. Marking group A closed while group B stands would
report the gate passed while a client author is still blocked.

Group C, closed only by driving the surface live: how to receive live progress -
event names, frame envelope, replay and resume, terminal semantics - and the
WebSocket surface, which no schema can carry and which currently has no owner on
this plan beyond the live-driving Step.

Two entries are already closed and are REGRESSION GUARDS rather than open work:
authentication is declared with a bearer scheme across the gated operations, and
the contract surfaces are published with a documented regeneration path. The
artifact-equality test holds both.

Per-Step, closure requires the finding's remedy verified against the surface
that carried the defect - for a served-contract finding, a live payload showing
the corrected value, not a passing unit test alone. Four Steps carry a stricter
bar. `W03.P05` closes only on a captured value set with proven containment.
`W04.P09` closes only on a live subscription; "not yet verified" is not a
permitted resting state for that surface, which is in flight and being
engineered through rather than caveated around. `W01.P11.S36` closes only on a
file existing on disk that a run produced through the documented flow, which no
run has yet achieved. And the guide Step closes only when the wireframe above
has no caveated entry left.

No Step in `W05`, and no narrowing in `W03.P06`, may be marked closed on the
strength of a change landed in this repository alone.
