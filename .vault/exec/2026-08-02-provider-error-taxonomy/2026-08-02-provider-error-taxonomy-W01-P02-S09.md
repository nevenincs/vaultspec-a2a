---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:1f4b9c2121c1f70ae1228e4e5fe6e73c63b83833009f42ac670681b70f9a2143'
step_id: 'S09'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Attach the resolved condition to the ACP prompt error at raise

## Scope

- `src/vaultspec_a2a/providers/acp_chat_model.py`
- `src/vaultspec_a2a/providers/acp_exceptions.py`

## Description

- Give the base ACP error a keyword-only `condition` field defaulting to the
  unknown member, so every ACP failure carries one whether or not its raise site
  had a discriminator to resolve.
- Resolve the condition where the JSON-RPC failure frame is turned into an
  exception, which is the last place the adapter's error kind is still in hand.
- Fold the condition into the class's declared slots and drop the stray second,
  empty slots declaration that was silently overriding the first.

## Outcome

The provider's own classification now travels WITH the exception instead of
being stranded in a payload nobody reads. Carrying it as a first-class field
rather than leaving it inside the structured data matters for what comes next:
the reporting site walks a cause chain and needs to read a condition off an
arbitrary link, which it cannot do by re-parsing a vendor-shaped payload it has
no schema for.

Driven against the exact frame captured live from the Z.ai gateway two Steps
earlier, the raise now yields condition `unauthenticated` alongside code -32603
and the untouched structured data. Four further shapes were driven through the
same real raise site: the rate-limit kind resolving to throttled, the
authentication-required code with no kind at all resolving to unauthenticated
from the code alone, an internal-error code with no kind resolving to the floor,
and a response carrying no error object at all also resolving to the floor
rather than raising a second failure inside the first.

The default is what makes this safe to land ahead of the remaining raise sites.
The two ACP failures raised without a wire frame - a turn that goes silent past
its idle deadline, and a subprocess that exits before the turn ends - now report
the unknown member rather than nothing, which is the truthful answer for a
failure the wire never classified.

Verified with `ruff format`, `ruff check src`, whole-tree `ty check` (clean), and
`pytest -q -p no:randomly --timeout=180 --timeout-method=thread`: the providers
package at 615 passed, 2 failed, 30 deselected - both failures pre-existing and
unrelated - and the thread, graph and streaming packages together at 733 passed,
2 deselected.

## Notes

The stray slots declaration removed here was a real defect, not tidying. The
class declared its four attribute names and then, after the method definitions,
declared an empty tuple under the same name; the class body executes in order,
so the empty one won and the named declaration never took effect. Adding a
condition field to a class in that state would have quietly continued the
pattern. The practical effect was nil either way, because a base exception
carries an instance dictionary regardless, which is exactly why nothing had
caught it.

Two ACP raise paths outside this Step's scope still resolve to the floor by
default rather than by classification, and are recorded rather than changed. The
session-setup authentication failure raises through the auth helper with its own
bounded outcome marker, and the catalog's RPC failure classifier builds a session
error from the same JSON-RPC shape this Step now maps. Both already hold the
frame they would need, so both are cheap to convert; neither is named in this
Phase.

No test lands with this Step. The proof that the condition reaches a raised
exception belongs with the totality coverage three Steps from here, which drives
these same raise sites rather than asserting on a constructed object; in the
meantime the behaviour was exercised directly against the real raise site with
the live-captured frame.
