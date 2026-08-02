---
tags:
  - '#plan'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_hash: 'sha256:5a0446a42648e767f83f4a943af295daebdad451d4ea911057100ce6b684ffac'
tier: L3
related:
  - '[[2026-08-02-provider-error-taxonomy-adr]]'
  - '[[2026-08-02-provider-error-taxonomy-research]]'
---

# `provider-error-taxonomy` plan

Recover the provider condition the wire already carries, serve it typed, and render it.

## Description

Executes `2026-08-02-provider-error-taxonomy-adr` across two repositories, grounded
in `2026-08-02-provider-error-taxonomy-research`. The ADR governs both Waves: W01
delivers the a2a backend contract, W02 consumes it in the dashboard.

The ordering is set by the ADR's own de-risking sequence. Nothing can be classified
until the provider exception survives the worker-node wrapper and the ingest
summarizer, so cause preservation comes first and delivers a truthful free-text
reason on its own. The ZAI fidelity probe sits early because the ADR gates that
lane's typing on live evidence rather than on the shared adapter. Vocabulary and
per-lane mapping follow, then durable carriage onto `run-status`, then
recoverability and retry, then the blank-terminal closure that the ADR brought into
scope. Live proof closes W01 and is the precondition for W02.

## Steps

## Wave `W01` - a2a typed provider conditions

Delivers the backend half end to end: the provider exception survives to the reporting site, each served lane maps its own wire discriminator into one closed condition vocabulary, the condition is persisted and served authoritatively on run-status, recoverability becomes a consequence of the condition rather than of the catch site, and every path that fails a run records one. Backed by the provider-error-taxonomy ADR and research. W02 consumes this Wave and cannot begin until the vocabulary is frozen and proven live.

### Phase `W01.P01` - preserve the provider cause

Restores a truthful failure reason by stopping the worker-node wrapper and the ingest summarizer from discarding the provider exception's identity.

- [x] `W01.P01.S01` - Retain the provider exception type, message, and code on the worker wrapper; `src/vaultspec_a2a/graph/nodes/worker.py`.
- [x] `W01.P01.S02` - Name the resolved provider lane and model id instead of the model class; `src/vaultspec_a2a/graph/nodes/worker.py`.
- [x] `W01.P01.S03` - Walk the cause chain in the ingest exception summarizer; `src/vaultspec_a2a/streaming/ingest.py`.
- [x] `W01.P01.S04` - Prove a provider exception's identity survives to the failure reason through real ingest; `src/vaultspec_a2a/streaming/tests/test_aggregator.py`.

### Phase `W01.P02` - condition vocabulary and per-lane mapping

Establishes the closed condition vocabulary, proves the ZAI lane's discriminator fidelity live, and gives each served lane a total pure mapping from its own wire vocabulary into it.

- [x] `W01.P02.S05` - Capture a live ZAI error payload and record the discriminator fidelity verdict; `src/vaultspec_a2a/providers/tests/test_zai_error_fidelity_live.py`.
- [x] `W01.P02.S06` - Declare the closed provider condition vocabulary; `src/vaultspec_a2a/providers/conditions.py`.
- [x] `W01.P02.S07` - Map the ACP error kind and JSON-RPC code onto the vocabulary; `src/vaultspec_a2a/providers/conditions.py`.
- [x] `W01.P02.S08` - Map the Codex error info variants onto the vocabulary; `src/vaultspec_a2a/providers/conditions.py`.
- [x] `W01.P02.S09` - Attach the resolved condition to the ACP prompt error at raise; `src/vaultspec_a2a/providers/acp_chat_model.py`.
- [x] `W01.P02.S10` - Attach the condition and the lane retry hint to the Codex error at raise; `src/vaultspec_a2a/providers/codex_chat_model.py`.
- [x] `W01.P02.S11` - Consume the populated Codex turn error instead of the bare status string; `src/vaultspec_a2a/providers/codex_chat_model.py`.
- [x] `W01.P02.S12` - Prove each lane mapper is total over its installed wire vocabulary; `src/vaultspec_a2a/providers/tests/test_conditions.py`.

### Phase `W01.P03` - durable carriage onto run-status

Carries the condition on the error frame, persists it beside the failure reason, and projects it authoritatively onto run-status so a reloading client recovers it.

