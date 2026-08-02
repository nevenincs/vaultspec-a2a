---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:ad9e3fed95b65feee5ebf397944685edf5c1807e21924f1201da27721832d9bb'
related: []
---
# `repository-tooling-hardening` audit: `Provider JSON and MCP boundary review`

## Scope

Independent read-only review of the P25-C provider foundation: recursive JSON freeze/thaw in `src/vaultspec_a2a/providers/_json_contract.py`, the closed ACP harness registry and config-home emission in `src/vaultspec_a2a/providers/_acp_mcp.py`, MCP launch-shape and real-handshake verification in `src/vaultspec_a2a/providers/_mcp_contract.py`, and authoring bridge token/config shaping in `src/vaultspec_a2a/providers/_acp_authoring.py`. No source was changed by this review.

The inspected implementation preserves recursively frozen registry interiors and emits fresh mutable wire structures without scalar coercion. Registry-owned names remain fail-closed across ACP and Codex serializers; desktop admission remains explicit; malformed launch fields are rejected before config emission or probing; the authoring bridge validates stdio shape and keeps real tokens in spawn environment rather than config-home values. The contract probe performs real `initialize` plus `tools/list` handshakes, refuses an absent command, malformed args, missing declared tools, and a deadline failure, and skips only the separately guarded authoring bridge.

Validation: focused Basedpyright reported 0 errors/warnings/notes; Ty, Ruff check, Ruff format check, and `git diff --check` passed. The seven real provider seams passed 152 tests, including production `vaultspec-rag` handshake/tool-list evidence. One existing Python 3.13 `importlib.metadata` deprecation warning remained.

## Findings

No material defect was found in the four-file P25-C scope.

### codex-jsonvalue-indexing-followup | low | Codex config rendering remains a deferred raw-value indexing boundary

Type: strict typing follow-up. The P25-C recursive JSON contract deliberately stops at its four owned files. The adjacent Codex renderer in `src/vaultspec_a2a/providers/_codex_config_home.py` still accepts `Sequence[dict[str, Any]]` and directly indexes protocol fields such as `name` and `command`. That leaves the next consumer outside the newly established `JsonValue` boundary and lacks the P25-C-style structural narrowing/refusal. This did not invalidate the reviewed ACP/authoring paths and is recorded for P25-E without expanding the current scope.

## Recommendations

P25-E should adopt the shared JSON contract at the Codex config-emission boundary, narrow each required string/list/object field before use, and refuse malformed protocol values rather than converting them. Preserve the current no-coercion and detached-emission invariants, then add direct renderer-shape regression coverage.
