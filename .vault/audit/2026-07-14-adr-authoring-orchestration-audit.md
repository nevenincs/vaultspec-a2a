---
tags:
  - '#audit'
  - '#adr-authoring-orchestration'
date: '2026-07-14'
modified: '2026-07-15'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
  - "[[2026-07-14-adr-authoring-orchestration-adr]]"
---

# `adr-authoring-orchestration` audit: `P01-P04 partial code review`

## Scope

## Findings

## Recommendations

## Context

Formal vaultspec-code-review over the committed steps S01-S04, S07-S08, S09 (commits 2f2d2f8, 1573d80, ac50f67, f10b3e2, a9fd496, ad9d5e3, 5191c4d) plus adjacent f5f650d. STATUS: REVISION REQUIRED - no CRITICAL; one HIGH concurrency defect and one HIGH verification gap.

Suites run (all green): team+thread 124 passed; graph+authoring+control 172 passed (11 live deselected); database 14 passed.

HIGH-1 (blocking): api/app.py wires endpoint_provider=resolve_engine; verdict_subscriber.py:119 calls it synchronously on the gateway event loop; authoring/discovery.py:78 performs a blocking httpx.get(timeout=3.0) plus file read - stalls the shared loop up to ~3s per poll cycle. Mitigated today only by the default-off VAULTSPEC_AUTHORING_SUBSCRIBER_ENABLED flag. Fix: move the probe off-loop (asyncio.to_thread) or make it async.

HIGH-2 (environmental, not a code fix): the verdict-to-Command(resume)-to-parked-run hop is unproven live - the engine build emits only session.created (no proposal.*/approval.* outbox frames) and the run-parking gate topology (S05) had not landed at review time. Proven over real infra: SSE decode on the live wire, id correlation, cursor durability across restart. Keep P03 open for re-verification once S05 lands and the engine emits verdict events.

MEDIUM-1: _consume_page/_process_event/_handle_gap/_iter_recovery_proposals/_recovery_high_water (verdict_subscriber.py:148-408) lack direct coverage - add unit tests over synthetic recovery/gap payloads. MEDIUM-2: _find_parked_thread (verdict_subscriber.py:232-249) is O(N) checkpoint reads per verdict over up to 200 INPUT_REQUIRED threads - consider a proposal-id-to-thread index. MEDIUM-3: merge-ordering hygiene - the vaultspec-adr-research preset (5191c4d) landed before its TopologyType member, leaving main transiently unable to load it.

LOW: diverge.py:93-96 appends producer output without shape validation; worker.py _apply_queue_tool_calls loses the turn's current_task_id update if the follow-up ainvoke raises after mark_complete (self-heals via tool idempotency); lifecycle.py:218-224 request_changes is unrecoverable from a replay gap (no terminal changeset status) so a run stays parked until a live event; client.py SSE default 30s read timeout causes backoff churn on idle streams.

Verified solid: SSE stream/client cancellation-safe close and app shutdown cancel-and-gather; monotonic cursor with advance-after-process idempotent replay; contract pins consistent end to end ({"verdict","notes"} resume payload, research_findings {claim,locators,source_thread}, single-sourced verdict vocabulary); S01 add-only refresh off-thread and capped; S02 drain fully removed with Command(update) keyed by injected tool_call_id; f5f650d gate node deterministic pre-interrupt; tests mock-free and spec-derived.

Required before merge: fix HIGH-1; hold P03 verification open per HIGH-2. Recommended: MEDIUM-1/2/3 and LOW items.

### Delta review (S05 526a47e, S06 c056241, revision in 91a4c2a) - overall status now PASS

Both prior HIGH items resolved. HIGH-1 fixed and verified: `verdict_subscriber.py:120` dispatches the endpoint provider via `asyncio.to_thread`, so the blocking service-json read and health probe left the gateway event loop. MEDIUM-1 addressed with 10 non-tautological, mock-free tests (real `safe_dispatch` against a dead worker port; run stays INPUT_REQUIRED when resume fails). Prior LOW SSE read timeout fixed (`client.py:259`, `httpx.Timeout(None, connect=5.0)`).

S05 phase gate: safety PASS - only pre-interrupt side effect is the idempotent submitter call (`phase_gate.py:109`); unknown verdicts fail closed to revision (`:135-137`); replay-safety proven directly (submitter called with a stable proposal id on resume). S06 topology: safety PASS - full graph traced (dispatch -> Send fan-out -> synthesis -> review loops -> gates -> END), no dead ends or unreachable nodes; role/submitter config errors raised at compile.

New findings: MEDIUM (non-blocking, fails safe) - `_doc_review_router` matches the substring "REVISION" in the reviewer message, so prose like "no revision required" false-positives back to the writer; harden to the exact REVISION REQUIRED / PASS sentinel tokens before live model runs. LOW - inner quality loop is prose-only until engine ValidationFindings flow (P04.S10); research producer packs the whole response as one claim with empty locators; no bounded revision counter (stuck loops end via GraphRecursionError at recursion_limit 50 rather than gracefully).

Carried open: HIGH-2 environmental (engine emits only session.created; P03 live verdict-to-resume verification stays open until proposal/approval outbox emission lands engine-side); MEDIUM-2 O(N) checkpoint scan per verdict (scale note). MEDIUM-3 resolved by S06's enum. Verdict: safe to merge, with the sentinel hardening recommended before P04.S10 live runs.
