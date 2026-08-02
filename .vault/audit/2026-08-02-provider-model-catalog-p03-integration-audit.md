---
tags:
  - '#audit'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:bd992428d4b3e1cf9333c40b69f31d262dcac642855dc7498c20ab73c63f3885'
related:
  - "[[2026-08-02-provider-model-catalog-adr]]"
  - "[[2026-08-02-provider-model-catalog-plan]]"
---
# `provider-model-catalog` audit: `P03 Dashboard to A2A catalog integration review`

## Scope

Reviewed the opt-in live provider integration path from the Dashboard engine through A2A. The review covered explicit prerequisite declarations, opaque selection validation against the served catalog, frozen assignment disclosure, terminal output evidence, and idempotent replay. A final independent read-only pass covered all five changed implementation and coverage files, found no remaining findings, and confirmed the three new nested-Pytest coverage cases use no mock, fake, stub, patch, monkeypatch, skip, or xfail technique. This host has neither a configured Dashboard engine command nor the five live selector variables, so no external provider turn was sent and no plan execution step is claimed complete.

## Findings

### live-provider-transcript-evidence | high | Completion did not prove the configured provider returned the prompt response

The first version treated a completed run plus frozen start, status, and replay envelopes as sufficient. That could pass if a run were marked complete without an agent output. Remediated in this pass: every authorized run now uses a fresh bounded nonce, instructs an exact nonce-only response, and reads the real gateway history to require an assistant turn from an agent named by the frozen record whose content equals that nonce.

### lifecycle-identifiers-in-executable-tests | low | Plan identifiers appeared in code and test names

The first version exposed lifecycle identifiers in environment variables, constants, comments, and test names. Remediated in this pass: executable identifiers now describe the stable live-provider behavior and use `LIVE_PROVIDER` and `VAULTSPEC_LIVE` names. Lifecycle tracking remains in Vault records.

### live-provider-proof-unconfigured | low | The current host cannot produce the billable integration evidence

The engine command and explicit opaque provider, lane, entry, control, and option selectors are absent. The focused service invocation therefore deselects both live proofs rather than skipping or spending. Explicit declarations collect both proofs, but collection alone does not validate a provider response.

## Recommendations

- Run the two live proofs only in an authorized environment that supplies the Dashboard engine command and current catalog-derived selector identifiers, with both named prerequisites explicitly declared.
- Keep the provider-execution plan steps pending until that run proves the nonce response, frozen assignment, and replay through real processes.
- Preserve collection deselection for absent authorization; a missing live-provider configuration must not become a passing skip.
