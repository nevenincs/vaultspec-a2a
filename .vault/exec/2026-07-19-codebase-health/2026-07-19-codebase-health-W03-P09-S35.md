---
tags:
  - '#exec'
  - '#codebase-health'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S35'
related:
  - "[[2026-07-19-codebase-health-plan]]"
---

# Consolidate harness MCP server normalization on one canonical schema and resolver

## Scope

- `src/vaultspec_a2a/providers/_acp_mcp.py, src/vaultspec_a2a/mcp`

## Description

- Compare the two serialization consumers against the registry and resolver they
  read from.
- Establish whether their differing output shapes are duplication or one source
  serialized twice.
- Close the parity gap the comparison exposed.

## Outcome

The normalization is already consolidated, and the audit that established it found an
inconsistency in this session's own earlier work.

Both consumers read one registry, resolve through one capability resolver, and apply the
same read-only trust-root guard. Their outputs differ because the transports differ - a
Claude configuration home keys servers by name under a JSON object, a Codex configuration
declares a table per server - so two serializers over one canonical source is the correct
shape rather than duplication to remove.

The gap was in the guard, not the schema. An earlier Step in this session added a duplicate
identity refusal whose own scope named both transports, and it was applied to only one. The
Codex path accepted a repeated name and emitted two specs sharing it, which becomes two
configuration blocks under one key - a parse failure or a last-wins overwrite, the same
shadowing the other path already refused, on a transport where it can also break the file
outright.

Both transports now refuse the same condition, and a test asserts that parity directly
rather than testing each in isolation.

Gates: `ruff check src/` clean, `ty check src/` clean, provider suite reports three hundred
eighty-three passed with ten deselected.

## Notes

The earlier Step was closed with its own execution record describing a fix to both paths
when only one had been changed. Finding that here is uncomfortable and worth recording
plainly: a Step naming two surfaces needs each verified against the code, not one verified
and the other assumed to follow. The record of that Step remains as written and this one
carries the correction, because rewriting it would hide that the gap existed.

The consolidation itself required no change, which is the second time in this Phase that
reading the code contradicted the Step's premise. Both times the useful output was the
verification rather than a refactor.
