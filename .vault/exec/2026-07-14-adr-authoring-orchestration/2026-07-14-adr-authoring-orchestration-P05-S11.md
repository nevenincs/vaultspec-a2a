---
tags:
  - '#exec'
  - '#adr-authoring-orchestration'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S11'
related:
  - "[[2026-07-14-adr-authoring-orchestration-plan]]"
---

# Implement the production DocumentProposalSubmitter in the authoring package with rag-first discovery of every touched seam, conforming to the phase-gate Protocol (async call of state and phase returning the proposal id) and backed by AuthoringSession: create-or-resume session, whole-document create/populate/validate/submit, idempotency keys from thread id plus phase plus document kind plus revision cycle, denials as values, role token read from RunTokenStore at call time

## Scope

- `src/vaultspec_a2a/authoring/submitter.py`

## Description

Implement the production `DocumentProposalSubmitter` (ADR PW1), backed by
`AuthoringSession`. Commits `796ee7a`, `2d4b130`, `8d0cace`.

Created: `src/vaultspec_a2a/authoring/submitter.py`.
Modified: `src/vaultspec_a2a/authoring/__init__.py`,
`src/vaultspec_a2a/authoring/session.py`.

- The submitter conforms to the phase-gate Protocol (async call of state and
  phase returning the proposal id): reads the phase author's latest named
  `AIMessage` for the document body and the revision cycle (message count), reads
  the machine bearer and the calling role's actor token from `RunTokenStore` at
  call time (holds no token, R7), and does the engine-proven whole-document
  create-or-resume flow (create_session -> create_proposal -> submit) returning
  the proposal id. `active_feature` is read from state at call time (the graph is
  cached across runs). A typed fail-closed error family (engine unavailable,
  role/config invalid, credentials missing, document unavailable, denial-as-value)
  surfaces truthful failures, never silent skips.
- Team-lead ruling (option 1): to make ONE session per run restart-safe, an
  additive optional `idempotency_key` parameter was added to every mutating
  `AuthoringSession` method (backward-compatible; the per-command sequence
  behaviour is unchanged when omitted). The submitter keys create_session on a
  constant run-local value (create-or-resume, reused across research+adr) and each
  proposal/submit on `thread_id + phase + command + revision`, so a restarted
  worker resuming past the research gate reproduces byte-identical keys — no
  duplicate session, changeset, or proposal.

## Outcome

Complete. `ruff`/`ty` clean; the authoring unit suite (session + submitter) is
green and backward-compatible. Pure-logic probes confirmed document extraction,
constant-vs-per-phase key determinism, and the full fail-closed taxonomy. The
engine-observed proof is S12.

## Notes

The engine-proven op shape (`create_document` / `provisional_create` /
`whole_document`) was lifted from the existing `test_live_engine.py`, so nothing
was guessed. The document-role keys used for `RunTokenStore` lookup
(`synthesist`, `adr-author`) are the presumed engine bundle keys for the
research_adr roles; they are confirmed end to end only by the P04.S10 live run,
where the engine actually provisions the per-role bundle.
