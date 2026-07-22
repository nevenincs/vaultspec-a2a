---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S37'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Prove duplicate MCP identity rejection through the real configuration parser

## Scope

- `tests/providers, tests/mcp`

## Description

- Drive the real composition functions and the real config-home writer rather
  than asserting on a helper in isolation.
- Cover the accepted single-identity case, the refused duplicate, the naming of
  every duplicate, and the specs that must not trigger a false refusal.
- Assert that a refused composition writes nothing.

## Outcome

Six tests pass against the real boundary that emits configuration.

The last one is the load-bearing assertion: a refused duplicate leaves the target directory
byte-identical to how it started, so the refusal happens before anything is written rather
than after a partial home exists. A guard that raised after writing would have passed a
test asserting only that it raised.

The positive case is proven the same way, through the writer: the command that lands in the
written configuration is the declared one, so the test measures what the agent would
actually load rather than what the composition function returned.

Gates: `ruff check src/` clean, `ty check src/` clean, provider suite reports three hundred
sixty-two passed with ten deselected.

## Notes

The false-refusal test earns its place. Specs with a missing or empty name appear more than
once in ordinary configurations and must not be read as colliding identities; without that
assertion, a stricter-looking guard that grouped them would pass every other test here.
