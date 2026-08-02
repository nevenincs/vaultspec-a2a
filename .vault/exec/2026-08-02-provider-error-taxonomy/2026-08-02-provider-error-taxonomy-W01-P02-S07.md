---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:b902d7ed56eca828e13c0a957f51dc50eed325e202a627d88f1d71584c039f77'
step_id: 'S07'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Map the ACP error kind and JSON-RPC code onto the vocabulary

## Scope

- `src/vaultspec_a2a/providers/conditions.py`

## Description

- Add a table from the adapter's categorical error kind to the vocabulary,
  covering every member of the installed agent SDK union plus the adapter's own
  no-result kind, with a comment on each entry that is not self-evident.
- Add a second table from the JSON-RPC code, which answers for the failures
  raised outside a turn and therefore carrying no kind at all.
- Add one total resolver that prefers the kind and falls back to the code,
  returning the unknown member for a malformed frame, an absent discriminator,
  or a discriminator this vocabulary predates.
- Expose the set of explicitly mapped kinds, so coverage can assert that every
  kind the installed adapter can emit was decided rather than left to fall
  through - totality alone is too weak a property to test, since the floor makes
  every input return something.

## Outcome

The lane's own discriminator now reaches the shared vocabulary without anything
having to read the message text. The kind is preferred; the code answers only
when no kind is present.

| kind | condition |
| --- | --- |
| authentication_failed | unauthenticated |
| oauth_org_not_allowed | unauthenticated |
| billing_error | credits exhausted |
| rate_limit | throttled |
| overloaded | provider overloaded |
| invalid_request | invalid request |
| model_not_found | invalid request |
| max_output_tokens | invalid request |
| server_error | unknown |
| unknown | unknown |
| no_result | unknown |

| code | condition |
| --- | --- |
| -32000 | unauthenticated |
| -32700, -32600, -32601, -32602 | invalid request |
| -32603 | unknown |
| -32800, -32002 | unknown |

Three entries carry the weight of the governing decision's honesty constraint.
The rate-limit kind maps to the coarse throttled member and NOT to the finer
usage member, because the CLI assigns that single kind to both a short-term rate
refusal and an exhausted usage window, branching between them only on a response
header it consumes internally. The generic server-fault kind maps to the floor
rather than to overloaded, because overloaded implies a remedy - wait - that the
wire did not state. The billing kind maps to the credits member and never to the
budget member, since the budget member means a ceiling the caller configured and
this lane has no such control.

The mapping is total by construction and its floor is reached three different
ways - unrecognised kind, absent kind with an uninformative code, and a
non-object frame - all of which were exercised directly against the resolver
along with the eleven mapped kinds and the seven mapped codes.

The kind vocabulary was taken from the installed adapter rather than from the
published union, which is what surfaced the eleventh kind: the adapter raises a
no-result kind of its own when a turn ends without producing anything, and that
kind is not a member of the SDK union at all. A table built from the published
union alone would have let it fall through silently.

Verified with `ruff format`, `ruff check src`, and whole-tree `ty check` (clean).

## Notes

Two mappings are judgement rather than deduction and are flagged here so a later
reader can overturn them cheaply.

The billing kind is the least certain entry in the table. The provider's own
billing refusal covers at least a depleted balance and a reached spend ceiling -
the second is observable as a distinct message on the same kind - and this
vocabulary has separate members for those. There is no coarser member spanning
both, so the choice was between the credits member and the floor. The credits
member was chosen because the floor tells a client to report a bug, which is
actively wrong for a failure whose remedy is a billing action, whereas the two
billing sub-cases share that remedy. If the consuming surface ever renders a
literal credit balance off this member, that decision should be revisited.

The output-ceiling kind maps to the invalid-request member on the reasoning that
retrying an unchanged request repeats it. That reading is defensible but not the
only one: the request was satisfiable and merely truncated, so a reader who
expects the invalid member to mean outright rejection will find this entry
surprising.

An asymmetry worth recording: this lane has no discriminator for an unreachable
provider at all. A transport failure here does not arrive as an error kind, so
the unreachable member cannot be produced on this lane and will only ever be
emitted by a lane whose wire names a connection failure.
