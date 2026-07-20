---
tags:
  - '#exec'
  - '#repository-tooling-hardening'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S05'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---

# Reconcile the compact custom rule corpus and regenerate provider projections through owning verbs

## Scope

- `.vaultspec/rules`
- `generated provider projections`

## Description

- Inventory custom and built-in rule provenance through project-locked Core 0.1.48.
- Rewrite the four retained repository rules through Core's canonical writer.
- Remove twenty obsolete workflow-template and persona rules through Core's remove verb.
- Preview and apply Core 0.1.48's owning full-framework upgrade, then review its exact asset changes.
- Reconcile Core and RAG installation modes through their project-locked owning installers without provisioning models or Qdrant.
- Correct the RAG module's explicit dependency-mode install, preview, and upgrade commands against locked 0.3.2 help.
- Force-prune and regenerate every provider rule projection, then refresh complete provider instructions.
- Verify canonical/projection counts, rule status, entrypoint references, formatting, convergence, and safe staging.

## Outcome

The canonical rule corpus now contains four compact custom rules plus four Core built-ins. Each provider has exactly the effective custom and built-in projections; Claude and Codex also retain Core's generated system-rule projection. `AGENTS.md` and `CLAUDE.md` reference exactly their nine effective rule files, while `GEMINI.md` embeds the same effective corpus. The full-framework upgrade updated four agents, the CLI reference, one built-in rule, one skill, and two system sources. A second upgrade preview reported every framework asset unchanged. Workspace metadata now records Core as a development dependency and RAG as a runtime dependency. The final locked RAG installer used `--no-mcp` because the optional `rag` profile already supplies MCP, completed without model or Qdrant provisioning, preserved `pyproject.toml` and `uv.lock` byte-for-byte, and left locked MCP/server capability ready. Its module commands make dependency mode and idempotent MCP acquisition explicit. Core then reported zero missing, drifted, or stale rule projections, a complete provider sync reported 105 unchanged outputs, and a second rules sync reported 32 unchanged outputs.

## Notes

The shared index temporarily contained excluded runtime and Qdrant state; those paths were unstaged before commit and the resolved high finding is recorded in the rolling audit. Core 0.1.48 still lacks an owning ignore configuration for the runtime/provider-lock gap, so those paths remain untracked and unstaged without a competing repository policy. The full-framework skew was resolved through Core's owning upgrade and convergence workflow. No generated projection was edited directly.

Formal review result: PASS. No Critical or unresolved High finding remains in S05. The final vault check passed with four warnings that predate or sit outside this Step: two annotations in other feature plans, one stale index for another feature, and one unrelated plan without an ADR.
