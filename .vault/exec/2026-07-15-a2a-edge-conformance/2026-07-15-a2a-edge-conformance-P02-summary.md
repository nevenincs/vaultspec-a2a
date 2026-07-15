---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - "[[2026-07-15-a2a-edge-conformance-plan]]"
---

# `a2a-edge-conformance` `P02` summary

Two steps promoted the gateway to full semantic transparency: run-status gained a product-safe authoring-phase projection so the Rust backend never needs to interpret LangGraph node names (S04), and the versioned SSE stream gained per-frame semantic-phase stamping with a structural audit confirming that secrets, tokens, prompts, and raw provider payloads are excluded by construction (S05). The S05 commit also absorbed a whole-vault hygiene normalization that unblocked all subsequent markdown commits.

- Modified: `src/vaultspec_a2a/control/thread_state_service.py`
- Modified: `src/vaultspec_a2a/api/routes/gateway.py`
- Modified: `src/vaultspec_a2a/api/schemas/gateway.py`
- Modified: `src/vaultspec_a2a/api/tests/test_gateway_live.py`
- Modified: `src/vaultspec_a2a/streaming/sse_frames.py`
- Modified: `src/vaultspec_a2a/streaming/tests/test_sse_frames.py`
- Modified: `src/vaultspec_a2a/graph/compiler.py`
- Modified: `src/vaultspec_a2a/providers/factory.py`
- Created: `src/vaultspec_a2a/control/tests/test_semantic_phase.py`
- Created: `src/vaultspec_a2a/providers/model_profiles.py`
- Created: `src/vaultspec_a2a/providers/tests/test_model_profiles.py`

## Description

S04 (017c2d3) added a pure `project_semantic_phase` function to `thread_state_service` that maps a run's terminal and recovery states first, then its research_adr checkpoint node position, into the product-safe authoring-phase vocabulary: the dispatch and researcher fan-out nodes map to `researching`, synthesis to `synthesizing_research`, the review nodes to `reviewing_research` / `reviewing_adr`, the gate nodes to `awaiting_research_decision` / `awaiting_adr_decision`, and the author node to `writing_adr`. Non-research_adr runs receive an honest generic `running` (or `starting` before dispatch) rather than fabricated precision. A transient checkpoint-unavailable posture on fresh dispatch is excluded from `recovery_required` — that is normal startup, not genuine checkpoint loss. A non-raising `SemanticContext` reader pulls the target feature and authoring session id from checkpoint channel values. `RunStatusResponse` gained `semantic_phase`, `feature_tag`, and `authoring_session_id`.

S05 (93af381 + 434e3ba) added `semantic_phase_for_node` to the SSE frame module, mapping the same research_adr structural nodes to phases and returning `None` for any non-research_adr node so no phase is fabricated. The phase is stamped at the single `encode_sse_frame` choke point, idempotently and only when genuinely known; heartbeats, terminals, and coder-run frames carry none. The mapping is documented as non-authoritative — run-status is the source of truth. A live-socket audit test proved a research_adr progress frame carries its phase on the wire and that a document-body-sized frame degrades to the `progress_dropped` sentinel rather than streaming the body verbatim, confirming the structural content exclusion holds. The S05 commit also carried a whole-vault hygiene normalization (lead-authorized): the prek vault-fix hook had been running a newer uvx-pinned vaultspec-core whose modified-stamp and annotation rules had drifted 159 Feb-Mar documents, re-firing and aborting every markdown commit. The fixer was run once and staged alongside S05 so the hook converges; the normalization is pure metadata, no content change. Attribution note: the 93af381 commit also carries the model-profiles MP P01 S02 step record and `providers/model_profiles.py` because those files were staged in the shared index alongside S05 by the concurrent MP executor.

## Verification

All scoped suites green at phase close: api and control (278 after S04, 293 after S05), streaming (frame unit tests for node mapping, stamping paths, non-research_adr and no-node cases, and idempotent passthrough). `ruff check`, `ruff format`, and `ty check` clean on all changed modules. No mocks. The vault-fix convergence fix is confirmed: subsequent markdown commits land without the hook re-firing on the Feb-Mar corpus.
