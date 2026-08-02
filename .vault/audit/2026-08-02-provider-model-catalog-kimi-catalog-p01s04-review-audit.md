---
tags:
  - '#audit'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:20cd11edfb42e2888e54b5239c9d3ce17632c4263d4cda71e66efe13290e777f'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---
# `provider-model-catalog` audit: `Kimi catalog P01.S04 review`

## Scope

Review of `P01.S04`: prompt-free Kimi configured-lane alias and thinking-control discovery, including parser normalization, secret exclusion, bounded subprocess output, cancellation cleanup, and the installed CLI boundary.

## Findings

### kimi-catalog-p01s04-review | low | No implementation finding in the reviewed step

The configured-alias parser refuses malformed tables, unknown provider references, duplicate efforts, and bounded-output violations before constructing a catalog. It retains aliases, capabilities, and advertised thinking efforts while excluding credentials and raw wire model identifiers. Separate installed-CLI proofs enumerate a documented temporary configured lane and truthfully report the ambient unconfigured lane as unavailable, both without a model prompt. Child processes are reaped on normal, failure, timeout, cancellation, and aggregate-output-boundary paths.

### kimi-real-process-coverage | medium | Initial subprocess proof exercised only stdout success

Resolved before closure. Real spawned processes now write above typical pipe capacity to both stdout and stderr, breach the shared one-MiB budget across both streams, and hang past the configured timeout. Tests assert the exact static budget error where applicable and complete process-tree reaping. Independent closure re-review returned PASS with no remaining S04 implementation findings.

### execution-mode-admission | high | Provider-only admission can transfer proof across distinct runtimes

Completed-turn proof is currently keyed only by provider identity although catalog, authentication, and enforcement semantics are execution-mode-specific. A completed turn through one runtime could therefore authorize a distinct runtime without evidence. The admission declaration must be keyed by the same provider-and-execution-mode identity carried by catalog selections.

### exact-selection-evidence | high | A successful response does not prove the selected catalog value was honored

A lane-admission proof must observe the frozen current selection at its provider-specific enforcement seam before sending the prompt, then receive non-empty real model output. A cross-provider tier label or a pre-spawn metadata assertion is not sufficient evidence.

### static-tier-retirement | high | Transitional static model tiers remain outside the accepted product contract

The accepted catalog decision rejects universal tier inference and repository-authored external model identifiers for new runs. Remaining static model mapping and low-tier test assumptions must be retired as the frozen catalog-selection path lands; test spend policy may choose a current inexpensive catalog entry but cannot reintroduce a product-wide tier.

### missing-per-lane-admission-steps | medium | The current plan lacks explicit proofs for every external execution lane

The generic integration proof does not require separate selected-model completed turns for Gemini, Kimi, OpenAI, Zhipu, and Z.ai. Add independently credential-gated lane proofs and retain unavailable lanes as unselectable until their proof completes.

### zai-admission-precondition | medium | Explicit admission proofs must fail on missing prerequisites

The existing Z.ai proof uses a skipped result when its token is absent. An explicitly invoked admission certification must fail with the safe missing-precondition reason instead of reporting a skipped verification as success.

## Recommendations

- Preserve an unconfigured Kimi lane as unavailable and keep every Kimi lane unadmitted until a completed real selected-model turn proves that exact execution lane.
- In later selection-to-launch work, pass the served Kimi alias through the documented CLI selection surface; do not restore an environment-only model assumption.
- Key admission by provider catalog identity, add explicit per-lane selection-and-turn proofs, and remove transitional static tier authority in the planned catalog migration.
