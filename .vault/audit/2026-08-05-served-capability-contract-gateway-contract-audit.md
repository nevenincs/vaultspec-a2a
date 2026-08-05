---
tags:
  - '#audit'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:9ace72e5774d118baf365a0f6bb7cb7f38fd3ff39d672ab4c33442e44d43322b'
related:
  - "[[2026-08-05-served-capability-contract-research]]"
---

# `served-capability-contract` audit: `what the served gateway contract tells a frontend versus what is true`

## Scope

This is a LIVING audit of the gateway's served contract, judged from the position
of a frontend author who holds only the served API and the published
documentation. It is appended to continuously; settled entries are never
rewritten.

**Method.** Live read-only interrogation of the gateway on `127.0.0.1:18100`
(pid 63700, registry name `gateway-dev-mantest`, dev band), the committed
`openapi.json`, the published docs, and the `.vault/adr/` corpus. GETs and
validation-rejected POSTs only; no processes started or stopped, no runs started
by the auditor, no repository files modified. Findings F16 onward are read-only
observations of runs executed by a separate agent after the engine came up
(`engine-dev-mantest` on 18760, at which point `authoring_backend_reachable`
became `true`).

**Coverage.** All 19 served paths enumerated from the live spec; live probes of
`/health`, `/v1/service`, `/v1/presets` (with and without `workspace_root`),
`/v1/provider-catalog`, `/v1/runs`, `/v1/runs/{id}`, `/v1/runs/{id}/history`,
`/v1/team/status`, six `/.well-known/` and agent-card candidates, four auth
failure modes, six validation-rejected `POST /v1/runs` shapes, the structured
log, and the process registry.

**Deliberate non-coverage - read this before quoting anything about streaming.**
The SSE stream, `/v1/runs/{id}/messages`, and both `respond` routes were NOT
exercised live, because a run belonging to another agent was in flight and
driving it risked disturbing work in progress. F1's streaming finding therefore
rests on the served spec and the docs, NOT on a live subscription. The defect F1
records is that the surface is undocumented, not that it misbehaves - but the
live half is unverified and must be labelled as such wherever it is cited. This
matters more than a normal coverage gap: live progress is the primary
interaction of an orchestration product, and it is the surface this audit has
the least direct evidence about. `/v1/runs/{id}/history` was subsequently read
live for the F16-F22 tranche, so that route alone has since been exercised.

**Finding numbering and how to append.** Findings carry stable identifiers `F1`,
`F2`, ... assigned in order of discovery, never renumbered and never reused. The
ADR, the plan, and every downstream Step reference these identifiers, so
renumbering would orphan the trail. A new finding takes the next free number
after the highest already present and is appended to the Findings section in
numeric order. Severity is recorded per finding and is not adjusted by later
tranches; a superseded or retracted finding keeps its number and says so in
place. The current highest identifier is **F43**. F40 is RESERVED - assigned to an
agent and not yet delivered - and is held rather than reused.

**Renumbering applied to the third tranche, recorded so the source remains
traceable.** The live-run tranche from the `product-proof` session was authored
numbered F23 through F37, which collided at one position: F23 was already taken
by this document's typed-vocabulary finding, committed and cited by the
canonical-vocabulary decision record. Committed identifiers are never
renumbered, so the incoming tranche was offset by one and preserved in its
original order. The remap, from source number to number in this document: 23 to
24, 24 to 25, 25 to 26, 26 to 27, 27 to 28, 28 to 29, 29 to 30, 30 to 31, 31 to
32, 32 to 33, 33 to 34, 34 to 35, 35 to 36, 36 to 37, 37 to 38. No incoming
finding was dropped or merged; each is a distinct observation rather than a
rediscovery, and where one bears on an earlier finding that relationship is
stated in both entries.

**Tranche provenance.** F1-F15 are the contract audit of the served surface,
before the engine was reachable. F16-F22 are read-only observations of the first
live runs, after the engine came up. F23 is the served-vocabulary measurement
taken for the canonical-vocabulary decision. F24-F38 are the driven-run tranche,
from a session that stood the engine up itself and executed six real runs. All
are 2026-08-05; the engine's arrival partway through is why several F1-F15
observations about an unreachable authoring backend read differently now, and
why the later tranches can settle questions the earlier ones could only pose.

**Corrections carried by later tranches.** Three earlier entries have been
corrected in place rather than rewritten: F16's causal hypothesis is refuted by
F24, F22's stall premise is superseded by F25, and F8 is retracted as
non-reproducing. Each correction is marked inside the entry it affects, and the
original claim is retained beside it. A reader citing any of those three must
read its correction.

F25 has itself been corrected twice, and the sequence is worth stating because
it is instructive. The entry first claimed the watchdog reported something FALSE
about the system's own state, on the strength of per-minute event counts. It
then credited, as the surviving part, an inferred hedge that the watchdog
"counts a different channel". A code trace refutes both: the watchdog wraps the
same `astream_events()` iterator the worker's own transformer consumes, so there
is one channel, and the counts cited against it are aggregates over a window
that cannot rule out a gap inside it. The real defect is a threshold mismatch,
which is worse than a false signal rather than milder.

F24 has also been corrected once, on the same pattern: its mechanism was
diagnosed from a binary string grep, the string was present, and presence read
as confirmation. It was present for an unrelated feature. The correction came
from driving the actual protocol in both directions.

The method lesson is the durable part. A refutation assembled from a DERIVED
AGGREGATE of the same signal is not a refutation - it changes the resolution,
not the subject. Both wrong versions of this entry were argued from throughput
totals; only reading the code settled it. This document's own T5-shaped rule
applies to its findings as much as to the fields they describe: state what was
observed, at the resolution it was observed.

**A METHOD RULE THIS AUDIT EARNED THE HARD WAY, and which anyone appending
should read first.** Two findings in this document were mis-stated because A
SEARCH HIT WAS READ AS PROOF - a string present in a binary for an unrelated
feature (F24), and per-minute event counts standing in for a per-event gap
(F25). Both survived review, both were confidently argued, and both were
corrected only by someone tracing the actual code or driving the actual
protocol. A grep proves a string exists. It does not prove what produced it, what
consumes it, or that it is on the path under investigation. Where a finding's
mechanism rests on a search result alone, it is a HYPOTHESIS and must be labelled
one; only execution or a code trace promotes it.

This is the same lesson as the audit's own through-line - a surface that looks
right over a mechanism that is not - applied to the audit's METHOD rather than
to the product. The document is not exempt from the failure it documents.

## Findings

### F1-no-client-facing-api-documentation | critical | 13 of 19 served paths appear in no document, and the one streaming doc points at a route that 404s

Undocumented paths: `/v1/provider-catalog`, `/v1/runs/{id}/stream`,
`/v1/runs/{id}/history`, `/v1/runs/{id}/messages`, `/v1/runs/{id}/archive`,
`DELETE /v1/runs/{id}`, both `respond` routes, `/v1/team/status`, `/health`,
`/admin/shutdown`, and the `/internal/*` set.
`docs/a2a-edge-conformance-verb-mapping.md:20-23` tells a client author the
progress stream is `GET /api/threads/{id}/stream`; no `/api/*` path is served,
and the real route is `GET /v1/runs/{run_id}/stream`. The same file at L41-43
claims the internal `/api/threads*`, `/api/health`, and internal preset routes
"remain temporarily for internal callers and backward compatibility" - they do
not. `docs/` contains zero occurrences of "openapi"; `README.md` contains zero
occurrences of `Bearer`, `/v1/`, `service.token`, or `workspace_root`.
CONSEQUENCE: a frontend author wires a stream URL that 404s, and on finding the
real one gets no event names, no frame envelope, no `Last-Event-ID` or replay
parameter, and no heartbeat or terminal-event semantics - none of which OpenAPI
can carry. The WebSocket edge advertised at `README.md:17-18` has no documented
URL or message schema at all. CLASSIFICATION: genuine defect. The authorizing
records `2026-04-05-contract-validation-adr` and
`2026-02-26-frontend-backend-contract-adr` are both superseded and their
continuous-integration gate deleted; `2026-07-14-a2a-edge-conformance-adr`
L385-388 explicitly predicted this outcome and the replacement coverage it
demanded was never filled. REMEDY: publish a client guide; point `README.md` and
`docs/index.rst` at `/docs` plus `/openapi.json` as THE contract; document the
event taxonomy, frame schema, and `last_sequence` reconnect protocol; correct or
delete the stale `/api/*` claims. The correction is independent of the guide and
must not wait for it.

