---
tags:
  - '#audit'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:9d0b0e06f17a00fc65d1810cac94c84a1832dac3034cbbf95f0320c9a74fa8f7'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---
# `provider-model-catalog` audit: `P02.S16 dashboard provider health review`

## Scope

Reviewed P02.S16 Dashboard provider-health presentation and selection integrity against the accepted provider-model-catalog contract. The scope includes the independent health axes, independent health and catalog freshness timestamps, safe served reasons, localization, and the adapter and local TCP transport proofs that keep unsafe catalog entries unselectable.

## Findings

### catalog-axis-freshness-collapse | medium | Initial disclosure hid a contradictory catalog health axis

The first P02.S16 draft presented catalog freshness as the catalog health fact, so an A2A response with `health.catalog` available and a stale catalog state lost one independent piece of evidence. Remediated before review by rendering both separately, including a direct render proof for the contradictory payload and the served freshness timestamps and reason.

### stale-freshness-selectability | medium | A stale catalog state could retain browser aggregate selectability

Focused adapter coverage found that a served `selectable: true` survived when the independent catalog health was available but the catalog state was stale. Remediated by deriving aggregate browser selectability through the freshness state while retaining both served facts for display; the selection minting proof now fails closed for that contradiction.

### health-probe-timestamp-omission | medium | The health evidence timestamp was not independently disclosed

Independent review found that the initial disclosure showed the catalog check and expiry but omitted `health.checked_at`, allowing different health and catalog probe times to be conflated. Remediated by adding a separately localized health-check fact and a contradictory-timestamp render proof; the local TCP transport proof preserves both timestamps.

### expiry-time-selectability | medium | A catalog could remain selectable after its served freshness deadline

Independent review found that available status alone was insufficient: malformed, expired, absent, or chronologically invalid freshness timestamps could continue to mint selections. Remediated with a pure injectable current-time selection guard requiring valid `checked_at` and `expires_at`, strict expiry ordering, and current time before expiry. The picker schedules one real-timer rerender at the earliest served expiry; its render proof verifies the disabled transition without fake timers or patched clocks.

### formatter-closure-gate | medium | Changed provider-health paths did not satisfy the repository formatter

Closure review found that the exact changed-path Prettier check failed. Remediated by running the repository-pinned formatter over exactly the five provider-health paths and retaining the scoped whole-file result after inspection confirmed it contained only committed baseline formatting and P02.S16 changes.

### render-clock-consistency | medium | Selection mutation paths did not share the rendered freshness instant

Closure review found that model-click and native-control mutation revalidated with a newly read clock rather than the instant that produced the visible selectable state. Remediated by passing the render-captured `now` through model selection and control mutation, including the extended `selectionWithCatalogControl` guard.

### freshness-negative-proof-coverage | medium | Individual absent and malformed timestamp refusals lacked isolated tests

Closure review found that the general malformed and expired loop did not independently prove missing `checked_at`, missing `expires_at`, and malformed `checked_at` against an otherwise selectable lane. Remediated with separate direct selection and selectability tests for each refusal case.

### closure-gate-timeout | medium | The reviewer test command timed out without a valid proof boundary

Closure review reported its seven-file Vitest command ended after about 55 seconds without captured output, so the attempted gate was not evidence. Remediation is to run the known repository-focused command separately under an explicit timeout and retain its full result below as the only post-fix test proof.

## Recommendations

Final independent closure review returned PASS with no new findings. All recorded P02.S16 findings are remediated; no open implementation recommendation remains.
