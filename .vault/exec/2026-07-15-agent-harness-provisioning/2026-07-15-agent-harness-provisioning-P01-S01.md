---
tags:
  - '#exec'
  - '#agent-harness-provisioning'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S01'
related:
  - "[[2026-07-15-agent-harness-provisioning-plan]]"
---

# Build the harness verifier (rules corpus non-empty, required templates present, declared skills present, vaultspec-core CLI resolvable in the agent environment) and feed a harness_ready term with safe reasons into the shared eligibility service consumed by discovery and run-start

## Scope

- `src/vaultspec_a2a/context/`
- `src/vaultspec_a2a/providers/model_profiles.py`
- `src/vaultspec_a2a/control/`

## Description

- Add `src/vaultspec_a2a/context/harness.py`: the read-only harness verifier. `verify_harness(workspace_root, *, required_skills, required_templates)` returns a frozen `HarnessReadiness(ready, reasons)` after four workspace-scoped checks - flat `.vaultspec/rules/*.md` corpus non-empty, every required template present under `.vaultspec/templates/`, every declared skill present under `.vaultspec/skills/` (as a `<name>/SKILL.md` directory or a flat `<name>.md`), and the `vaultspec-core` CLI resolvable in the agent environment (the console script or the `uvx` shim). Reasons are path-free by construction: they name what is missing, never where.
- Export `HarnessReadiness`, `verify_harness`, and `DEFAULT_REQUIRED_TEMPLATES` from the `context` package facade.
- Feed the term into the shared eligibility service in `src/vaultspec_a2a/providers/model_profiles.py`: `evaluate_profile_eligibility` gains an optional injected `harness` verdict whose reasons compose honestly into the profile's ineligibility (discovery serves them); add a `probe_harness_ready` wrapper co-located with the other readiness probes. The verifier is imported lazily inside the probe and the type only under `TYPE_CHECKING`, because `context` pulls in the graph/thread import graph and `model_profiles` is itself imported during graph compilation - a top-level import would close a cycle.
- Make run-start refuse on an incomplete harness in `src/vaultspec_a2a/control/run_start_policy.py`: `evaluate_run_start_eligibility` gains an optional `harness` verdict; a document-authoring preset with a not-ready harness is refused with a safe reason (the discovery-serves / launch-refuses binding), while non-authoring presets and an omitted verdict are unaffected.
- Cover with real-filesystem and real-object tests: `context/tests/test_harness.py` provisions and under-provisions a genuine `.vaultspec/` corpus in `tmp_path`; `providers/tests/test_model_profiles.py` and `control/tests/test_run_start_policy.py` drive the composition and refusal with real `HarnessReadiness` inputs (no mocks).

## Outcome

- ruff and ty clean on all touched modules; 42 unit tests pass (harness verifier, eligibility composition, run-start refusal) plus the 7 API model-profile evidence tests confirming the gateway consumer is unaffected by the new optional term (default omission is a no-op).
- The `harness_ready` term now exists in both eligibility surfaces. Gateway wiring that probes and passes a live verdict at discovery and run-start is deferred to P02 adoption (the `api/routes` layer is outside this Step's scope); the term composition and the run-start refusal path are in place and defaulted safe.

## Notes

- A pre-existing circular import (`context.token_budget` <-> `graph.nodes.supervisor`) means the `context` test package requires `graph` to be imported first; untouched `context/tests/test_rules.py` fails identically in isolation. Not introduced here - the affected tests pass under normal collection order (a graph-importing module collected first). The lazy/`TYPE_CHECKING` harness imports in `model_profiles` were chosen specifically to avoid extending this cycle.
- ruff's unused-import auto-fix repeatedly stripped imports staged before their first use; edits were re-applied so every import lands used.
