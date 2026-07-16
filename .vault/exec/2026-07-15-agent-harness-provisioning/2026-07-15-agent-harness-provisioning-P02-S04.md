---
tags:
  - '#exec'
  - '#agent-harness-provisioning'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S04'
related:
  - "[[2026-07-15-agent-harness-provisioning-plan]]"
---







# Prove it live: an unprovisioned workspace is refused with the harness reason at discovery and run-start, a provisioned run passes with agents demonstrably reading templates and rules, and the skills surface is present and consulted per the persona directives

## Scope

- `src/vaultspec_a2a/service_tests/`
- `src/vaultspec_a2a/api/tests/`

## Description

- Prove the refuse/serve binding LIVE at the gateway HTTP boundary in `api/tests/`: real gateway app on a real socket, real eligibility service, and a real `vaultspec-core install` (no doubles). Three live directions: an unprovisioned document-authoring workspace is REFUSED at run-start with the harness reason before any dispatch and SERVED as unavailable at discovery on every profile; a workspaceless authoring run (top-level feature and tokens but no metadata) is REFUSED with the no-workspace reason before any dispatch; a provisioned workspace clears the harness gate at both surfaces. Reasons are asserted path-free.
- Prove the service-fixture adoption in `service_tests/`: the `provisioned_workspace` fixture runs a genuine install and the resulting workspace passes the harness verifier and carries the flat rules corpus plus every required template.
- Confirm the wiring is additive: the new gateway route + unit tests and the service tests pass, and the pre-existing API and eligibility suites are unchanged.

## Outcome

- Refuse and serve are proven LIVE and automatable: 5 gateway route tests + 2 gateway unit tests + 2 service-fixture tests pass, all against real HTTP / real installs with no mocks. This closes the reviewer's carried MEDIUM (the harness gate is no longer inert at the boundary) and the workspaceless-authoring bypass raised in S03 REVIEW 5b.
- Honest gap on the full agent-authoring lane: the plan's "a provisioned run passes with agents demonstrably reading templates and rules, and the skills surface is present and consulted" requires a running authoring engine plus real LLM agents. In this session no engine is reachable and real Claude runs are blocked by the weekly usage limit, so the end-to-end authoring materialization was NOT re-driven here. The provisioned run's acceptance is proven up to the gateway boundary (harness gate cleared); the agents-actually-read-the-corpus assertion rests on the ADR's ws5 counterfactual and the prior S10 live runs, and a fresh live re-drive is deferred to when the engine + LLM quota are available.

## Notes

- Registry-allocated-port live stacks were not booted: there is no standalone `procs allocate`/spawn CLI verb (the registry allocates into bands on spawn), no engine is currently running, and the LLM quota is exhausted for the week. The route-level proof uses a real uvicorn socket, which exercises the same gateway app a booted stack would, so the refuse/serve behaviour is genuinely proven against a live server - only the LLM-authoring tail is deferred.
- Committed on branch `fanout/agent-harness-provisioning-p02`: route proof `01b511a`, service-fixture proof `216615f`.
- The S04 box is held pending the reviewer's verdict and a team-lead ruling on whether the deferred live-authoring re-drive is required for S04 sign-off or tracked forward.


