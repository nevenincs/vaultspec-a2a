---
tags:
  - '#exec'
  - '#multi-provider-execution'
date: '2026-07-15'
modified: '2026-07-15'
step_id: 'S04'
related:
  - "[[2026-07-15-multi-provider-execution-plan]]"
---

# Confirm workspace/environment.py's scrub list does not strip ANTHROPIC_BASE_URL or ANTHROPIC_AUTH_TOKEN

## Scope

- `add a regression test pinning that`
- `src/vaultspec_a2a/workspace/environment.py`
- `src/vaultspec_a2a/workspace/tests/`

## Description

- Confirm by reading `resolve_env_vars` in `workspace/environment.py` that its `scrub_keys` set does not contain `ANTHROPIC_BASE_URL` or `ANTHROPIC_AUTH_TOKEN`, and that neither matches the `VAULTSPEC_`/`CLAUDE_CODE_` wildcard scrubs — so both survive the base-env build untouched.
- Add `test_zai_gateway_env_vars_are_preserved` to the credential-scrubbing suite, pinning that invariant: it sets both vars in the process env and asserts they survive `resolve_env_vars`.

## Outcome

The Z.ai auth path is protected by a regression test: a future addition to `scrub_keys` that strips either gateway var will fail the suite rather than silently break Z.ai auth. `ANTHROPIC_API_KEY` (a distinct name) remains scrubbed, as required by the Claude billing-isolation contract.

## Notes

No source change was needed in `environment.py`; the scrub list was already correct. The step's contribution is the pinning test. Exclusive to this phase.
