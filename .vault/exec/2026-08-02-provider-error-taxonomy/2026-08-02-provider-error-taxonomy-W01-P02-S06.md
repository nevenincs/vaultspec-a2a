---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:5d62748391808e854eaaed558bc8edb2e13ce64a1e5dfe8dc14caf53c247d51c'
step_id: 'S06'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Declare the closed provider condition vocabulary

## Scope

- `src/vaultspec_a2a/providers/conditions.py`
- `src/vaultspec_a2a/providers/__init__.py`

## Description

- Add a leaf domain module declaring `ProviderCondition`, a nine-member string
  enum whose values are the wire form a second repository consumes.
- Document on each member what it means, what remedy it implies, and what it is
  deliberately NOT, so a later mapping cannot quietly widen a member by reading
  its name rather than its contract.
- Record the two asymmetric members on the members themselves: the coarse
  throttled member that lanes without the finer signal collapse to, and the
  finer usage member reserved for a lane whose wire names it.
- State the totality contract and the additive-only constraint at module level,
  where every future mapper author reads them.
- Export the vocabulary from the package facade eagerly. The module imports only
  the standard library, so it cannot participate in the import cycle the rest of
  the facade defers around.

## Outcome

The vocabulary exists and is nine members: network unreachable, provider
overloaded, unauthenticated, throttled, usage exhausted, credits exhausted,
budget exhausted, invalid request, unknown.

The value this Step adds beyond the enum itself is the member contracts. Two of
them exist to prevent a specific false claim each. The overloaded member is
documented as reserved for a discriminator that names overload, explicitly NOT
for a generic server-side fault - because a 500 reported as overload tells a
client to wait, which is a remedy the wire never stated. The throttled member is
documented as the collapse target on lanes that cannot separate a rate refusal
from an exhausted window, which is the one place the governing decision predicted
an eight-member vocabulary would have forced a lane to lie.

The unknown member is documented as a normal outcome rather than a defect. That
framing is load-bearing for the mappers that follow: if unknown reads as failure,
the pressure is to guess a nicer member, which is exactly how a taxonomy stops
being trustworthy.

Verified with `ruff format`, `ruff check src`, whole-tree `ty check` (clean), and
`pytest -q -p no:randomly --timeout=180 --timeout-method=thread` over the
providers test package: 610 passed, 2 failed, 30 deselected - both failures
pre-existing and unrelated, already recorded against the preceding Step.

## Notes

No test accompanies this Step. The declaration has no behaviour to exercise, and
a test asserting that an enum contains the members written three lines above it
is the tautology this project forbids; the vocabulary is proven where it is used,
by the totality coverage two Steps from here.

The members were checked against what the served lanes can actually carry before
being written down, not after. One consequence is already visible and is recorded
here rather than discovered later: neither served lane's error path names a
credit balance and a spend ceiling in the same shape, so the credits and budget
members will be emitted by different lanes for different reasons, and no lane
will emit both.
