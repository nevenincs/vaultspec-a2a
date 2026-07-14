---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-14'
modified: '2026-07-14'
step_id: 'S16'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Implement session lifecycle (create authoring_session per run, turns, id cross-referencing into thread state) and proposal verbs (create, append, replace, submit, snapshot, conflicts, provenance, rebase) with idempotency keys derived from stable run-local material

## Scope

- `src/vaultspec_a2a/authoring/`
- `src/vaultspec_a2a/thread/`

## Description

Added the session-lifecycle and proposal-verb layer over the client, per ADR R3. The authoring session owns one session per run: it derives idempotency keys from stable run-local material (the run id, the command kind, and a per-command sequence, matching the LangGraph replay model), and drives the verbs create-session, start-prompt-turn, create-proposal, append-draft, replace-draft, submit-for-review, and rebase, plus the snapshot, conflicts, and provenance reads. The command discriminators were verified against the engine command-kind enum. Vaultspec ids the run produces are accumulated and exposed as thread-state references (D5, never document content) through new append-and-deduplicate team-state fields for the session id, changeset ids, and proposal ids. A helper mints a per-actor token through the bare bootstrap route.

- Modified: `src/vaultspec_a2a/authoring/__init__.py`, `src/vaultspec_a2a/thread/state.py`
- Created: `src/vaultspec_a2a/authoring/session.py`, `src/vaultspec_a2a/authoring/tests/test_session_unit.py`

## Outcome

Committed 8552f29, with a peer-review follow-up in 5bfa362. The review found that the proposal-id reference field was declared but never populated; a live probe showed the engine mints the review-facing proposal id at submit (the create-proposal receipt carries only changeset id and revision), so submit now captures it, and a scope-crept cancel verb whose route does not exist on the engine was removed. Guards and id validation fire before any HTTP. Unit tests cover the pure logic and guards; the verbs' live behaviour is the S17 deliverable. ruff, format, and ty all clean.

## Notes

The proposal-id gap and the non-existent cancel route were both surfaced by running against the live engine rather than trusting the source read — see the S17 record for the live corrections.
