---
tags:
  - '#exec'
  - '#clarification-decline'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:249685b27681f7bfcb11c9b6d75fddc808cc375411be69ea3a9cc248605a65d1'
step_id: 'S03'
related:
  - "[[2026-08-02-clarification-decline-plan]]"
---

# Prove contract boundaries and the real worker decline loop

## Scope

- `src/vaultspec_a2a/thread/tests/test_clarification.py`
- `src/vaultspec_a2a/graph/tests/nodes/test_clarification.py`
- `src/vaultspec_a2a/api/tests/test_clarification_loop_live.py`

## Description

- Prove the decline round-trips the strict parser, refuses smuggled payload keys, and binds to the committed request id.
- Prove the fixed marker is line-safe and within the prompt ceiling.
- Prove the decline fingerprint is distinct from every answer and continuation fingerprint.
- Prove the schema's exactly-one-of-three rule including the literal-true constraint through the wire validation path.
- Prove over a real StateGraph and checkpointer that a decline leaves one marker, no answer entry, a receipt, and cleared pending state.
- Prove the full gateway, worker app, Executor, and resume loop settles a declined run terminally with the marker in durable graph state.

## Outcome

Contract, schema (18 passed), graph node (90 passed across the touched suites),
and live worker loop (4 passed) suites are green; `ruff check`, `ruff format
--check`, and the gating `ty check` report zero findings on the repository's
Python paths.

## Notes

`just lint` currently fails on three pre-existing import-placement findings in
a provider catalog live test owned by a concurrent lane; the finding is outside
this feature's scope and left untouched. The strict basedpyright dimension
remains a repository-wide burndown backlog and is not part of the gating chain.