### F2-eligible-is-structurally-always-false | critical | every preset is ineligible, and the reasons are misattributed to unrelated presets

All 20 presets return `profiles[0].eligible: false`, and every one - including
all 8 `mock-*` and all 5 `deterministic-*` - carries the identical
`unavailable_reasons` pair "authoring engine is not reachable" and "production
acceptance gate for the research-to-ADR capability has not passed".
`mock-success-single` is a coding fixture with no relation to research-to-ADR.
Meanwhile `POST /v1/runs` accepts runs and a live run reports `status: running`.
CONSEQUENCE: a user interface gating on `eligible` offers nothing; one gating on
`loadable` offers everything, including 16 unrunnable fixtures. A "why can't I
run this?" tooltip tells the user a mock coding preset is blocked by a
research-to-ADR acceptance gate - actively misleading, not merely unhelpful.
CLASSIFICATION: genuine defect, a stranded field.
`2026-08-02-provider-model-catalog-adr` L95-100 retired provider policy from
presets and its 2026-08-03 amendment L153-158 removed the profile pair from
START responses but left it on READ surfaces. `eligible` is defined only in the
superseded `2026-07-15-model-profiles-adr` L48 and survives in code on
`ProfileSummary` (`src/vaultspec_a2a/api/schemas/gateway.py:919`), attached to
the exact concept the 2026-08-02 record retired. No accepted record states what
it means under the frozen-assignment contract. REMEDY: either retire
`eligible`/`profiles` from `/v1/presets` consistently with the amendment, or
redefine it as "runnable given a valid selection" and scope each reason to the
preset it applies to. Breaking wire change.

### F3-openapi-declares-no-auth | high | the published contract models authentication as an optional string header and documents 401 nowhere

`components.securitySchemes` is null, top-level `security` is null, and
per-operation `security` is null on all 21 operations. `authorization` is
modeled as an OPTIONAL plain-string header parameter on every route. No route
documents `401`, though `DELETE /v1/runs/{run_id}` documents `404/409/503`,
proving the others could. Live behaviour verified across four auth failure
modes: absent, malformed, and wrong-scheme all return 401 with
`WWW-Authenticate: Bearer` and `{"detail":"Invalid gateway service token"}`; a
valid token returns 200. CONSEQUENCE: a generated client has no auth affordance
- no `setBearerToken`, just an optional string the caller must know to populate.
Swagger UI at the public `/docs` has no Authorize button, so every "Try it out"
returns 401 with no hint why. Auth is documented in prose at
`docs/operations.rst:64-77`, but in an operator chapter the README never links,
and the concrete path `~/.vaultspec-a2a/service.token` appears nowhere - only
the bare filename. CLASSIFICATION: genuine defect. No record governs the OpenAPI
document, security schemes, or generated-client support; the two that once did
are superseded and their generator `scripts/export_openapi.py` was deleted.
REMEDY: add an `HTTPBearer` security scheme, apply it to `/v1` and `/admin`,
drop the hand-rolled `authorization` parameter, declare `401` responses.
Additive - it describes auth that already exists on the wire.

### F4-fixtures-served-without-a-filter | high | 16 of 20 presets are test scaffolding, `is_mock` does not identify them, and no filter parameter exists

Product presets number 4: `vaultspec-adr-research`,
`vaultspec-adr-research-clarify`, `vaultspec-doc-editor`,
`vaultspec-solo-coder`. Non-product number 16: five `deterministic-*`, eight
`mock-*`, `provider-condition-probe`, `vaultspec-adr-research-deterministic`,
and `vaultspec-adr-research-mock`. `is_mock` is true for only the eight
`mock-*`, so `vaultspec-adr-research-mock` reports `is_mock: false, origin:
bundled` - a preset named `-mock` that the mock flag denies. `/v1/presets`
accepts no filter parameter; its only declared parameter is the optional
`workspace_root`. CONSEQUENCE: filtering on `is_mock` still leaves eight
fixtures in the product picker, one of them named `-mock`. No served field
separates product from scaffolding - `origin` reports `bundled` for both.
CLASSIFICATION: undocumented accident. No record rules that mock presets belong
in the served list or that filtering is the client's job; `is_mock` rests on a
code comment alone (`src/vaultspec_a2a/api/schemas/gateway.py:942`).
`2026-03-31-decoupled-mockllm-adr` is status PROPOSED, never accepted, and
scoped to the mock transport rather than served presets;
`2026-07-18-desktop-product-profile-adr` excludes mocks from the WHEEL, meaning
packaging, not the API. REMEDY: add a fixture-exclusion parameter defaulting to
product-only, or replace the boolean with an accurate `origin` enum of product,
fixture, and probe.

### F5-provider-surfaces-disagree | high | `/v1/service` and `/v1/provider-catalog` disagree on which providers are usable

`/v1/service` reports `provider_eligibility: eligible` and `eligible_providers:
[claude, codex, kimi]`. `/v1/provider-catalog` at the same instant reports
claude with `admission: not_admitted`, `selectable: false`, a reason stating the
lane "has no exact completed-turn proof; evidence from another execution mode is
not inherited", and `catalog.state.status: unavailable` with `models: []`. Only
codex reports `selectable: true`. CONSEQUENCE: a provider picker built from
`/v1/service` offers three providers, two of which cannot be selected. `POST
/v1/runs` requires a selection naming a real catalog revision and entry
identifier, which the unadmitted lanes cannot supply. Two plausible readings of
the same fact, one of which fails silently at run start. CLASSIFICATION:
documented decision with an undocumented consequence. Completed-turn admission
is ruled (`2026-08-02-provider-model-catalog-adr` L70, L103-106, with L136-137
conceding that some configured providers remain visible but unselectable), but
nothing rules that `eligible_providers` may mean something different from
`selectable`. REMEDY: rename to `configured_providers`, or derive it from the
same admission predicate so the two surfaces cannot diverge. Believe
`/v1/provider-catalog`.

### F6-readiness-vocabulary-undefined | high | the health vocabulary is undefined and self-contradictory in three separate places

