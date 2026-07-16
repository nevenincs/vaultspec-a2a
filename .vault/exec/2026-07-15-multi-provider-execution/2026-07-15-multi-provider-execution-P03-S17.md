---
tags:
  - '#exec'
  - '#multi-provider-execution'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S17'
related:
  - "[[2026-07-15-multi-provider-execution-plan]]"
---

# Verify the a2a-edge discovery/eligibility responses correctly surface the new providers with safe reasons on failure and no secrets

## Scope

- `src/vaultspec_a2a/api/tests/`

## Description

Verified the a2a-edge presets discovery/eligibility response surfaces the new
codex and zai providers correctly, with safe reasons and no secrets, in
`test_gateway_live.py::test_presets_list_is_truthful_and_resilient`.

- Asserted the codex profile discloses the three research/authoring roles on
  `codex` with `source=profile` attribution and the un-overlaid doc-reviewer on a
  different provider (a genuinely mixed profile), and the zai profile discloses
  them on `zai`.
- Asserted the zai lane is unavailable, with a safe reason that names the unready
  provider - the system disclosing what is missing, never a credential value.
- Hardened the response's no-secret assertion from a crude substring ban to a
  value-based check: the prior ban on the words "token"/"oauth" false-positived on
  legitimate safe reasons and profile descriptions that name a credential TYPE
  ("Z.ai auth token", "OAuth"). The check now asserts the real configured secret
  VALUES are absent, plus env-dump canaries.

## Outcome

The discovery endpoint is provider-agnostic, so the additive profiles surface
automatically; the test asserts that surfacing is correct and secret-free. Full
`test_gateway_live.py` and `test_model_profiles_evidence.py` suites pass (21
tests), ruff and ty clean.

## Notes

Corrected a stale pre-existing assertion this test carried: doc-reviewer was
repinned off the non-resolving zhipu fallback onto claude in the bundled agent
preset (commit df6665b), but this file's team-defaults assertion still expected
zhipu; updated to claude to match the committed resolution. That was a missed test
update from the repin, surfaced by extending this same test for the provider
axis.