- [x] `W01.P03.S13` - Emit the resolved condition as the error frame code; `src/vaultspec_a2a/streaming/ingest.py`.
- [x] `W01.P03.S14` - Carry the condition on the terminal status payload; `src/vaultspec_a2a/worker/state_projection.py`.
- [x] `W01.P03.S15` - Declare the provider condition column on the thread model; `src/vaultspec_a2a/database/models.py`.
- [x] `W01.P03.S16` - Add the provider condition migration revision; `src/vaultspec_a2a/database/migrations/versions`.
- [x] `W01.P03.S17` - Persist the condition alongside the failure reason on the terminal write; `src/vaultspec_a2a/database/thread_repository.py`.
- [ ] `W01.P03.S18` - Align the failure reason bound to the consumer byte limit; `src/vaultspec_a2a/database/thread_repository.py`.
- [ ] `W01.P03.S19` - Thread the condition through the gateway terminal event handler; `src/vaultspec_a2a/control/event_handlers.py`.
- [ ] `W01.P03.S20` - Read the condition into the thread state snapshot; `src/vaultspec_a2a/control/thread_state_service.py`.
- [ ] `W01.P03.S21` - Declare the condition on the domain snapshot dataclass; `src/vaultspec_a2a/api/schemas/snapshots.py`.
- [ ] `W01.P03.S22` - Declare the condition on the run-status response schema; `src/vaultspec_a2a/api/schemas/gateway.py`.
- [ ] `W01.P03.S23` - Project the condition onto the run-status response; `src/vaultspec_a2a/api/routes/gateway.py`.
- [ ] `W01.P03.S24` - Prove the condition survives a reload through run-status alone; `src/vaultspec_a2a/api/tests/test_internal.py`.
- [ ] `W01.P03.S58` - Project the repair reason onto the run-status response; `src/vaultspec_a2a/api/routes/gateway.py`.

### Phase `W01.P04` - recoverability and retry

Derives the recoverable flag from the condition rather than the catch site and binds the same classification to the node retry policy.

- [ ] `W01.P04.S25` - Derive the recoverable flag from the condition instead of the catch branch; `src/vaultspec_a2a/streaming/ingest.py`.
- [ ] `W01.P04.S26` - Bind the condition to the node retry classifier; `src/vaultspec_a2a/graph/compiler.py`.
- [ ] `W01.P04.S27` - Prefer a lane-supplied retry hint over inferred retryability; `src/vaultspec_a2a/graph/compiler.py`.
- [ ] `W01.P04.S28` - Prove throttled and overloaded conditions retry under the existing backoff policy; `src/vaultspec_a2a/graph/tests/test_compiler.py`.

### Phase `W01.P05` - close the blank terminals

Guarantees every path that fails a run records a condition, emits a terminal, and survives reconnect and backpressure.

- [x] `W01.P05.S29` - Record a condition and reason on the shared dispatch failure transition; `src/vaultspec_a2a/control/repair_transitions.py`.
- [x] `W01.P05.S30` - Pass the dispatch failure reason from run creation; `src/vaultspec_a2a/control/thread_service.py`.
- [x] `W01.P05.S31` - Record a durable reason where an undelivered follow-up settles; `src/vaultspec_a2a/control/message_service.py`.
- [x] `W01.P05.S32` - Pass the dispatch failure reason from permission resume; `src/vaultspec_a2a/control/permission_service.py`.
- [ ] `W01.P05.S33` - Record a durable reason when a clarification resume is not delivered; `src/vaultspec_a2a/control/clarification_service.py`.
- [x] `W01.P05.S34` - Emit a terminal from the executor top-level dispatch handler; `src/vaultspec_a2a/worker/executor.py`.
- [x] `W01.P05.S35` - Record a condition on the missing-graph rejection; `src/vaultspec_a2a/worker/executor.py`.
- [x] `W01.P05.S36` - Record a condition on the ingest and resume catch-alls; `src/vaultspec_a2a/worker/executor.py`.
- [ ] `W01.P05.S37` - Emit an error frame on compile refusal; `src/vaultspec_a2a/worker/executor.py`.
- [ ] `W01.P05.S38` - Carry status and condition on the terminal replay frame; `src/vaultspec_a2a/api/thread_stream.py`.
- [ ] `W01.P05.S39` - Protect terminal and error frames from backpressure eviction; `src/vaultspec_a2a/streaming/fanout.py`.
- [ ] `W01.P05.S40` - Prove no failed run persists without a condition across dispatch and executor paths; `src/vaultspec_a2a/api/tests/test_internal.py`.

### Phase `W01.P06` - cleanup and live proof

Removes the superseded dead vocabulary and proves a real provider failure surfaces a typed condition end to end on a served lane.

- [ ] `W01.P06.S41` - Remove the dead severity and recovery-action vocabulary; `src/vaultspec_a2a/thread/errors.py`.
- [ ] `W01.P06.S42` - Withdraw the removed vocabulary from the thread package surface; `src/vaultspec_a2a/thread/__init__.py`.
- [ ] `W01.P06.S43` - Replace the usage-limit substring sniff with the typed condition; `src/vaultspec_a2a/service_tests/test_claude_web_grounding_live.py`.
- [ ] `W01.P06.S44` - Add a scripted failure scenario preset for the integration-verification ask; `src/vaultspec_a2a/team/presets/teams`.
- [ ] `W01.P06.S45` - Prove a live provider failure surfaces a typed condition end to end; `src/vaultspec_a2a/service_tests/test_provider_condition_live.py`.

