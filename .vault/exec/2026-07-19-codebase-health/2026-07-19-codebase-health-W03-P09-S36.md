---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S36'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Reject duplicate MCP server identities before emitting Codex or ACP configuration

## Scope

- `src/vaultspec_a2a/providers/_acp_mcp.py, src/vaultspec_a2a/providers/_acp_project_mcp.py`

## Description

- Demonstrate the current behaviour against the real composition before changing
  it.
- Refuse a repeated identity before composition rather than during it, so the
  error names every duplicate.
- Guard the second collision shape the first check cannot see: the authoring
  bridge against a declared harness server.

## Outcome

The defect was reproduced first. Two specs advertising the same known server name produced
one entry, and the second command survived - the first was discarded without a word.
Composition is keyed by name, so a repeated identity never conflicts, it overwrites.

That breaks the harness invariant directly. The spawned agent's MCP surface is supposed to
be exactly the declared set, and a name that can be redeclared with a different command
means the surviving entry is no longer the one that was reviewed. Both composition paths
now refuse.

The bridge collision is a distinct shape and needed its own guard. The authoring bridge is
composed from its own guarded channel rather than from the advertised specs, so the
duplicate check over those specs cannot see a collision between the bridge and a harness
server. A plain merge would let the bridge silently replace a reviewed read-only server
with a write-capable one, which is the same defect with worse consequences.

Gates: `ruff check src/` clean, `ty check src/` clean, provider suite reports three hundred
sixty-two passed with ten deselected.

## Notes

The check runs before composition rather than inside the loop so the refusal can name every
duplicated identity at once. Failing on the first would make an operator fix a
multi-duplicate configuration one run at a time.

Specs without a name, or with an empty one, are not treated as duplicates of each other.
They are already excluded from composition by the registry filter, and reporting them as
identity collisions would produce a refusal an operator cannot act on.
