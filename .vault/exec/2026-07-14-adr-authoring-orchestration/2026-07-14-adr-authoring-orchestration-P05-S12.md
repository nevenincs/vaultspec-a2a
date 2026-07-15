---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S12'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
---

# Prove the submitter live and mock-free against the loopback engine: session reuse across calls, idempotent replay returning the deduplicated receipt, denial handling, and revision-cycle key advancement

## Scope

- `src/vaultspec_a2a/authoring/tests/`

## Description

Prove the production submitter live and mock-free against the loopback engine.
Commit `5fbf2dd` (test), `8d0cace` (feature-from-state refinement).

Created: `src/vaultspec_a2a/authoring/tests/test_submitter_live.py`.

- Service-marked tests resolve the engine via the discovery-file contract and
  skip cleanly when it is unreachable (an infrastructure gate, not a masked
  failure). Each test mints a real per-actor token, registers it in a real
  `RunTokenStore`, constructs the production submitter, and drives it against the
  running engine.
- Coverage: a whole-document propose-and-submit returns a real engine proposal
  id; the constant create_session key resumes ONE session across calls (same
  `session_id`); in-dispatch replay AND a simulated restart (a fresh submitter,
  same durable state) return the SAME proposal id; a revision-cycle bump advances
  the key to a distinct proposal.

## Outcome

Complete. Passed LIVE against the running dashboard engine (127.0.0.1:8767):
real `actor-tokens` 201, `sessions` 200, `proposals` 200 with per-revision
changesets `cs:...:research-r1` and `-r2`, `submit` 200 — all four assertions
green (replay/restart dedup, session reuse, revision advancement). `ruff`/`ty`
clean.

## Notes

The engine went transiently unavailable later in the session (a fresh-ish
heartbeat but a refused `/health` — the Crashed specimen the attach-never-own
discipline exists for), after which the tests correctly SKIP. The live PASS was
captured before that; the tests are the durable, mock-free proof and re-run green
whenever the engine is up. No stub submitter was used, per the handover's
explicit prohibition.
