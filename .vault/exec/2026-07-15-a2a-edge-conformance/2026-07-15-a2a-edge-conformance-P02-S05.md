---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S05'
related:
  - "[[2026-07-15-a2a-edge-conformance-plan]]"
---

# Carry the semantic phase in versioned SSE progress frames and audit frame content against the handover exclusions: no secrets, prompts, document bodies, tokens, or raw provider payloads

## Scope

- `src/vaultspec_a2a/streaming/`
- `src/vaultspec_a2a/api/tests/`

## Description

- Added a semantic_phase_for_node helper to the SSE frame module mapping the
  research_adr structural nodes (dispatch/researcher fan-out, synthesis, the two
  reviews, and the two gates) to the product-safe phase vocabulary, returning
  None for any non-research_adr node so no phase is fabricated.
- Stamped semantic_phase onto every progress frame at the single encode choke
  point: a frame naming a research_adr node (by node_name, falling back to
  agent_id) carries its phase, idempotently and only when genuinely known, while
  heartbeats, terminals, and coder-run frames carry none.
- Documented that the mapping mirrors the authoritative run-status projection
  vocabulary and is duplicated in the streaming layer to avoid a control-layer
  import, keeping run-status the source of truth and these frames
  non-authoritative.
- Added frame unit tests for the node mapping, the node_name and agent_id
  stamping paths, the non-research_adr and no-node cases, and the idempotent
  passthrough of a pre-set phase.
- Added a live-socket audit test proving a research_adr progress frame reaches
  the wire carrying its semantic phase, and that a document-body-sized frame is
  bounded: it degrades to the droppable progress_dropped sentinel rather than
  streaming the body verbatim.

## Outcome

- The versioned SSE stream now carries the semantic authoring phase on progress
  frames, and the handover's content exclusions hold: document bodies are bounded
  by the frame cap to a droppable sentinel, and the transformer surfaces only
  safe node/state/role and truncated tool metadata - actor tokens, prompts, and
  raw provider payloads never enter graph events and so never reach a frame.
- Scoped suites green: streaming and api (293); `ruff check`, `ruff format`, and
  `ty check` clean.

## Notes

- The content audit is enforced structurally rather than by a per-field filter:
  the frame source (the LangGraph event transformer) extracts only safe fields
  and truncates tool output, actor tokens live only in worker-scoped memory and
  are never checkpointed or emitted, and the hard per-frame byte cap bounds any
  large body to a sentinel. The audit test asserts the bounding and the phase on
  the wire; the token/prompt exclusion is by construction (they are absent from
  the event stream the transformer reads).
- A concurrent session reshaped TopologyPosition (dropped next_nodes for
  role-vocabulary, PW4) and integrated the P02.S04 semantic_phase wiring cleanly;
  this Step touched only the streaming layer and its tests, so it did not
  interact with that change.
- This commit also sweeps a whole-vault hygiene normalization (authorized by the
  lead): the prek vault-fix hook runs a newer uvx-pinned vaultspec-core whose
  rules had drifted 159 Feb-Mar docs (a modified-stamp and annotation refresh),
  which re-fired and aborted every markdown commit and could not be landed
  separately while this Step's record sat staged in the shared index. Ran the
  hook's own fixer once and staged the normalization alongside the S05 change so
  the hook converges; the normalization is pure metadata, no content change.
