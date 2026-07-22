---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S38'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Continuously drain Codex standard error into a bounded redacted diagnostic buffer

## Scope

- `src/vaultspec_a2a/providers/codex_chat_model.py, src/vaultspec_a2a/providers/_subprocess.py`

## Description

- Establish what the Codex session currently does with standard error.
- Drain it for the process lifetime into a bounded tail.
- Redact credential-shaped values before retention, writing the redactor since
  none existed.
- Extract the drain loop so it is testable without reaching into a half-built
  client.

## Outcome

Standard error was not read at all. The session captured only the input and output pipes,
while the shared spawn helper opens standard error as a pipe - so nothing consumed it for
the whole run.

That is a hang rather than lost diagnostics. An undrained pipe fills its operating-system
buffer and the child blocks on its next write, so a Codex process that reported enough
diagnostic output would stall the turn that was waiting on it. The sibling agent path
already drained its own standard error; this one did not.

The tail is bounded and redacted. Provider subprocesses report their configuration when
they fail and configuration is where credentials live, so a retained diagnostic tail is a
plausible place for a token to surface.

Twelve tests cover it: each credential shape masked, ordinary diagnostics untouched, an
absent stream tolerated, real bytes drained off a real stream, and the tail bounded under a
chatty child.

Gates: `ruff check src/` clean, `ty check src/` clean, provider suite reports three hundred
seventy-four passed with ten deselected.

## Notes

The redactor was silently inert when first written and the tests are what caught it. A
stray control byte had been written into the expression, so it matched nothing and every
line passed through unchanged while the code read as though it redacted. A test asserting
only that ordinary lines survive would have passed against that. There is now an explicit
assertion that the redactor is not inert, and its docstring records why it exists.

No redaction helper existed anywhere in the tree, so one was written rather than imported.
It matches on the NAME introducing a value rather than the value's shape, because a token
has no reliable shape while an assignment to something called a token, secret, key,
password or credential does. The helper is local to this module; a second consumer would
justify hoisting it, and one does not exist yet.

The drain loop was extracted to module level after the first version of the tests had to
build a client through its own constructor and poke private attributes. That needed
suppressions this repository forbids, and the suppressions were the signal that the seam
was wrong rather than that the rule was inconvenient.
