---
tags:
  - '#exec'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:0dc3146226da13545a43aa60a7040136cf0fd59df1f81883f9296c57536951bb'
step_id: 'S01'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---

# Define normalized provider catalog, native-control, selection-reference, catalog-state, structured-health, and refresh-cache contracts

## Scope

- `src/vaultspec_a2a/providers/provider_catalog.py`
- `src/vaultspec_a2a/providers/tests/test_provider_catalog.py`

## Description

- Define immutable provider, catalog, model, native-control, selection, state,
  and structured-health records around opaque provider-issued values.
- Derive selectability from independent configuration, transport,
  authentication, catalog, and completed-turn admission evidence.
- Add canonical selection fingerprints for replay comparison.
- Add a bounded per-lane async single-flight TTL cache with generation-fenced
  invalidation that retains stale evidence when refresh fails.
- Exercise normalization, immutability, health derivation, replay identity,
  concurrent refresh coalescing, expiry, and failed-refresh retention through
  production imports.

## Outcome

Implemented the normalized S01 contract without concrete external model
identifiers or provider policy. Ten focused tests passed. Ruff, `ty`, and strict
basedpyright passed for the implementation and its direct tests. Formal review
findings covering immutability, invalidation concurrency, and resource bounds
were classified, remediated, and retained in the audit queue.

## Notes

Semantic discovery was temporarily unavailable because RAG compute admission
was quiesced. Grounding continued through the plan's explicit source target,
the accepted ADR, Research, Reference, and targeted exact-symbol inspection.
