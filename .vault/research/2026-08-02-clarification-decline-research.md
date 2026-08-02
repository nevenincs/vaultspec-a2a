---
tags:
  - '#research'
  - '#clarification-decline'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:f87b8d09fa757d1af61cccf34c9d69d5b97fa269f16508dd21aa1f4903b965ea'
related:
  - "[[2026-08-02-clarification-continuation-adr]]"
  - "[[2026-08-02-control-action-leases-adr]]"
---

# `clarification-decline` research: `declining a parked clarification`

A user shown a parked questionnaire can answer it, replace it with a new prompt, or
cancel the whole run - there is no way to refuse to answer and let the run proceed on
its own judgement. The consuming product surfaces "refuse to answer" as a first-class
outcome beside "answer" and "chat instead", so the run stays parked on a question the
user has already dismissed. The evidence favors a third typed outcome of the same
checkpoint-addressed respond verb, with one transcript marker as its only downstream
trace. The ADR must settle the wire shape, the resume discriminator, the downstream
visibility mechanism, and what a decline may not do (answer synthesis, run cancellation).

## Findings

### The resolution vocabulary is a closed two-variant union with no expiry

`ClarificationResolution` is exactly `ClarificationAnswers | ClarificationContinuation`
(`src/vaultspec_a2a/thread/clarification.py:375`), and the respond body admits exactly one
of `answers` or `prompt` (`src/vaultspec_a2a/api/schemas/gateway.py:680`). No decline,
timeout, or expiry semantics exist anywhere on the parked path: the only exits are a valid
resolution or run cancellation. The lease TTL in the control journal
(`src/vaultspec_a2a/control/action_lease.py:102`) expires dispatch claims, not parked
questions.

### Every type-aware seam is already enumerable, and the lease service is not one of them

Adding a resolution variant touches exactly four type-aware seams: the union and its
parser (`src/vaultspec_a2a/thread/clarification.py:398`), the canonical fingerprint
(`src/vaultspec_a2a/thread/clarification.py:378`, which hashes `as_resume_value()` and so
extends for free), the respond request schema (`src/vaultspec_a2a/api/schemas/gateway.py:701`
exactly-one-of validator plus the route's variant mapping at
`src/vaultspec_a2a/api/routes/gateway.py:1918`), and the gate node's resume handling
(`src/vaultspec_a2a/graph/nodes/clarification.py:346`). The durable lease/journal service
is resolution-type-agnostic - it fingerprints, journals, and dispatches any
`ClarificationResolution` (`src/vaultspec_a2a/control/clarification_service.py:222`) - and
the answers-only semantic validation is already variant-gated
(`src/vaultspec_a2a/control/clarification_service.py:244`).

### Only the message transcript reaches model turns; recorded answers reach nothing

`clarification_answers` state is written by the gate
(`src/vaultspec_a2a/graph/nodes/clarification.py:364`) and read by no production code:
the researcher producer composes its turn from `messages` plus its thread spec
(`src/vaultspec_a2a/graph/compiler.py:1425`), and the worker message builder reads
system prompt, rules, anchoring, and `messages`
(`src/vaultspec_a2a/graph/nodes/worker.py:90`). A continuation is downstream-visible
only because it appends a `HumanMessage`. A decline whose meaning is "proceed on your
own judgement" therefore has exactly one existing mechanism for the graph to know it
was declined rather than never asked: a message append. A new state channel would be
an emitter with zero callers - the defect class the repository's
clarifications-are-typed-interrupts rule names outright. The zero-reader status of
`clarification_answers` itself is a pre-existing gap outside this feature's scope.

### The verb question is already settled by the continuation record

`2026-08-02-clarification-continuation-adr` rejected a dedicated decline/chat verb: a
second outcome of the same resource transition rides the same respond verb as an
exactly-one-of body alternative, preserving the engine whitelist. A decline is the same
class - a third outcome - so a new verb or a new route would re-open a decided question.
The consuming engine's brokered `clarification-respond` currently forwards only the
`answers` alternative (dashboard repo,
`engine/crates/vaultspec-api/src/routes/ops/a2a/clarification.rs:91`), so consumer-side
carry-through is required for decline and continuation alike; that is consumer work
sequenced after this producer lands.

### Receipts distinguish nothing; the fingerprint does

`clarification_resolution_receipts` stores one fingerprint per request id
(`src/vaultspec_a2a/graph/nodes/clarification.py:359`), and idempotent replay compares
stored payload fingerprints (`src/vaultspec_a2a/control/clarification_service.py:262`).
A decline needs no receipt-shape change: its distinct discriminator yields a distinct
fingerprint, so a retried decline replays and a conflicting later answers attempt
refuses with 409 through the existing journal path. Not investigated: surfacing the
resolved outcome kind on `run-status` after resume (nothing discloses "how was it
resolved" today for answers or continuation either; a decline adds no new gap).

## Sources

- `src/vaultspec_a2a/thread/clarification.py:375`
- `src/vaultspec_a2a/thread/clarification.py:378`
- `src/vaultspec_a2a/thread/clarification.py:398`
- `src/vaultspec_a2a/api/schemas/gateway.py:680`
- `src/vaultspec_a2a/api/schemas/gateway.py:701`
- `src/vaultspec_a2a/api/routes/gateway.py:1918`
- `src/vaultspec_a2a/graph/nodes/clarification.py:346`
- `src/vaultspec_a2a/graph/nodes/clarification.py:359`
- `src/vaultspec_a2a/graph/nodes/clarification.py:364`
- `src/vaultspec_a2a/graph/compiler.py:1425`
- `src/vaultspec_a2a/graph/nodes/worker.py:90`
- `src/vaultspec_a2a/control/clarification_service.py:222`
- `src/vaultspec_a2a/control/clarification_service.py:244`
- `src/vaultspec_a2a/control/clarification_service.py:262`
- `src/vaultspec_a2a/control/action_lease.py:102`
- `engine/crates/vaultspec-api/src/routes/ops/a2a/clarification.rs:91` (dashboard repository)
