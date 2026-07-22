---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S39'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Propagate ACP background RPC handler failures as protocol errors or terminal session failures

## Scope

- `src/vaultspec_a2a/providers/_acp_protocol.py, src/vaultspec_a2a/providers/acp_chat_model.py`

## Description

- Establish what currently happens when a background handler raises.
- Reply to the agent with a protocol error instead of leaving the request
  unanswered, reusing the response shape the capability refusal already uses.
- Re-raise cancellation rather than reporting teardown as a handler fault.
- Keep the failure detail out of the reply and in the log.

## Outcome

A raising handler produced no reply at all. The exception escaped into the fire-and-forget
task, a done-callback logged it, and the agent that made the request was told nothing.

That leaves the agent in one of two bad states: blocked until its own timeout, or
proceeding as though the operation succeeded - a refused file write read as written. The
request is answered now, with the internal-error code, naming the method.

Cancellation is re-raised rather than converted. Teardown is not a handler fault and the
agent is owed no reply for it, so the distinction is explicit rather than incidental.

The reply names the method and nothing else. Handler failures carry paths and internal
detail, and the agent is the untrusted side of this boundary; a test asserts the exception
text does not reach it.

Five tests cover the raising, leaking, succeeding, cancelled, and unknown-method paths.

Gates: `ruff check src/` clean, `ty check src/` clean, provider suite reports three hundred
seventy-nine passed with ten deselected, no suppressions anywhere in the new file.

## Notes

Three of my own mistakes shaped the final test file and are worth recording. The first
choice of method was capability-gated, so dispatch refused before reaching the handler and
the test proved the gate rather than the guard; the permission request is used instead
because it is deliberately not gated. The session context was first approximated by a
look-alike class, which the type checker correctly rejected - the real dataclass is used
now, since a stand-in would have type-checked only by suppression. And the context was
initially built in the synchronous test body, where the asyncio primitives it holds cannot
be constructed; it is built inside the loop.

Each of those produced a red test that was wrong about the code rather than a code defect,
which is the case where reading the failure matters most.
