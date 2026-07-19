---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S42'
related:
  - '[[2026-07-14-a2a-edge-conformance-plan]]'
  - '[[2026-07-19-a2a-edge-conformance-adr]]'
---

# Implement marked-entry merge projection per the 2026-07-19 real-project-root mcp projection ADR: merge declared surfacing entries into an existing foreign .mcp.json with an added-keys marker, loud refusal only on name collision or unparseable file, cleanup inverting exactly the marker's entry list (foreign and mid-run user entries never touched), idempotent crash-residue re-projection, legacy whole-file marker honored for one transition release. Live real-seam tests for merge, create, collision, crash-residue, and mid-run-edit cases

## Scope

- `src/vaultspec_a2a/providers/_acp_project_mcp.py`
- `src/vaultspec_a2a/providers/tests/`

## Description

Reworked the run-workspace MCP projection from file-replacement to marked-entry
merge, per the ADR, so a run whose workspace is a real project root (the normative
production case, which near-universally carries a git-tracked `.mcp.json`) gains
BOTH the project's own MCP servers AND the declared bridge/harness surface instead
of hard-failing.

- `project_declared_mcp` now reads and parses any existing `.mcp.json`, recovers
  the pre-merge base (a foreign file's content, or - for crash residue - the base
  under a stale marker with its added keys stripped), refuses loudly ONLY on a
  server-name collision with a non-projected entry or an unparseable file, then
  writes the declared entries alongside the base. Non-`mcpServers` top-level keys
  the project declared are preserved through the merge. The marker moved from the
  boolean `true` to a dict recording the exact added entry names, whether the
  pre-merge base was absent, and a content fingerprint of the pre-merge file for
  diagnostics.
- `cleanup_projected_mcp` inverts exactly the marker's `added` list and drops the
  marker, then deletes the file only when the pre-merge base was absent and nothing
  foreign remains; otherwise it writes back the surviving entries. A foreign entry,
  or one a user added mid-run, is never removed. A legacy `true` marker keeps its
  whole-file removal for one transition release.
- Crash-residue re-projection is idempotent: a stale dict marker is inverted to the
  true base before the fresh merge, and the ORIGINAL pre-merge state is carried
  forward so a later cleanup still restores it.
- Updated the caller comment in the spawn seam and the `ProjectionRefusedError`
  docstring to the narrowed refusal semantics. The spawn seam's ancestor-deny
  composition (`enumerate_ancestor_mcp_names` minus `projected_declared_names`) is
  upstream of the merge and unchanged; verified it still composes.

- Modified: `src/vaultspec_a2a/providers/_acp_project_mcp.py`,
  `src/vaultspec_a2a/providers/acp_chat_model.py`,
  `src/vaultspec_a2a/thread/errors.py`,
  `src/vaultspec_a2a/providers/tests/test_acp_project_mcp.py`,
  `src/vaultspec_a2a/providers/tests/test_isolation_fail_loud.py`

## Outcome

Live real-seam tests (real filesystem, no mocks) cover every ADR case: merge into a
real project `.mcp.json` asserting BOTH surfaces present and the original project
config restored after cleanup; absent-file create then remove-to-absent; name
collision loud refusal with the foreign file left intact; unparseable-file refusal;
crash-residue re-projection idempotent for both absent-base and foreign-base residue
(no double-count, original restored on cleanup); and a mid-run user-added entry
surviving cleanup while only our added entry and the marker are removed. The
armed-run spawn-path fail-loud test was repurposed from refuse-on-any-foreign to
refuse-on-name-collision, matching the new semantics.

Validation: `ruff` and `ty` clean on the touched modules; the full provider suite
passes (`322 passed`), including the 14 projection unit tests and the reworked
isolation fail-loud test.

## Notes

Byte-for-byte restoration is not guaranteed for the merge case - a merged foreign
file is rewritten and its JSON formatting may normalize (the ADR consequences
accept this). The tests assert restoration of the parsed CONTENT, which is the
meaningful invariant; the fingerprint is retained for desync diagnostics, not for
verbatim restore. The legacy `true`-marker path is a deliberate one-release
transition and must be retired explicitly, or it becomes dead policy.

The S20 solo-coder closure probe against a real project root is S43, dispatched
after this lands.