## Wave `W02` - dashboard condition surfacing

Consumes the served condition in the dashboard repository: the engine models and validates it on a failed run, the adapter reads it from run-status, and the agent panel maps each member to its own remediation affordance without ever parsing the reason string. Backed by the same ADR, and authored against the vocabulary W01 froze.

### Phase `W02.P07` - engine models the condition

Teaches the dashboard engine to model, validate, persist and forward the condition on a failed run, so the frontend has an authoritative field to read.

- [ ] `W02.P07.S46` - Declare the provider condition on the run record type; `engine/crates/vaultspec-api/src/authoring/session/types.rs`.
- [ ] `W02.P07.S47` - Validate the condition against the closed vocabulary; `engine/crates/vaultspec-api/src/authoring/session/validate.rs`.
- [ ] `W02.P07.S48` - Persist and read back the condition on a failed run; `engine/crates/vaultspec-api/src/authoring/session/mod.rs`.
- [ ] `W02.P07.S49` - Forward the condition on the a2a ops route; `engine/crates/vaultspec-api/src/routes/ops/a2a.rs`.
- [ ] `W02.P07.S50` - Prove the condition round-trips through the session store; `engine/crates/vaultspec-api/src/authoring/session/tests.rs`.

### Phase `W02.P08` - adapter and panel surfacing

Carries the condition from the a2a payload through the stores into the agent panel, with one localized message and one remediation affordance per member.

- [ ] `W02.P08.S51` - Read the condition from the a2a run-status payload; `frontend/src/stores/server/agent/a2aTeam.ts`.
- [ ] `W02.P08.S52` - Carry the condition through the relay adapter; `frontend/src/stores/server/liveAdapters/a2aRelay.ts`.
- [ ] `W02.P08.S53` - Expose the condition on the agent panel view store; `frontend/src/stores/view/agentPanel.ts`.
- [ ] `W02.P08.S54` - Add one localized message key per condition member; `frontend/src/localization/catalogAgentKeys.ts`.
- [ ] `W02.P08.S55` - Render a distinct remediation affordance per condition; `frontend/src/app/agent/AgentPanel.tsx`.
- [ ] `W02.P08.S56` - Prove the panel renders each condition without parsing the reason string; `frontend/src/app/agent/AgentPanel.render.test.tsx`.

### Phase `W02.P09` - cross-repo live proof

Proves a real provider failure raised in a2a renders as its typed condition in the running dashboard.

- [ ] `W02.P09.S57` - Prove a real a2a provider failure renders its condition in the panel; `frontend/src/stores/server/agent/a2aTeam.live.test.ts`.

## Parallelization

Waves are strictly sequenced: W02 consumes a vocabulary W01 must first freeze and
prove, and starting it earlier would author against a moving contract.

Within W01, P01 and P02 are partially parallel - the ZAI probe carries no code
dependency on cause preservation and can run alongside it - but every later Phase
depends on P02 having frozen the vocabulary. P03 and P04 both consume the condition
and may proceed in parallel once P02 lands, since they touch disjoint surfaces
(persistence and projection versus retry classification). P05 is independent of P03
and P04 in mechanism but must land before P06, because the live proof asserts that
no failed run lacks a condition. P06 is strictly last in W01.

Within W02, P07 must land before P08 (the panel cannot read a field the engine does
not model), and P09 is strictly last.

## Verification

- Every Step closed.
- Whole-tree `ruff format --check src`, `ruff check src`, and `ty check` clean, run
  from the repository root rather than scoped to changed files.
- The full non-service suite passes, reported with its exact command and totals.
- A provider exception's type and message reach `failure_reason` end to end, proven
  by a test that drives a real exception through real ingest rather than asserting on
  a constructed string.
- Each lane's condition mapper is total over its own wire vocabulary, proven by a
  test enumerating that vocabulary from the installed adapter rather than from a
  hand-copied list.
- A failed run's condition survives a reload, proven through `run-status` alone with
  no live stream attached.
- The conditions the ADR classifies retryable actually retry under the existing node
  backoff policy, proven by observing repeated attempts rather than by asserting on
  the classifier in isolation.
- No failed run persists with a null condition, proven across the dispatch-failure
  and executor-rejection paths as well as the ingest path.
- A live provider failure surfaces its typed condition end to end on a served lane.
- The dashboard panel renders a distinct remediation per condition and parses no
  reason string, proven by a test that would fail if the string were consulted.
- Formal code review against the implementation before any Step is marked complete.
