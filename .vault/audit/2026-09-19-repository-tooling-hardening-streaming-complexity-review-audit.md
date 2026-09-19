---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-09-19'
modified: '2026-09-19'
body_schema: 'body-v2'
body_hash: 'sha256:20b844bebc477abc413c9198de1df7f42fd9c874799aeea2de3af61cb4e3f067'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---
# `repository-tooling-hardening` audit: `streaming complexity reduction review`

## Scope

Reviewed the stream transformer changes against the event and progress contracts in the accepted repository-tooling and codebase-health decisions. The review traced chat-model content, additional reasoning, model end, and chain-end plan and artifact projection through the real aggregator. `just check-all`, `just check-type-strict`, and 76 focused streaming tests pass. The health census moved from 162 to 160 cyclomatic findings, 119 to 116 parameter findings, and 9 to 7 nesting findings.

## Findings

### stream-event-order | low | chain-end and chunk emissions retain their order

Type: behavioral regression. Status: RESOLVED. The refactor retains tool-call registration before chunk content, emits content-block reasoning or text in input order, leaves additional reasoning excluded for list content, flushes at model end, and emits the chain idle status before plan and artifact updates. The direct characterization tests and real aggregator tests pass. No regression finding remains in the changed event paths.

### remaining-streaming-structure | medium | translator and ingest hotspots remain

Type: maintainability. Status: OPEN. The changed translator no longer contributes the two former nesting findings, but the strict Ruff scan still finds seven shape and complexity diagnostics in `streaming/transformer.py`, including the tool-end translator and the public dispatcher. `streaming/ingest.py` also remains over the accepted complexity and nesting limits. Repository-tooling-hardening plan W07.P13.S31 remains open until both files reach the stated thresholds with stream regression evidence. The full strict aggregate remains red; no threshold or exclusion was changed.

### provider-failure-condition | high | ACP initialization failure is served as unknown

Type: behavior/test contract. Status: OPEN. A broader aggregator selection ran 73 tests; four provider-condition tests failed because the scripted ACP initialize response lacks a usable protocolVersion, yielding provider condition `unknown` where the tests expect a classified refusal. This failure is outside the changed transformation branches and needs an end-to-end provider condition investigation before the suite can be green. The 76 stream-specific tests passed when the two affected provider-condition classes were excluded from the focused regression run.

### provider-failure-condition-closeout | low | ACP simulator negotiates protocol version 1

Type: test contract. Status: RESOLVED. The simulator response in
src/vaultspec_a2a/graph/tests/acp_simulator.py omitted protocolVersion.
The production client correctly rejected the missing negotiation before
session/prompt, so the four failures never exercised their intended provider
refusal. The real subprocess now returns protocolVersion 1, matching the
request and accepted ACP negotiation contract. All five provider-condition
tests pass, and the full aggregator plus worker integration selection passes
79 tests. The failure assertions were not weakened.

## Recommendations

Continue W07.P13.S31 on the remaining translator and ingest hotspots. Re-run the full non-service suite and strict aggregate before promoting any sentinel or marking the Step complete.
