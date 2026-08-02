---
tags:
  - '#exec'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:02d27fe474b53c88042e87093045607e2b53bd1d88bd5620719d22ff75afe4c5'
step_id: 'S06'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---
# Register execution-mode-specific catalog adapters and report unsupported enumeration honestly

## Scope

- `src/vaultspec_a2a/providers/factory.py`
- `src/vaultspec_a2a/control/config.py`
- `src/vaultspec_a2a/providers/model_profiles.py`
- `src/vaultspec_a2a/workspace/environment.py`
- direct factory, settings, readiness, workspace, adapter, and installed prompt-free tests
- feature reference and S06 review audit

## Description

- Register every external catalog by exact provider and execution mode without embedding external model identifiers or exposing internal mock/deterministic lanes.
- Bind Claude ACP, Codex app-server, Gemini ACP, Kimi Code ACP, and OpenAI API to their own prompt-free discovery adapters.
- Keep unproven Z.AI and Zhipu enumeration registered but unavailable, with empty catalogs and unknown authentication rather than borrowed provider choices.
- Align discovery and execution commands and endpoints, including Gemini `--acp` without discovery-time model preselection, Kimi sibling `provider list --json` plus exact `-m <alias> acp`, and one OpenAI-compatible base URL.
- Repair Kimi Code 0.28.1 environment drift: current-first legacy migration fallback, blank-current fallthrough, persisted versus complete temporary configuration, ambient scrubbing, normalized optional context/capability fields, and current-name-only reinjection.

## Outcome

Factory registration now preserves provider and execution-mode identity end to end. Installed prompt-free proofs returned available non-empty catalogs for Claude, Codex, and Gemini, while isolated Kimi with an empty persisted home returned the exact truthful unavailable result. Kimi temporary provider settings are bounded and deterministic: context size is a positive 32-bit integer serialized canonically; capabilities are bounded unique provider tokens serialized comma-separated in first-seen order; optional fields cannot exist without the complete temporary tuple. Current values win only when nonblank, otherwise nonblank legacy key/base inputs remain a migration fallback, and secrets are excluded from repr/model dumps.

Static gates passed: Ruff, BasedPyright with zero diagnostics, and ty. The final owner suite passed 124 focused tests, 50 adapter tests with 12 service-marker deselections, and 4 explicit installed prompt-free service tests. Independent review first surfaced two medium configuration findings and closure review surfaced one medium blank-precedence finding; all three were remediated, audited, and directly tested. Fresh closure re-review returned PASS with zero open findings and independently passed 58 focused tests plus all static/diff gates.

## Notes

The initial frozen S06 implementation blobs were exact-staged but were atomically consumed by concurrent commit `d4a75911`; history was preserved without reset or rewrite. Factory and factory-test hashes remained identical across that event, and the complete consumed path list is recorded in the audit. This closure commit contains only post-`d4a75911` remediation and unambiguous S06 lifecycle files.

A concurrent writer twice reintroduced a cross-provider Z.AI catalog adapter before ownership was settled. Work paused, stable hashes were established, and the accepted unavailable boundary was restored. The unrelated untracked future Z.AI live-proof file was never staged or modified. Catalog authentication remains separate from completed-turn admission and later health/selectability work.

Shared lifecycle closure was coordinated with the Dashboard S17 owner. Its A2A audit and exec landed first in commit 781af0a; S06 then regenerated the consolidated feature index and retained the shared plan's truthful S06/S17 closure state without recommitting the peer records.
