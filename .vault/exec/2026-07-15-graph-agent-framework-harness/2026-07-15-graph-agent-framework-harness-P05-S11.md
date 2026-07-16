---
tags:
  - '#exec'
  - '#graph-agent-framework-harness'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S11'
related:
  - "[[2026-07-15-graph-agent-framework-harness-plan]]"
---

# Add a live service-level assertion that a research_adr worker turn's compiled system messages actually contain the P02 role-scoped rule content, run against a real provisioned workspace rather than a static-repo RuleManager.compile() call

## Scope

- `src/vaultspec_a2a/service_tests/test_receipt_role_rules.py` (new sibling service module)

## Description

- Add a service-marked, engine-free proof that a document persona receives its
  role-scoped rule conventions at the model boundary in the REAL compiled graph,
  not via a static `RuleManager.compile()` call the ADR deems insufficient.
- Return a recording `BaseChatModel` through the real provider-selection seam
  (the `provider_factory` parameter `compile_team_graph` already accepts and
  calls per worker) - never a monkeypatch onto a compiled node. Everything under
  test is real: the compiler, `RuleManager`, the worker node, and the bundled
  conventions shipped under `context/presets/rules/`.
- Compile the `research_adr` topology over a bare on-disk tmp workspace (Path B,
  bundled-only) and invoke the compiled `adr_author` and `synthesis` document
  writer nodes; assert their model was handed the bundled `Tag taxonomy`
  conventions under the worker rules header.
- Add a live-run variant that drives `ainvoke` to the first gate and asserts
  every document persona that executed (researcher, synthesist, doc-reviewer)
  received the conventions.
- Add the bundled-only tripwire: a bare workspace with no `.vaultspec/rules` is
  not refused by the compile path and the conventions still reach the boundary.
- Add the negative + role=None regression on a coder turn: it is scoped OUT of
  the document conventions (the one-sided-assertion guard) yet still compiles its
  own workspace rule corpus (coder rules are never stripped).

## Outcome

Landed on `main` at `2500eb3`. All three tests pass under `-m service` with no
engine and no Docker (10s), against a bare tmp workspace. `ruff` and `ty` clean.
The recording model is confirmed created through the real selection path (the
compiler logs `resolved model_type=_RecordingChatModel provider=deterministic`).
The positive/negative pairing is non-tautological: the coder case proves the
`Tag taxonomy` marker is not universally injected, so the document-role positive
assertion is meaningful.

## Notes

The ADR's tripwire wording referenced a `has_workspace_rules()` gate; that
function exists but is unused - the live gate was the inline on-disk `.md` probe
in the harness verifier - so the tripwire is asserted behaviourally (a bare
bundled-only workspace is not refused and still yields conventions), which is the
guarantee the tripwire intends. The workspace is a bare on-disk tmp dir rather
than the engine-`provisioned_workspace` fixture, because Path B requires the
absence of `.vaultspec/rules` that the provision verb would scaffold.

Loop closed (post-arbitration): the gateway-level bundled-only story - which at
build time was actively disputed and so proven only at the compile-path level -
is now resolved. The harness verifier's rules leg was corrected to delegate to
the bundled-aware `RuleManager` (landed `90c3522`; recorded under the
agent-harness-provisioning feature), so the gateway no longer refuses a
bundled-only document run on the rules surface.
