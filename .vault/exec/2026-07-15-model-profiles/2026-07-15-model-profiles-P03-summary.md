---
tags:
  - '#exec'
  - '#model-profiles'
date: '2026-07-15'
modified: '2026-07-15'
related:
  - "[[2026-07-15-model-profiles-plan]]"
---

# `model-profiles` `P03` summary

One step closed the plan: the handover live evidence battery (S05) ran net-new checks that the P02 gateway tests did not already cover, all against real production paths with no mocks. A reviewer-requested tautology removal (3d55191) narrowed the identity claim to its behavioral evidence, and the step checkbox closed on review PASS (5a2ddb2).

- Created: `src/vaultspec_a2a/api/tests/test_model_profiles_evidence.py`

## Description

S05 (24e502c initial battery, 3d55191 review revision, 5a2ddb2 checkbox) added `test_model_profiles_evidence.py` covering six net-new scenarios not already exercised by the P02 gateway tests, all against the real in-process gateway over a real TCP socket, the real durable SQLite thread store and `AsyncSqliteSaver` checkpointer, the real shared resolver and readiness probe, and real settings read from spawned process environments. No mocks, monkeypatch, stubs, or skips.

The six new tests:

- Frozen profile survives a genuine gateway restart: freeze on a first app instance, read run-status from a second app instance built on the same durable stores; the assignment is reproduced verbatim and nothing re-dispatches.
- Workspace config drift after launch does not mutate a running run: rewrite the workspace profile capability after freeze; run-status still discloses the frozen value.
- Discovery and launch resolve through the one canonical `resolve_effective_assignment` and disclose byte-identical per-role assignments for the same team and profile. The identity claim is carried behaviorally — the two live endpoints agree and the drift test confirms the launch side reads a frozen record; a same-module `is` assertion would be tautological (removed in 3d55191 per code review) and a call-count spy would require monkeypatching.
- Persisted run-metadata DB row carries the frozen profile but no actor token, bearer, or credential marker.
- Scrubbed-credential spawned process reports an unavailable provider with a safe, secret-free reason; injecting a credential into that same spawned process env flips readiness to ready, proving real settings are consulted rather than a monkeypatched constant. The spawned process runs with its working directory at an empty temp dir so pydantic-settings loads no repository `.env`, guaranteeing deterministic credential state regardless of the host developer's environment.
- A ready declared fallback makes an unready-primary role eligible over the real readiness probe; a no-fallback control role remains ineligible.

### Honest deferrals

Checkpoint secret-freedom is asserted at the DB-row level in this phase; graph checkpoints are only produced by a real graph run, which the in-process worker does not perform in these tests (only the dispatch is recorded). That coverage belongs to the P04.S10 acceptance run in the adr-authoring-orchestration plan, which owns the real Research → ADR execution on the served assignments; this phase references that evidence rather than duplicating it. Checkpoint-level secrecy verification is thus deferred to P04.S10.

The acceptance gate (`eligible=false` with a safe reason for every profile) remains open because P04.S10 has not yet passed. Eligibility is reported honestly throughout.

## Verification

7 new tests pass; full `api/tests` suite 194 passed. Reviewer PASS on 3d55191. `ruff check`, `ruff format --check`, and whole-tree `ty check` clean. No mocks.
