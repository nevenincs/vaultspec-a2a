---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S48'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Bind MCP-unavailable error-path tests to an owned closed loopback socket without production-state mutation

## Scope

- `tests/mcp, tests/api`

## Description

- Establish where the MCP-unavailable error-path tests pointed before asserting
  the server was unavailable.
- Bind an owned loopback port, close it, confirm it refuses, and pin the gateway
  URL there for the duration of each such test.
- Restore settings and reset the shared client on exit.

## Outcome

The eleven error-path tests asserted that a tool raises when the gateway is unavailable,
but none of them owned that unavailability. They resolved the gateway URL from ambient
settings, which auto-derive to the real gateway port. On a machine already running a
gateway, "unavailable" would have been false and the tools would have reached a live
service - the tests asserting nothing about the path they are named for, or worse, sending
a real request.

Nine of them now take a fixture that binds a loopback port, closes it, and confirms by a
connect-probe that the port refuses before the test relies on it. Binding alone is an
unreliable "is it free" signal on this platform, so the probe is what makes the refusal
guaranteed rather than assumed. The gateway URL is pinned to that dead port and restored on
exit, and the shared client is reset so no connection to the dead port leaks into the next
test.

The two tests that already managed the gateway URL themselves - pointing at an in-process
transport to exercise a specific error body - were left as they were, because they already
own their unavailability rather than inheriting the ambient default.

Gates: `ruff check src/` clean, `ty check src/` clean, the MCP server suite reports
fifty-nine passed.

## Notes

On this machine no gateway was listening on the default port, so the tests passed before
the change as well. That is the finding, not a reassurance: they passed by luck of the
environment rather than by construction, and a single running gateway on the default port
would have turned them from a correctness assertion into a request against production. The
fixture removes the coupling to the environment entirely.

The probe can lose a race - another process can claim the freed port between the close and
the connect check - and the fixture skips loudly in that case rather than proceeding against
a port it cannot prove is dead. A skip that names its reason is honest where a silent
success would not be.
