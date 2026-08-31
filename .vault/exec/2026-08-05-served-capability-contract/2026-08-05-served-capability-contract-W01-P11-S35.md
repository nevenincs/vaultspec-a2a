---
tags:
  - '#exec'
  - '#served-capability-contract'
date: '2026-08-05'
modified: '2026-08-05'
body_schema: 'body-v1'
body_hash: 'sha256:1d43e7e6e54c2d88d4622cc8c8053736b9aabcc405b5585c58f8d6c01330a1b9'
step_id: 'S35'
related:
  - "[[2026-08-05-served-capability-contract-plan]]"
---

# F30 DONE in commit cb7f856e - approval forwarding wired through the engine decision and apply verbs, proven by a real document reaching disk. NOTE the phase does NOT close on this: delivery works for callers inside this repository and for nobody else, because no REST proxy exposes those verbs to the frontend. That gap is F57

## Scope

- `src/vaultspec_a2a/authoring/session.py`

## Description

- Wire the engine's review-decision and apply verbs behind the approval path so
  an approved proposal advances the engine's ledger rather than only resuming
  the graph.
- Drive the campaign's surviving evidence proposal through that path.

## Outcome

Closed, and it is the first time in this campaign that anything reached disk.

The proposal driven through was not a fresh test fixture: it is the ACTUAL
evidence artifact from the six live runs - the one that sat at needs-review and
queued, and could never become a file. It was approved and applied through the
new production path, and a real document now exists on disk with real content,
real code locators, two options compared with one rejected and the reason
given, an open gap and sources. Verified independently as content rather than
scaffold.

THE RETRY PROOF IS THE PART WORTH KEEPING. It asserted the file's modification
timestamp UNCHANGED and its content byte-identical after a second apply under
the same idempotency key - not merely that a matching receipt came back. That
distinction is the whole difference between a drift guard and a real proof:
a matching receipt shows the key was stable, while an unchanged file shows the
ENGINE deduplicated. Only the second closes the question, because the engine is
what deduplicates.

Two failure modes were proven live and kept distinguishable rather than
collapsed into one error: an in-domain denial for self-approval, and a typed
conflict for a stale revision fence.

## Notes

CORRECTION - THE REACHABILITY CAVEAT ORIGINALLY RECORDED HERE IS RETRACTED. This
record first said the capability was reachable inside this repository and by
nobody else, citing a finding that has since been withdrawn. The consuming
frontend reaches the engine's review and apply verbs DIRECTLY, so the human
delivery path was complete before this campaign began.

What this Step actually delivered, stated correctly: a SECOND consumer of those
same engine verbs - a programmatic path for this service with no human at a
browser, which genuinely did not exist. That is a real capability and a real
first. It is a narrower claim than the one originally recorded here, and the
work is not diminished by the correction - only the reachability framing around
it was wrong.

The phase still does not close on this Step alone: the engine content gap behind
the review-body question is unresolved and needs verifying through the
consuming client rather than through a declaration.

THE PROOF ARTIFACT, captured here because the file itself is deliberately
untracked. Path `.vault/research/2026-08-05-mantest-probe-research.md`, 1900
bytes, body hash `sha256:30026f2f01bdf22a5f30bb6b54d645c15e3fe75a16890b9a9eecb55ab5a1cfdd`.
It carries a probe feature tag rather than a real feature, and its subject is a
narrow question about whether the anonymous liveness route should expose a
worker restart count - concluding that it should not, on the grounds that the
route is deliberately liveness-only and the count already exists in the richer
health assembly. Its content is reproduced in full in the audit finding that
records the artifact decision, so the evidence survives independently of the
file.

WHY THE FILE IS LEFT UNTRACKED RATHER THAN COMMITTED OR DELETED. Committing it
would mint a permanent feature in the corpus and its index for what is a probe,
polluting exactly the structure this campaign is trying to make trustworthy.
Deleting it would destroy the single piece of end-to-end evidence the campaign
has produced, and this repository has a standing rule against tidying away
provenance. Leaving it untracked destroys nothing and pollutes nothing: the file
remains inspectable on disk, its content is durable in the vault through the
finding, and no phantom feature enters the tracked corpus. Anyone encountering
it should NOT tidy it - the reason it is there is recorded.

This record was authored by the vault writer from the implementing agent's
report and the team lead's independent verification of the file, not from direct
observation of the work.