`/health` serves `checks.worker.status: ok` alongside `worker_connected: false`
and `worker_status: pending`. `/v1/service` serves `status: ready`,
`can_accept_run: true`, `worker_ready: true`, and `degraded_reasons: []` while
`authoring_backend_reachable` was false. A live run served `degraded_reasons:
[execution_state_projection_missing]` beside `repair_status: healthy` and
`execution_readiness: healthy`. CONSEQUENCE: no client can compute "is this
usable?". `checks.worker.status: ok` next to `worker_connected: false` is a
plain contradiction inside one payload, and a green badge derived from
`degraded_reasons: []` hid that the document-authoring backend - the capability
the product exists for - was unreachable. CLASSIFICATION: split. RULED and
therefore not a defect: `worker_ready: true` on a cold worker, per
`2026-07-18-desktop-product-profile-adr` L173-176 ("Worker absence before demand
is informational, not degradation") and L319. NOT RULED anywhere:
`degraded_reasons`, `can_accept_run`, and `authoring_backend_reachable` have
zero hits in the decision corpus and originate in execution records; whether an
unreachable authoring backend SHOULD degrade the service was never decided. A
premise correction belongs here: `2026-07-16-authoring-contract-adr` does not
govern health at all - it rules where the document-authoring role and topology
constants live. REMEDY: rule the authoring-backend question; define the
vocabulary in `docs/glossary.rst`; rename `checks.worker.status` to express
"startable" rather than "ok".

### F7-capability-disclosure-empty-and-wrong | medium | capability fields are empty on 16 presets and miscategorize the document editor as coding

`supported_capabilities` is populated only on the four `research_adr` presets,
with `research_document`, `architecture_decision`, and `plan_document`; it is
empty on the other 16. A second field, `authoring_capability`, reports `coding`
for `vaultspec-doc-editor` despite that preset's own served description
beginning "Single vaultspec-doc-editor worker, no supervisor: one agent applies
one natural-language instruction to one existing vault document".
`vaultspec-solo-coder` likewise reports `coding` with an empty capability list.
CONSEQUENCE: a capability-driven launcher can only offer research, decision, and
plan authoring. Document editing and solo coding are declared nowhere
machine-readably, and the one taxonomy field that IS populated files the
document editor under coding. CLASSIFICATION: genuine defect.
`2026-08-02-provider-capability-evidence-adr` explains an EMPTY list, since
capability claims are proof-gated; it does not explain a WRONG one. REMEDY:
populate capabilities across presets and correct the document editor's
`authoring_capability`. See F16, which supplies strong evidence that this field
is not cosmetic.

### F8-team-status-contradicts-runs | medium | `/v1/team/status` reports an idle system during an active run

`/v1/team/status` returned `{"api_version":"v1","agents":[],"active_runs":[],
"pending_permissions":[]}` while `/v1/runs` at the same instant returned a run
with `status: running`. CONSEQUENCE: a "current activity" panel built on
`/v1/team/status` shows an idle system during an active run. CLASSIFICATION:
genuine defect, consistent with the known prior finding that the same route
serves null provider and model values. REMEDY: back `active_runs` with the same
projection `/v1/runs` uses, or remove the route rather than serve a false empty.
See F18, which finds the same surface wrong in the opposite direction.

RETRACTION (third tranche). This finding DOES NOT REPRODUCE and should be
treated as closed. The live-run session found `/v1/team/status` fully populated
against a PAIRED worker; the all-empty arrays observed here were caused by the
worker being unpaired at the time of the probe, not by the projection. The
route is not serving a false empty. F18 is unaffected and stands on its own
evidence - the two were never the same defect, and pairing them in the original
entry was a mistake this retraction corrects.

### F9-run-status-serves-dead-fields | medium | run status serves two empty fields that look authoritative while the real assignment sits elsewhere

A live run served `roles: []` and `assignments: []` while `frozen_assignment`
carried the real assignment including provider identity, execution mode, and
catalog revision. CONSEQUENCE: a panel rendering "which agents and models are
running?" from `assignments` shows nothing on a fully-resolved run, and nothing
in the served payload indicates `frozen_assignment` is the authority.
CLASSIFICATION: documented decision, incompletely applied. The 2026-08-03
amendment to `2026-08-02-provider-model-catalog-adr` L153-158 rules that
run-start and run-commit responses disclose exactly one execution authority and
that the retired profile pair is "removed from those responses rather than
served empty" - but scoped removal to start and commit, so run-status still
serves them empty, precisely what the amendment refused to do. REMEDY AND
CLASSIFICATION NOTE, recorded so it is not misread later: this is EXECUTION OF
AN EXISTING RULING and needs no new decision record, but it REMOVES FIELDS THE
DASHBOARD CONSUMES TODAY, so it is a breaking wire change requiring a plan Step
plus cross-repository coordination. "Already ruled" does not mean "safe to land
unilaterally".

### F10-undiscriminated-response-union | medium | `POST /v1/runs` returns a four-way union with no discriminator

The 201 response is an `anyOf` of the start, prepare, commit, and release
response models with no `discriminator`. The selector is `stage` on the REQUEST,
whose four values are described only inside the enum's own description.
CONSEQUENCE: generated clients produce an untagged union the caller must narrow
by hand, and the four-stage reservation lifecycle - genuinely useful - is
invisible to anyone reading the route. CLASSIFICATION: genuine defect,
mechanical. REMEDY: add a discriminator, or split by response code or route, and
document the lifecycle.

### F11-private-schema-names-leak | medium | underscore-prefixed private schema names are published in the contract

`components.schemas` contains `_AgentSnapshot`,
`_ClarificationRequestSnapshot`, `_ClarificationQuestionSnapshot`,
`_PermissionSnapshot`, and `_PermissionOptionSnapshot`. CONSEQUENCE:
underscore-leading names are invalid or mangled identifiers in most code
generation targets, and these sit on the clarification and permission surfaces -
the human-in-the-loop path. CLASSIFICATION: genuine defect. REMEDY: rename the
models; they are public regardless of the Python convention.

### F12-presets-workspace-root-optional | medium | `/v1/presets` silently returns a different answer without `workspace_root` while its sibling requires it

`workspace_root` is declared optional on `/v1/presets` and required on
`/v1/provider-catalog`, which 422s cleanly when it is omitted. The bare
`/v1/presets` call adds "agent harness incomplete: no workspace resolved for a
document-authoring preset" to the `research_adr` presets' unavailable reasons;
the parameterized call does not. No error either way. CONSEQUENCE: omitting an
optional parameter yields a quietly more-broken picture with no signal that the
wrong question was asked, and two sibling discovery routes carry opposite
conventions. CLASSIFICATION: genuine defect, an inconsistency between siblings.
REMEDY: make it required to match its sibling, or return a top-level
workspace-resolution flag.

### F13-no-topology-discovery | low | no route enumerates topologies or their structure, and the topology enum is defined in no document

Chains are inferable only from each preset's `topology` string - `pipeline`,
`pipeline_loop`, `star`, `research_adr`. CONSEQUENCE: a frontend cannot render
what a preset will actually DO, only its name and an undefined enum.
CLASSIFICATION: undocumented accident. REMEDY: serve topology metadata - node
sequence, roles, pause points - on the preset, or add a topologies route.

### F14-stale-compiler-module-docstring | low | the graph compiler's module docstring claims three topology types where four are dispatched

`src/vaultspec_a2a/graph/compiler.py:4` states "Three topology types are
supported", listing star, pipeline, and pipeline_loop, while the function
docstring at `:931` says "Supports four topology types" and `:1051` dispatches
the research-to-ADR topology - the flagship chain. The module docstring is the
sole stale copy. CONSEQUENCE: none directly, being internal source a frontend
author never sees; recorded because it is F13's omission one layer down.
CLASSIFICATION: genuine defect, documentation. REMEDY: update the module
docstring.

### F15-fatal-errors-bypass-structured-log | low | boot failures reach stderr only, and the live instance's registry record carries a null log path

`~/.vaultspec-a2a/runtime/gateway.log` (1843 JSON lines) contains zero lines
matching band-port, live-listener, or traceback patterns; the level tally is
1239 informational, 554 warning, 51 error, and all 51 errors are telemetry
exporter noise about an unavailable local collector. The reported boot failure
reached stderr only. The live instance's process-registry record carries a null
log path while siblings carry real paths, and two records both claim port 18110.
CONSEQUENCE: none for a frontend author; operator-facing. CLASSIFICATION: mixed.
Structured-logging LANES are ruled (`2026-07-19-observability-lanes-adr`
L80-86), but a guarantee that EVERY ERROR REACHES THE STRUCTURED LOG is NOT
FOUND anywhere in the corpus, so that completeness gap is genuinely unowned. The
log path belongs to the process registry by design
(`2026-07-15-dev-process-registry-adr` L38) rather than to the discovery record,
but within the registry it is inconsistently populated and the duplicate
port-18110 records are stale. REMEDY: route startup failures through the
structured logger before exit; populate the log path consistently; reap stale
registry records.

### F16-completed-run-produces-no-artifact | critical | a document-authoring run completed with real model output and produced nothing applyable

Run `866679f3` (`vaultspec-doc-editor`) reports `status: completed` with
`proposal_ids: []`, `changeset_ids: []`, `artifacts: []`, an empty
`authoring_session_id`, `approval_status: null`, `degraded_reasons: []`,
`repair_status: healthy`, and `execution_readiness: healthy`. The model's output
- a complete document with an appended Summary section - exists only as prose
inside an assistant chat message in the transcript. The preset's own served
description states that no persona writes to the filesystem directly, that all
authoring goes through engine proposals, and that a human applies through the
dashboard review lane; no proposal was ever created, so there is nothing for the
review lane to apply. Both completed document-editor runs show the same empty
artifact set.

CORRECTION (third tranche, supersedes the causal note below). The
`authoring_capability` hypothesis recorded in this entry is REFUTED as the
mechanism. The real cause is F24: the bridged `propose_changeset` tool is
auto-denied at a permission rung with `[{"type":"text","text":"user rejected
MCP tool call"}]` against a schema-conformant payload, and no permission request
is ever surfaced. The two paths differ by SUBMISSION MECHANISM, not by
capability string: the research_adr chain submits through the engine's HTTP
authoring API directly from the worker, bypassing the model's tool surface
entirely, while the document editor goes through the bridged tool that is
blocked. `authoring_capability` correlated only because it tracks which topology
uses which path. The original note is retained below unrewritten, because a
hypothesis recorded and then refuted is more useful than one quietly deleted.
The finding itself - a completed run producing no artifact - stands unchanged,
and its remedy is unchanged: the missing proposal and the silent green remain
two separate defects.

CONSEQUENCE: the product's core claim reports SUCCESS while
delivering nothing applyable. A frontend sees a completed run with no
degradation and has no document to show or apply. This is a false green in the
most literal sense - the run is green, the model did the work, and the work is
unreachable. CAUSAL LINK TO F7, strongly evidenced but not yet code-confirmed:
`authoring_capability` takes exactly two values across all 20 served presets,
and the split against artifact production is perfect. The four presets valued
`document_authoring` produced proposals - even the FAILED run `1226efda` emitted
one - while the 16 valued `coding`, including `vaultspec-doc-editor`, produced
none. The outcome is inverted: the run that failed produced an artifact, the two
that completed produced none, and the only distinguishing variable is that bare
string. STILL TO CONFIRM IN CODE: that the authoring-bridge and proposal path is
genuinely gated on this value. The remedy branches on it - if gated, reclassify
the preset AND make the value a typed enum; if not gated, the missing proposal
has a separate cause and F7 is merely cosmetic. REMEDY: either the document
editor must submit its output as an engine proposal, or a run producing no
artifact must not report completed with empty degradation. Both, ideally: the
missing artifact is the bug, the silent green is the safety failure.

### F17-tool-call-status-never-reconciled | high | every tool call stays `pending` on a completed run, including one the model narrates as rejected

Run `866679f3`, status completed, carries 15 tool calls and every one is
`status: pending` with empty `locations` and empty `content`. The transcript
proves these are not genuinely pending - the model narrates their results, and
one was actively rejected, the model reporting that a hash check "hit a policy
rejection because I wrapped PowerShell inside PowerShell". That rejection is
nowhere in the tool-call record. CONSEQUENCE: a frontend rendering tool activity
shows 15 perpetually-spinning operations on a finished run and can never show
which succeeded, which failed, or what any of them touched. Tool-call state is
write-once at dispatch and never advanced to a terminal value.
CLASSIFICATION: genuine defect, and an instance of the bare-string status
problem - this `status` has no terminal-state contract.

### F18-agents-projection-not-run-scoped | high | a one-worker pipeline run reports the full eight-agent roster of a different topology

Run `866679f3` is `vaultspec-doc-editor` with `topology: pipeline` and
`worker_count: 1`. Its history reports eight agents, none of which is the
document editor: the complete research-to-ADR roster including research
dispatch, synthesis, research review, decision author, decision review, plan
author, and plan review, each with full persona descriptions referencing the
research_adr topology. CONSEQUENCE: a frontend agent panel renders seven roles
that are not participating, from a topology the run does not use. Combined with
F8, the agent-identity surface is unreliable in BOTH directions - empty when it
should be populated, populated with the wrong roster when it should be scoped.
Inside the same projection, every agent reports a populated provider alongside a
null `model` and a populated `model_name` - a null-versus-populated
inconsistency in one object, matching the known team-status defect.
CLASSIFICATION: genuine defect.

### F19-last-sequence-zero | high | `last_sequence` is 0 on a completed run, so the reconnect protocol cannot work

Run `866679f3` reports `last_sequence: 0` while the same payload carries three
messages, 15 tool calls, `history_depth: 2`, `checkpoint_step: 2`, and
`replay_status: durable`. CONSEQUENCE: `last_sequence` is the value a client
would use to resume an interrupted subscription; if it is always 0, a
reconnecting frontend either replays everything or replays nothing. F1 already
established that the replay protocol is undocumented, so no client can even
discover the intended semantics. CLASSIFICATION: genuine defect. This compounds
the deliberate non-coverage recorded in Scope and must be verified as part of
driving the streaming surface live.

### F20-run-stranded-in-reconciling | medium | a run stranded in `reconciling` survives a restart with no recovery path and no defined meaning

Run `6943bd0d` (`mock-success-single`), started before the engine existed,
remained `reconciling` after both the gateway and the worker were restarted. It
is the only run returned by the default runs listing, which filters to active
state, so it permanently occupies the active-run view. CONSEQUENCE: a frontend's
active-run list is headed indefinitely by a dead run. No served field explains
what `reconciling` means, how long it may persist, or what a client should do.
CLASSIFICATION: genuine defect, and another undefined vocabulary value.

### F21-emitted-document-duplicates-a-heading | medium | the document content the model emitted contains two identical section headings

The document body emitted in run `866679f3` contains two `## Summary` sections -
the restated existing content and the newly appended two sentences.
CONSEQUENCE: lower severity than F16 only because the proposal never reached
disk. If F16 is fixed without addressing this, the first thing the review lane
receives is a malformed document. CLASSIFICATION: genuine defect, content
quality. REMEDY: a content-quality gate on authored output. This is direct
evidence that authoring obligations - validation against the persisted document
conventions - are a real requirement rather than a nicety.

### F22-failed-run-reports-healthy | high | a failed run reports `healthy` on every structured health field it serves

Run `1226efda` (`vaultspec-adr-research`), status failed, serves `failure_reason:
"Ingest stalled: no event from the graph for over 90s"` alongside
`repair_status: healthy`, `execution_readiness: healthy`, `degraded_reasons:
[]`, an empty repair reason, and `provider_condition: unknown`. CONSEQUENCE: the
prose failure reason is genuinely useful and specific, but every MACHINE-READABLE
health field says nothing is wrong on a run that failed. A frontend gating on
the structured fields sees a healthy run and must fall back to parsing status
and prose. CLASSIFICATION: genuine defect. This is F6 with a concrete failure
attached: these fields are not merely undefined, they are actively WRONG at the
moment they matter most. It shares its defect class with F16's green-on-empty-
artifact and F17's pending-on-complete.

CORRECTION (third tranche, itself revised once). The run was NOT failing on its
own merits when it was killed: it was executing legitimate long-running work
that its own preset configuration sanctioned, and an unconditional 90-second
bound terminated it. See F25 for the mechanism.

The health fields being wrong is still the finding here and still stands - but
they were wrong about a run that was working, which makes this entry an instance
of the same disease rather than a description of a genuine failure. A run killed
by its own infrastructure is exactly the case where a structured health field
should have said something, and every one of them said `healthy`.

A claim briefly recorded here and now WITHDRAWN: that the `failure_reason` prose
was itself false. It was not - it accurately reported the watchdog's own signal.
This entry's original credit to that field as "genuinely useful and specific"
was closer to right than the retraction that briefly replaced it. What the
message got wrong is narrower and belongs to F25: it named "the graph" where it
meant one specific stream.

### F23-served-vocabulary-typing-is-split | high | the same kind of vocabulary is served as a closed enum in 32 places and as a bare string in 15, and two concepts are served both ways at once

Measured against the served specification on 2026-08-05, not assumed. The
contract ALREADY carries roughly 32 properly typed, closed enumerations,
including `ThreadStatus` (11 members), `ToolCallStatus`, `AdmissionState`,
`HealthState`, `AuthenticationState`, `CatalogStatus`, `WorkerLifecycleState`,
`LivenessState`, `GatewayReadiness`, `ProviderEligibility`, `RunAdmission`,
`ToolKind`, `PermissionOptionKind`, `AgentLifecycleState`, `Provider`, `Model`,
and `RunStage`. This corrects a premise worth recording: `RunStage` is NOT a
lone precedent, and the surface is not uniformly stringly-typed.

The defect is the SPLIT, and it has three distinct shapes.

SHAPE ONE - an enumeration exists in code and is DISCARDED at the wire.
`TopologyType` is a four-member string enumeration in
`src/vaultspec_a2a/team/team_config.py:106`, yet `PresetSummary.topology` is
served as a bare nullable string. `Provider` is a nine-member enumeration served
correctly as an enum on the agent snapshot's `provider`, while the SAME concept
is served as a bare string in `provider_id` on five other models. One concept,
two typings, one payload.

SHAPE TWO - a vocabulary has no declaration anywhere. `authoring_capability`,
`origin`, `repair_status`, `execution_readiness`, `provider_condition`,
`approval_status`, `worker_status`, `semantic_status`, `semantic_phase`,
`replay_status`, and `degraded_reasons` are bare strings or string arrays with
no owning type in code or on the wire. `origin`'s legal values exist only in a
source comment - "bundled | workspace | test_mock" at
`src/vaultspec_a2a/api/schemas/gateway.py:945` - which is a declaration a client
cannot read and a compiler cannot check. `supported_capabilities` is an
unconstrained string array. This is the direct cause of F4, F6, F7, and F13.

SHAPE THREE, and the one that bounds what typing can fix - a vocabulary is
PROPERLY TYPED and still wrong. `ToolCallStatus` is a closed enum with a genuine
terminal set (`pending`, `in_progress`, `completed`, `failed`), and F17 happened
anyway: 15 calls stranded at `pending` on a completed run. `ThreadStatus`
properly contains `reconciling`, and F20 happened anyway. Typing constrains a
value's DOMAIN; it never obliges a writer to ADVANCE the value, and it cannot
make a written value true. F17, F20, and F22 are therefore NOT typing defects
and will not be closed by typing work.

A further hazard for anyone executing the remedy: `AdmissionState` is declared
twice, at `src/vaultspec_a2a/control/drain.py:36` (open, draining - the drain
gate) and `src/vaultspec_a2a/providers/provider_catalog.py:106` (admitted,
not_admitted, unknown - completed-turn evidence). These are genuinely DISTINCT
concepts that happen to share a name. A remedy phrased as one declaration per
NAME would wrongly merge them; the rule must be one declaration per CONCEPT.

CONSEQUENCE: a frontend can generate exhaustive, checked handling for the typed
half of the surface and must hand-maintain string literals for the rest, with
nothing marking which half a given field is in. CLASSIFICATION: genuine defect
for shapes one and two; shape three is recorded here as a SCOPE LIMIT on the
remedy rather than as a typing defect. REMEDY: shapes one and two are the
follow-on decision record's subject. Shape three needs a separate obligation -
a transition or terminal-state contract with a writer that is required to
advance the value - and must not be folded into the typing work, or F17 and F22
will be marked closed while still occurring.

### F24-bridged-propose-is-auto-denied | critical | the authoring tool is refused at a default-deny with no elicitation path wired, and no permission request is ever surfaced

Source tranche number 23. THE ROOT CAUSE OF F16. An instrumented run asked the
model to call the engine's propose tool once and report any rejection verbatim.
It returned `[{"type":"text","text":"user rejected MCP tool call"}]` against a
payload conforming to the schema the engine publishes at its agent-tools route.
The run settled `completed` with `failure_reason: null`, `proposal_ids: []`,
`pending_permissions: []`, and no permission-request event on the stream.
PROVEN: a2a's own permission handler never ran - it logs a line on every
invocation and there are zero such lines in the worker log for that run.

MECHANISM, established by LIVE PROTOCOL REPRODUCTION IN BOTH DIRECTIONS and
superseding the original inference. The provider answers every server-initiated
request with a method-not-found error, which is a default deny with no
elicitation path wired. Answering that way makes the tool item settle `failed`
with the rejection text and the turn complete - AND the target server receives
`initialize` and `tools/list` but never `tools/call`. Answering instead with an
acceptance makes the same tool settle `completed` with a real result, and the
server logs the actual call. That the call never reaches the server in the deny
case is what makes this conclusive rather than suggestive.

THREE SPECIFICS IN THE ORIGINAL DIAGNOSIS WERE WRONG, and the reason they were
wrong is recorded because it generalizes. First, the method is the MCP server
elicitation request, NOT a permissions method - no method of that name exists in
this protocol version, and the similarly-named approval method that does exist
is sandbox escalation carrying no tool identity, a different feature. Second,
the response vocabulary is the MCP elicitation contract of accept, decline, or
cancel - not the approved/denied/timed-out set, which is real but belongs to
auto-review NOTIFICATIONS that are informational rather than a client rung.
Third, the request carries NO TOOL-NAME FIELD: its parameters name the thread,
turn, server, mode, message, requested schema and a metadata marker, and the
tool name appears ONLY inside the human-readable message.

The original diagnosis came from a BINARY STRING GREP - the string was present,
so it read as confirmation. It was present for an unrelated feature.

CONSEQUENCE FOR THE REMEDY, which the third specific constrains sharply. The
ruled decisions require an exact-name allowlist and explicitly reject blanket
approval, and the autonomous fallback is barred from approving uncovered calls.
The elicitation payload cannot supply that name on its own, so tool identity must
be recovered by correlating with the tool-call notification that arrives
immediately before on the same thread and turn. Parsing the prose message is
forbidden. Any correlation miss must therefore FAIL CLOSED to decline and log,
or the remedy becomes a latent blanket approve - which would be worse than the
defect it replaces.

CLASSIFICATION: genuine defect. REMEDY: wire the elicitation rung with
frame-correlated tool identity and a fail-closed default. The substance of the
original finding is unchanged: a default deny, no permission object ever
constructed, and a run settling completed with nothing produced.

### F25-watchdog-bound-ignores-the-runs-own-timeouts | critical | an unconditional 90-second bound killed a run whose own configuration sanctioned 1800 seconds of node silence

Source tranche number 24. SUPERSEDES THE STALL PREMISE IN F22. The slug and
summary of this entry were rewritten once; the identifier is unchanged and the
correction is described below.

The flagship research-to-ADR run was killed at 12:19:13 by the ingest-stall
watchdog, serving `failure_reason: "Ingest stalled: no event from the graph for
over 90s"`, with an agent subprocess spawned at 12:17:47 still alive at the kill.
The model was mid-turn.

CORRECTION - the reason was NOT false, and this entry originally said it was.
The watchdog wraps each `astream_events()` iteration in `streaming/ingest.py`,
which is the SAME iterator the worker's transformer consumes to produce every
relayed chunk, in the same process against the same compiled graph. The
event-batch counts and chunk totals cited as refutation are aggregates DERIVED
from that stream over a window, not a separate signal, and an aggregate cannot
rule out a gap inside the window it aggregates. Legitimate work makes such gaps
routine: a long tool call or an extended reasoning stretch produces no
`on_chat_model_stream` event at all while per-minute totals still look healthy.
The watchdog was reporting its own signal accurately.

Both of this entry's earlier framings are therefore withdrawn: the "asserts
something false about its own state" claim, AND the inferred hedge that the
watchdog "counts a different channel than the worker posts to". The hedge was
closer to the truth than the confident claim built on it, but it is still wrong
as stated - the source is one channel, and what differs is the resolution at
which it was measured.

THE ACTUAL DEFECT is a threshold mismatch, and it is worse than a false message.
The watchdog's outer bound was a flat global 90 seconds, while the agent chat
model explicitly sanctions up to 600 seconds of silence as legitimate during a
long tool call, and the run's own preset declares a step timeout of 1800 seconds
which is set on the compiled graph object. An unconditional bound hardcoded at
90 seconds consulted neither number. The system was killing work its own
configuration declared safe.

The message was still misleading in a narrower way: "no event from the graph"
reads as "nothing happened in this run", when it means one specific stream
produced nothing. That half stands.

CONSEQUENCE: any agent-backed document-authoring node doing genuine
long-running work - which is the flagship chain - was killable mid-turn by its
own infrastructure. This was the direct blocker on producing decision and plan
documents. CLASSIFICATION: genuine defect, correctness and observability.
REMEDY: APPLIED in commit `088bd603`. The effective bound is now derived from
the compiled graph - the greater of the global floor and the graph's own step
timeout plus a margin - so it is run-aware from data already in scope rather
than a raised static default that would be wrong for some other preset. Presets
with no configured step timeout keep the 90-second floor unchanged. The reason
text now names the exact signal rather than "the graph".

TWO HONEST GAPS, recorded rather than smoothed over. Per-event timestamps for
the run in question could not be obtained - the database holds no rows for that
thread, which belonged to a different worker session - so the diagnosis rests on
the architectural mismatch between the three timeout values, not on a log replay
of that run. Confidence is high but this is inference. And the decision corpus
was searched for a prior deliberate ruling on the 90-second value; none was
found on point, the only related record being the incident that introduced the
watchdog, which predates this tension. No ruling was overridden, and the absence
was checked rather than assumed.

RESIDUAL: the margin added to the step timeout is a module constant,
deliberately not configurable because no other consumer needs it. If it should
become a named configuration knob, that is a decision, not a defect.

### F26-engine-serve-command-breaks-on-windows-paths | medium | the documented launch override is unusable with native paths and the surfaced error names the wrong cause

Source tranche number 25. The engine serve command template is split with POSIX
tokenization, which consumes every backslash, so a native Windows path becomes
an unfindable executable. The launch failure was logged ten times but surfaced
to the operator as "no band port yielded a live listener" - a port-allocation
message for a file-not-found cause. Forward slashes are the workaround.
CONSEQUENCE: the documented override is broken on this repository's target
platform and points the operator at the wrong subsystem. CLASSIFICATION: genuine
defect. REMEDY: split without POSIX semantics on Windows, or accept a list-valued
template, and propagate the launch error instead of collapsing it into a port
message.

### F27-engine-data-seat-guard-is-defeated | high | an explicitly supplied data seat is silently ignored whenever it sits inside a git repository

Source tranche number 26. A seat directory was passed explicitly to the process
launcher. After boot the seat was empty and the engine's store had appeared
under the repository's own vault data directory, with the engine reporting an
active scope of the repository root. The engine resolves its vault root by
git-worktree discovery from the working directory rather than from the working
directory itself, so any seat inside a git repository is hoisted to that
repository's root. The guard's own docstring names avoiding exactly this outcome
as its purpose. CONSEQUENCE: two development engines seated under one repository
share a store. Impact is bounded here because the store is a gitignored
rebuildable cache, but the guard is not doing its stated job. CLASSIFICATION:
genuine defect, data-corruption class. REMEDY: honour the explicit seat as the
vault root, or refuse a seat that resolves into an enclosing worktree.

### F28-engine-surface-has-no-machine-readable-description | high | the engine surface a frontend must use publishes no schema, and every fact about it costs a source read in another repository

Source tranche number 27. The engine's OpenAPI path returns 200 with the
single-page-application HTML fallback rather than a schema; its route list
exists only as a source constant. Undiscoverable from any live interface: the
actor-token mint route and its payload; the proxy verb vocabulary; that an
expected-scope generation fence is required on most proxy verbs and obtainable
only from the engine's session route; that `workspace_root` is REJECTED by the
proxy but REQUIRED by a2a directly, the two surfaces contradicting each other;
that `feature_tag` is required for document-authoring presets but optional in
a2a's schema; and that proxy application errors arrive with HTTP 200 carrying an
error body. On a2a's side, `actor_tokens` appears as an optional caller-supplied
field, no a2a route returns such a bundle, and nothing hints the value comes
from a different service. CONSEQUENCE: a third-party frontend cannot be built
against the live interface alone. CLASSIFICATION: genuine defect, product blind
spot. REMEDY: publish an engine schema; declare the conditional requirement of
`feature_tag` in a2a; align `workspace_root` across the two surfaces; return
proxy errors with a non-200 status.

### F29-review-gate-is-unreviewable | high | a human is asked to approve a document that no route will show them

Source tranche number 28. The gate prompt asks for approval of a named research
document. a2a serves only proposal identifiers, its artifacts array is empty,
and no a2a route matches proposal, artifact, or document. On the engine side the
proposal fetch returns 200 but with an empty review-documents array and an
operation count of one carrying no operation body; the diff and preview routes
both 404. CONSEQUENCE: the review gate is ceremonial - the approving human
cannot see what they are approving. CLASSIFICATION: genuine defect; the content
is in the ledger and is simply not served. REMEDY: serve the proposed body, from
the engine and/or as an a2a passthrough on the run.

### F30-a2a-approval-never-advances-the-engine-decision | high | approving through a2a is a graph resume signal only, so a produced document has no path to disk

Source tranche number 29. The permission respond route returns 200 with
`accepted: true`, `applied: false`, an action status of `accepted_not_applied`,
and an approval status of `approved`. The engine ledger afterwards still reports
the proposal as needing review and queued. Zero files were written to the vault
by any of the six runs driven in that session. CONSEQUENCE: there is no path
from a produced document to a file on disk through the documented API. Taken
with F29, the delivery path is broken at its last mile rather than its first.
CLASSIFICATION: genuine gap. The `applied: false` disclosure is honest, so the
field is not lying - but the end-to-end capability is absent and no surface
tells a frontend what else to call. REMEDY: forward the decision to the engine's
approval queue, or document and serve the second call a frontend must make.

### F31-authoring-session-id-always-null | medium | the run never discloses the authoring session the engine recorded for it

Source tranche number 30. A run reported a null authoring session identifier
throughout while the engine ledger recorded a concrete session identifier for
that same run's proposal. Null on all six runs. CONSEQUENCE: a frontend cannot
join a2a's run view to the engine's authoring session, and the documented
run-end session close cannot find the session either. CLASSIFICATION: genuine
defect. REMEDY: fold the session state reference, which the authoring session
object already returns, into thread state on the submitter path as well as the
bridge path.

### F32-terminal-transition-erases-the-approval-record | medium | the decision a human made does not survive the run reaching a terminal state

Source tranche number 31. At the gate the run reported a pending approval status
with a concrete request identifier and a sequence of 678. After the approval and
the subsequent failure, all three read null, null, and 0, with the worker
logging that it pruned one stale permission request. The proposal identifier
survives; the decision does not. CONSEQUENCE: a post-mortem through the API
cannot distinguish an approved run from one never reviewed. CLASSIFICATION:
genuine defect. REMEDY: preserve the recorded outcome on terminal transition -
pruning a PENDING request must not erase the DECISION.

### F33-engine-writes-metadata-a2a-rejects | medium | run metadata written by the engine fails a2a's own model and is silently reported absent

Source tranche number 32. The gateway logged that stored metadata for a run does
not satisfy the metadata model and that it is reporting it absent. The engine's
run-start forwards a workspace root as a scope token. CONSEQUENCE: workspace
provenance - which engine source describes as engine-owned and durable in a2a
run metadata, and as the selector the bounded active-runs read matches after
reload - is silently dropped, so reload recovery by workspace is unreliable for
proxy-started runs. CLASSIFICATION: genuine defect, cross-repository contract
drift. REMEDY: reconcile the engine's metadata shape with a2a's model, and fail
loudly rather than reporting it absent.

### F34-team-run-start-exceeds-the-forward-budget | medium | a cold provider catalog pushes team run-start past the proxy budget and it fails as a connection error

Source tranche number 33. A first team start through the proxy returned 504 with
a connection-attempt error. That run does not exist on a2a and has zero lines in
either log. The proxy's control budget is 60 seconds against a cold
provider-catalog refresh measured at 36.2 seconds with a five-minute cache life;
warming the catalog first took 0.1 seconds and the identical start then
succeeded. CONSEQUENCE: team run-start fails roughly whenever the catalog has
aged out, and the operator sees a transport-level connect error for what is a
budget expiry, with no run and no log line to work from. CLASSIFICATION: genuine
defect. REMEDY: raise or split the run-start budget, warm the catalog before
forwarding, report a budget expiry as a timeout, and log the abandoned attempt.

### F35-eligible-is-false-on-one-surface-and-true-on-another | high | the same field contradicts itself across two surfaces, and one of them can never be true

Source tranche number 34. SHARPENS F2. The preset listing returns `eligible:
false` for every profile of all 20 presets with the research-to-ADR acceptance
reason, because the route passes an acceptance-gate flag hardcoded false and is
the ONLY production caller of the eligibility composer - every other call site
is a test, so it can never be otherwise. Yet the direct run-start response for
the same preset returns `eligible: true`, and run-start does not enforce the
gate: all six live runs started. CONSEQUENCE: a frontend honouring the listing
shows zero runnable presets permanently; one honouring the run-start field sees
the opposite. The field is simultaneously dead and contradictory.
CLASSIFICATION: genuine defect. REMEDY: wire the acceptance gate to a real
signal or remove the term, and make the two surfaces mean the same thing.

### F36-log-signal-to-noise-prevents-run-correlation | medium | the logs cannot answer what a run did, which is why the critical defect stayed invisible

Source tranche number 35. Correlating by thread identifier yields four gateway
and one worker line for a five-minute run with 30 tool calls, and ten plus four
for a 24-minute team run. Both logs carry a health poll every five seconds and a
telemetry-exporter warning-and-error pair every ten seconds continuously against
an unreachable collector. CONSEQUENCE: the logs cannot answer "what did this run
do", which is precisely why F24 remained invisible until a model prompt was
instrumented to extract the error text. CLASSIFICATION: genuine defect. REMEDY:
demote the health poll and the unreachable-collector export, and log authoring
tool calls and rejections at informational level with the run identifier.

### F37-no-preset-declares-summarization | medium | the advertised summarization capability is not reachable through any served preset

Source tranche number 36. CONFIRMS F7 FROM THE LIVE SURFACE. Across all 20
presets the only declared capabilities are the three document kinds, and only on
the four research-to-ADR variants; 16 of 20 declare an empty capability list,
including the document editor, which additionally declares its coarse capability
as coding. CONSEQUENCE: the advertised ability to summarize existing vault
documents is NOT REACHABLE through any served preset, and the nearest path is
the false green of F24. CLASSIFICATION: genuine gap - either the capability is
unimplemented or the presets under-declare it. REMEDY: declare and serve the
capability, or drop the claim.

### F38-only-codex-is-admitted | low | one provider is selectable and another serves 128 models while remaining unselectable

Source tranche number 37. Recorded so it is not re-investigated. The live
catalog shows codex selectable with 7 models; openai reports an available
catalog with 128 models but is not admitted and not selectable; the remaining
lanes report unavailable catalogs with reasons citing absent completed-turn
proof. CLASSIFICATION: documented decision, the served-profile admission rule
working as designed. No remedy. This is the intended behaviour of the admission
rule and must not be "fixed".

### F39-router-level-auth-breaks-the-websocket | medium | mounting the bearer scheme at router level silently broke the worker socket behind a clean-looking contract change

Found and fixed DURING remediation, recorded because it reproduces this
document's own through-line rather than because it survived. While landing the
authentication declaration, the bearer scheme was mounted as a router-level
dependency. Router-level dependencies also apply to WebSocket routes, and the
bearer resolver resolves only against an HTTP request, so the worker WebSocket
broke. Four internal WebSocket logging tests failed and the fix was to attach
the dependency per HTTP route instead.

CONSEQUENCE, had it shipped: a correct-looking, fully declared authentication
contract over a broken worker connection - the served surface improving while
the mechanism beneath it stopped working. CLASSIFICATION: genuine defect,
already fixed; recorded as evidence rather than as open work.

WHY IT EARNS A NUMBER. It was caught by RUNNING THE TESTS rather than by
reasoning from source, and reasoning from source is what would have shipped it.
That is the same shape as F16, F17, and F22 - a typed surface that looks right
over a mechanism that is not - occurring inside the remediation of those very
findings. It is direct evidence that the pattern is structural to this codebase
rather than a property of the three runs that first exposed it, which is a
stronger claim than any single earlier finding could support. Anyone closing a
contract-shaped Step on source reading alone should read this entry first.

### F40-reserved | low | reserved, assigned and not yet received

Assigned to a live-run agent for an ACP-lane tool-call gap and not yet delivered
in full. The number is held rather than reused so the assignment stays stable.
Known shape, to be replaced by the agent's own text: agent-lane tool calls
accumulate rich per-update status, content and locations in the session context,
but that state is wiped at session cleanup and never re-emitted, so it is
unrecoverable from either the streaming or the snapshot side and needs the
provider to forward per-update data. LATENT, NOT LIVE - no such lane is
currently an admitted provider, and the evidence from the admitted lane must not
be read as inflating this one.

### F41-engine-route-table-is-never-served | high | the engine holds a complete machine-readable route table and serves single-page-application HTML instead

Same family as F1, a strong contract a client cannot reach; this is its mirror on
the engine side. The engine's authoring module holds a route-fixture array
covering the whole authoring surface, carrying per route the method, path
template, family, command kind, whether it mutates, whether idempotency is
required, and a list of in-domain refusals NAMED INDIVIDUALLY - stale review
revision, stale approval, missing idempotency key, unknown field. Sixteen routes
are declared this way, including the review-decision and apply-request routes.
Meanwhile the engine's OpenAPI path returns 200 with single-page-application
HTML.

CONSEQUENCE: this repository had to be written against that surface by reading
another repository's source. CLASSIFICATION: genuine defect, and a cheap one -
this is not missing work but UNSERVED work. The declaration already exists in a
form richer than most OpenAPI documents, naming per-route failure modes that
OpenAPI usually cannot. Nothing needs authoring; something needs exposing.
REMEDY: serve the route table as a machine-readable description at a stable
path and stop returning application HTML from the schema path. The named-refusal
list is the valuable part and must survive into whatever is served - a client
that knows a stale approval is a named outcome can handle it, where one
discovering it as an opaque success-with-denial cannot. CROSS-REPOSITORY: this
is a dashboard-repository change, cheap but not ours to land.

WHY THIS OUTRANKS ITS SEVERITY: F41 is the DEMONSTRATED CAUSE OF F30. The
approve and apply verbs existed the whole time and this repository never called
them, because nobody could see them without reading another language in another
repository. An unserved contract let a capability sit implemented-but-unreached,
and the product's entire delivery path was broken as a direct result. That makes
this causally upstream of the highest-ranked phase on the plan rather than a
tidy-up item.

### F42-tool-approval-config-key-does-nothing | medium | the generated provider config sets automatic tool approval for every server and the elicitation is raised anyway

The generated provider configuration home writes an automatic tool-approval mode
for EVERY declared server including the authoring bridge, and the provider still
raised the elicitation that F24 records. The key therefore does not suppress the
prompt on those server blocks, and a client-side rung is required regardless.
CONSEQUENCE, and the reason this is recorded separately rather than folded into
F24: without it, a later engineer meeting a recurrence will "fix" it by trusting
that configuration key, and it will silently do nothing. CLASSIFICATION: genuine
defect, or at minimum a documented-behaviour gap in a dependency; either way the
operational consequence is the same. REMEDY: do not rely on the key; keep the
client rung as the enforcement point, and record that the key is inert here.

### F43-applied-means-two-different-things | medium | a near-miss where the natural fix would have merged two distinct verdicts under one English word

Caught BEFORE any code was written, by reading a field's docstring rather than
its name. The permission-respond response carries an `applied` flag whose own
documentation states it reports whether the WORKER durably confirmed applying
that request's PERMISSION RESOLUTION. The engine applying a DOCUMENT CHANGESET
to disk is a different fact on a different plane. Two distinct verdicts share one
English word.

The obvious implementation of F30's remedy - forward the decision, then set the
flag true - would have merged them, made the flag untrue for its existing
consumers, and violated the canonical-homes ruling that distinct verdicts are
load-bearing and merging them destroys properties they were written to hold.

CLASSIFICATION: near-miss, no defect shipped. RECORDED IN THE F39 FAMILY and for
the same reason. F39 earned its number because this document's through-line
reproduced during the remediation of it; F43 is the same phenomenon caught one
step EARLIER, before the code existed. That the correct fix's most natural
implementation was itself a canonical-homes violation says something about how
this class of defect propagates: it is not that people are careless, it is that
the wrong merge is the shortest path from a correct intention.

A second decision from the same work belongs here as evidence rather than as a
defect: encoding new outcomes into the action-status string was REJECTED because
it is a bare vocabulary clients branch on, undeclared under the
canonical-vocabulary record's enum-worthiness clause, and growing its value set
mid-capture would hand the in-flight containment proof a moving target. A refusal
becomes a truthful error response instead. That is a served-contract rule doing
real work on a live decision, which is worth recording as evidence the record is
load-bearing rather than aspirational.

### F44-and-beyond | low | reserved marker for continuous appending

New findings land immediately above this marker, taking the next free identifier
after the highest already assigned. This entry carries no finding; it exists so
the append point is unambiguous and so a later tranche does not have to guess
where the log ends. Delete nothing above it.

## Recommendations

### What a frontend literally cannot do today

Holding only the served API and the published documentation, a competent
developer cannot: authenticate without reverse-engineering, because auth is an
optional string header with no security scheme and the token's path appears in
no document (F3); receive live progress, because the only document naming a
stream names a route that 404s and the real route's event names, frame schema,
replay protocol, and terminal semantics are undocumented (F1, F19); decide what
to show the user, because `eligible` is false for everything and `loadable` true
for everything, with neither defined anywhere (F2); show only real products,
because 16 of 20 presets are fixtures and the flag catches eight while
mislabelling one literally named `-mock` (F4); build a working provider picker,
because two endpoints disagree and trusting one yields two dead options (F5);
start a run from the schema alone, because a body without a metadata envelope is
schema-valid and 422s at runtime - a RULED cost, accepted on the premise that
the only caller is the engine; advertise two of the product's three
capabilities, because they appear in no machine-readable field and the one
populated taxonomy field files the document editor under coding (F7); trust a
green light, because ready, accepting, and undegraded are served while the
authoring backend is unreachable (F6), while a failed run reports healthy on
every structured field (F22), and while a completed run reports success having
produced nothing (F16).

### What demonstrably WORKS, stated so the failures are not read as total

The product CAN produce a real document. The research-to-ADR chain authored a
genuine, validated artifact: a proposal and changeset recorded in the engine's
authoring ledger with a validation status of valid, approval-ready true, and an
authoring actor of the synthesist persona - confirmed three independent ways, by
the worker's own 200 on submit, by the engine's ledger, and by a2a's run status.
The model tier works: real turns read real vault documents, grounded themselves
against linked records, and produced real content.

What the product cannot do is get that document onto disk. Zero files were
written to the vault across all six live runs. The distinction matters and must
not be blurred in either direction: the authoring capability is real and the
delivery path is broken, which is a materially different problem from a model
that cannot write.

Two further capabilities were proven that were previously believed blocked. An
actor-token bundle IS obtainable through a real HTTP route - the engine's
bootstrap mint route, gated by the machine bearer alone and requiring no
pre-existing token - so the run-start refusal for missing role tokens is fully
solvable client-side. And a run can be started either directly against a2a with
a self-assembled bundle or through the engine proxy, both proven live.

### The through-line, and what it means for the decision to be taken

The TYPED surface is genuinely strong - 80-plus closed schemas, constrained
strings, and an artifact-drift test most projects lack. What is missing is the
SEMANTIC layer: which of two disagreeing fields is authoritative, what a boolean
means, which presets are real, and what arrives on the stream.

The live-run tranche sharpens this into something more specific than "the
documentation is thin". In F16, F17, and F22 the PROSE is honest and the TYPED
surface lies: the model narrates a rejected tool call whose record says pending;
a failure reason names a 90-second graph stall while every health field says
healthy; a transcript carries a finished document while the artifact list is
empty and degradation is empty. The typed surface is precisely what a frontend
must gate on. Where a served vocabulary is a bare string with no owning
declaration and no terminal-state contract, it drifts from the truth it is meant
to encode, and F16 shows the cost is not cosmetic: a mistyped capability string
appears to switch the product's primary function off with no error anywhere.

The originating cause is recorded plainly in the corpus: this contract was
designed for exactly one consumer, the dashboard engine, which already knows the
answers out of band. `2026-08-03-production-boundary-adr` L111-113 makes the
assumption explicit. The claim that the service can feed any frontend that
connects to it is NOT SUPPORTED; it can feed the one frontend that already knows
what its fields mean.

### The decision a follow-on record must make

A follow-on decision record must rule the canonical typing of served
vocabularies: where the enumerated types live, that emitting layers derive from
them rather than restating literals, that consumers import from the owning
module only, what makes a value enum-worthy as against legitimately free-form,
and the migration stance for values the dashboard consumes under the frozen edge
contract. That decision is not recorded here.

Two questions this audit found unowned should be settled by that record or
explicitly assigned elsewhere: whether an unreachable authoring backend should
degrade the service (F6), and whether every error is guaranteed to reach the
structured log (F15) - the latter has no owner anywhere in the corpus.

### Remediation grouping

Additive and unilateral, safe to land on this side of the edge: F1, F3, F10,
F11, F13, F14, F15, F26, F28, F36. Breaking, changing what a served field MEANS
and therefore requiring cross-repository coordination: F2, F4, F5, F6, F9, F12,
F35. Behavioural defects requiring investigation before a fix is specified: F16,
F17, F19, F20, F21, F22, F24, F25, F27, F31, F32, F33, F34. The delivery-path
cluster, which is the highest product impact in this document: F24, F25, F29,
F30. Closed by retraction: F8. Recorded as intended behaviour, not to be
"fixed": F38.

Two special cases must not be misread. F9 is execution of an already-ruled
amendment and needs no new decision, but it removes fields the dashboard
consumes and is therefore breaking. And coordination with the consuming
repository is the ROUTE for the breaking set, not a reason to defer it - a
served field that contradicts itself is not made acceptable by documenting the
contradiction.

F16's remedy no longer branches on the capability-gating question; that
hypothesis is refuted and the mechanism is F24's denial path. What remains
branch-dependent is F24 itself, whose first move is to dump the generated
provider configuration for a live run rather than to change policy blind.

### Two supporting facts worth preserving

The repository-root `openapi.json` and the live `/openapi.json` are IDENTICAL,
verified field-for-field: 19 paths each, same version, same specification
version. The artifact is guarded by
`src/vaultspec_a2a/api/tests/test_openapi_artifact.py`, which asserts valid
encoding, path completeness in both directions, version match, full
field-for-field equality against the freshly-built application, and the absence
of development-record references. It carries no marker, so it runs in the
default gate. Its regeneration path is the same file run as a script - and that
command is documented NOWHERE outside the test file, not in the contributing
guide, the development documentation, or the task runner. The strongest part of
this contract surface rests on a test nobody is told about.

Protocol conformance to the public agent-to-agent specification is NOT claimed
anywhere and was affirmatively rejected: `2026-02-27-agent-definition-schema-adr`
L298-303 rejected the well-known agent card on the grounds that the agents are
compiled graph nodes inside a single process, and both protocol records were
amended on 2026-07-15 to drop the ambition, stating that "a2a" survives as a
project label only. Six well-known and agent-card candidates were live-probed
and all 404 - correct behaviour, not an oversight. "Edge conformance" means
conformance to the private, frozen dashboard contract. The only residual issue
is that no published document tells an arriving reader the name is vestigial.
