---
tags:
  - '#exec'
  - '#agent-harness-provisioning'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S03'
related:
  - "[[2026-07-15-agent-harness-provisioning-plan]]"
---

# Implement the workspace provision verb wrapping vaultspec-core install/sync plus the verifier, surface version skew, and adopt it in the PW7 acceptance harness and service fixtures

## Scope

- `src/vaultspec_a2a/cli/`
- `src/vaultspec_a2a/service_tests/`

## Description

- Add the workspace provision verb in `cli/provision.py`: `provision_workspace(path)` wraps `vaultspec-core install` (scaffold + sync the `.vaultspec` corpus) and then runs the S01 harness verifier over the result, returning one `ProvisionResult` whose readiness is the verifier's verdict, not the installer's exit code. Version skew between the environment-pinned and the resolved `vaultspec-core` is computed and surfaced (never hidden); skew composition and version parsing are pure helpers.
- Expose it as `vaultspec-a2a workspace provision <path>` (click group + command in `cli/main.py`), with `--verify-only` to check an already-provisioned tree; exits non-zero and lists each missing surface when the harness is incomplete.
- Wire the carried-forward MEDIUM into the live gateway boundary: run-start and discovery now probe the harness for document-authoring presets via a `_probe_harness` helper and pass the verdict into the eligibility service, so run-start REFUSES an incomplete authoring harness and discovery SERVES the harness reason. The probe returns `None` for non-authoring presets or a workspaceless run, so the change is additive.
- Adopt provisioning in the service fixtures: a `provisioned_workspace` fixture calls `provision_workspace`, replacing the ws5 manual recipe.
- Cover with a real `vaultspec-core install` integration test plus pure-logic skew/parse tests (no doubles), and confirm the gateway wiring is regression-safe across the API and eligibility suites.

## Outcome

- ruff + ruff format + ty clean on all touched modules; 9 provision tests pass (including the real-install integration) and 235 API + run-start + model-profile tests pass unchanged (the harness probe is a no-op for the presets/workspaces those tests use).
- The provision verb was dogfooded to materialize this branch worktree's own `.vaultspec` and reported "harness ready".
- Committed on branch `fanout/agent-harness-provisioning-p02` (code commit `f0bba58`). The live refuse/serve proof and registry-allocated stacks are P02.S04.

## Notes

- Work was done in an isolated worktree off clean main HEAD (own index, local uv venv) to stay clear of the shared-tree contention with the parallel gateway campaign; the driver merges the branch.
- The run-start harness refusal is realized through the run-start policy (the natural precondition gate); the profile-freeze path keeps its provider-readiness-only contract, so harness is gated once at run-start, not twice.
- Carried forward to P02.S04: prove the refuse (unprovisioned workspace 422 at discovery and run-start) and the serve (provisioned run passes, agents read templates/rules, skills consulted) against live stacks on registry-allocated ports. Still-open consolidation LOWs (topology two-sources-of-truth; RuleManager has_workspace_rules consume-side) remain for the follow-up task.
