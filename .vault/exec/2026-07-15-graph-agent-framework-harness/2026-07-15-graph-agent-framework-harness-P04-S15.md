---
tags:
  - '#exec'
  - '#graph-agent-framework-harness'
date: '2026-07-16'
modified: '2026-07-16'
step_id: 'S15'
related:
  - "[[2026-07-15-graph-agent-framework-harness-plan]]"
---

# Consume the declared team.harness mcp_servers into the ACP session composition - resolve each declared server name to a launch spec and thread it per-role through AcpChatModel.with_mcp_servers into session/new, claiming the agent-harness-provisioning ADR's unowned per-role MCP-composition Opens item with a protocol-layer assertion (advertised servers present in session/new params), model-visible surfacing remaining upstream-gated per the S20 constraint

## Scope

- `src/vaultspec_a2a/providers/_acp_mcp.py`
- `src/vaultspec_a2a/providers/_acp_session.py`
- `src/vaultspec_a2a/graph/compiler.py`

Delivered as `feat(providers)` at `357d87a`. A document run whose `[team.harness]`
declares `mcp_servers` now has those servers composed into its ACP `session/new`.

- Created: `src/vaultspec_a2a/providers/_acp_mcp.py`, `src/vaultspec_a2a/providers/tests/test_acp_mcp.py`, `src/vaultspec_a2a/graph/tests/nodes/test_harness_mcp_wiring.py`
- Modified: `src/vaultspec_a2a/graph/nodes/worker.py`, `src/vaultspec_a2a/graph/compiler.py`

The plan-row scope named `_acp_session.py`, but that file already advertises
`config.mcp_servers` into `session/new` unchanged; the missing pieces were the
registry (new `_acp_mcp.py`) and the consumption wiring (worker + compiler), so
no edit to the session builder itself was needed.

## Description

- Add an explicit, closed name-to-launch-spec registry in `_acp_mcp.py`:
  `resolve_harness_mcp_servers` maps a known server name to its stdio spec and
  raises `ConfigError` naming any unknown name plus the known set, so a mistyped
  or unsupported declaration fails loudly at composition time. No plugin or
  discovery machinery. `vaultspec-rag` resolves to `uvx --from vaultspec-rag
  vaultspec-search-mcp` - uvx, not the repo `.mcp.json`'s `uv run` form, because
  the ACP subprocess is spawned in the run workspace with no uv project cwd.
- Add `compose_harness_mcp_servers`: feature-detects the ACP `with_mcp_servers`
  surface (a non-ACP model passes through unchanged), resolves the names, and
  UNIONS the specs by name with any the model already advertises - ADD-only,
  never replacing, so composition only ever widens a session's declared surface
  by exactly the harness declaration.
- Thread `harness_mcp_servers` through `create_worker_node` (composed AFTER the
  per-run authoring attach so both MCP surfaces coexist) and through
  `_make_research_producer`. In `_compile_research_adr`, read
  `effective_harness().mcp_servers` once and pass it to every document-role model
  - the four worker nodes and the researcher producer.
- Reach the researcher explicitly: its model is resolved by
  `_resolve_model_for_worker` and handed to the diverge-branch producer, NOT
  `create_worker_node`, so a worker-only wiring would have starved exactly the
  role the rag server exists for.

## Outcome

Landed on `main` at `357d87a`. Registry + composition unit tests and a
protocol-layer wiring test pass: the wiring test drives the REAL ACP session
builder (a real `AcpChatModel` over the protocol simulator, which records the
`session/new` params) and asserts the declared `vaultspec-rag` server is
advertised for a document worker turn AND, specifically, the researcher producer
turn, and absent when nothing is declared. `ruff` and `ty` clean; the full
default suite reports 1696 passed - the only reds are the eight pre-existing
`service`-marked `test_server` cases that fail when a live gateway answers on
port 8000 (environmental, identical on main, not a regression).

## Notes

Granularity honesty: `TeamHarnessConfig.mcp_servers` is a FLAT, team-level list -
there is no per-role field on the harness schema today - so this is
per-preset-harness composition delivered to all document-role models, not true
per-role. Per-role granularity is a schema extension deferred to the provisioning
ADR's owner if a real need arises.

S20 upstream gate: session-injected MCP servers CONNECT but do NOT surface to the
model in the pinned Claude CLI, so the assertion here is protocol-layer only
(present in `session/new` params); model-visible surfacing remains upstream-gated
and `P03.S05` stays blocked on it and is not checked on the back of this.

Exclusive-MCP-surface note (from the recovery-race record): the composition only
ever ADDs the declared servers (union by name), pairing with `--strict-mcp-config`
thinking; the strict-config hardening itself is not implemented here, only the
interaction noted. No consumption of `has_workspace_rules`, which is slated for
deletion as dead code.

Topology boundary (reviewer observation, a stated boundary not a fix): the
harness `mcp_servers` declaration is threaded only in the `research_adr` compile
path, so a `star` / `pipeline` / `pipeline_loop` coding team that declares
`mcp_servers` gets nothing composed - silently inert. This matches the
document-role intent of the Opens item (the harness surfaces are a
document-authoring concern), but a non-`research_adr` team ever needing harness
MCP servers would require threading the same composition through the star and
pipeline worker sites.

Follow-up (reviewer LOW-9, landed `a3d4e01`): `compose_harness_mcp_servers` now
validates the declared names BEFORE the non-ACP feature-detect passthrough, so an
unknown server name is refused loudly regardless of model type rather than being
swallowed when composition is inapplicable.
