---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S131'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Route WebSocket delivery through the shared bounded fanout implementation

## Scope

- `src/vaultspec_a2a/api/websocket.py`

## Description

- Route the connection manager's relay delivery through the shared helper.
- Preserve the structured logging context this path carries and the other does
  not.

## Outcome

The third copy of the policy is gone. The algorithm here was identical to the two in the
subscriber registry; only the logging differed, carrying a thread identifier, a bounded
action name, and the queue maximum where the other path logged a bare message.

That difference is why the helper takes a structured-context argument rather than logging
uniformly. Collapsing the two fidelities into one would have either stripped context the
operator-facing relay depends on, or forced the quieter path to invent fields it has no
value for. The shared piece is the policy; the observability around it stays per-caller.

Gates: `ruff check src/` clean, `ty check src/` clean, streaming suite reports sixty-seven
passed.

## Notes

The bounded action names the caller previously supplied are now applied by the helper, so
the two relay paths emit the same action vocabulary for the same event. Previously each
path spelled its own, which is the drift a shared implementation is supposed to prevent.

The wider api suite did not finish inside its budget on this host and its result is not
claimed here. The streaming suite that owns the changed policy is green, and the type
checker resolves both call sites.
