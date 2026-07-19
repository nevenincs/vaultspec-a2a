---
tags:
  - '#exec'
  - '#a2a-edge-conformance'
date: '2026-07-19'
modified: '2026-07-19'
step_id: 'S44'
related:
  - "[[2026-07-14-a2a-edge-conformance-plan]]"
---

# Close the two projection review LOWs: enforce the marker base_fingerprint at cleanup (on mismatch, skip inversion and log the desync instead of removing entries a hand-edited marker names), and add the reserved-name mid-run-edit test covering a user entry created mid-run under a projected name. Real-filesystem tests, no mocks

## Scope

- `src/vaultspec_a2a/providers/_acp_project_mcp.py`
- `src/vaultspec_a2a/providers/tests/test_acp_project_mcp.py`

## Description

- Redefined `_fingerprint` to hash a canonical (sorted-key) JSON serialization of the parsed base dict instead of the file's raw text. A raw-text fingerprint would spuriously mismatch on our own `json.dumps` re-serialization (different key order/whitespace) even with zero tampering, since every write we perform goes through our own canonical writer; the canonical-JSON hash survives our own round-trips while still changing on any semantic edit to the protected base.
- `cleanup_projected_mcp` now enforces the marker's recorded `base_fingerprint` (finding `s42-fingerprint-diagnostic-only`): when present, it's compared against a fresh fingerprint of the recovered base (current `mcpServers` minus the marker's `added` names, plus the other top-level keys). On mismatch, inversion is SKIPPED entirely - the file is left exactly as found, and the desync is logged at WARNING naming the file - rather than trusting a marker whose `added` list may no longer describe only entries that are truly ours.
- `_recover_base`'s crash-residue (dict-marker) branch gets the same enforcement for re-projection: when the stripped-base fingerprint doesn't match the marker's recorded value, the stale `added` list is not trusted to recover the base. Falls back to treating the FULL current `mcpServers` as the base (nothing stripped), fingerprinted fresh, so `project_declared_mcp`'s collision check judges every currently-present name - including ones we may have added before the crash - as an existing entry and refuses on any re-declared collision rather than silently reusing an unverifiable slot.
- Added the reserved-name mid-run-edit test (finding `s42-cleanup-keys-on-marker-names`): a user re-purposes one of our reserved projected names (`vaultspec-rag`) mid-run with their own value under the SAME key. Confirmed and pinned as defined behavior: cleanup still pops it as ours, since fingerprint enforcement protects the STRUCTURE of the other (non-reserved) keys and cannot detect a same-named key's value changing underneath it (popping by name is value-agnostic) - the projected namespace is reserved by design, not verified by content.
- Live tests (real filesystem, no mocks): the reserved-name mid-run-edit test above; a cleanup-skips-inversion test (hand-edit a foreign base's structure without updating the marker, assert the file is left byte-identical and a WARNING is logged); a re-projection-refuses test (the same hand-edit applied to a crash residue, assert the fallback's full-current-set collision check raises `ProjectionRefusedError` and the file is untouched).

## Outcome

Both review LOWs are closed. The recorded `base_fingerprint` is now enforced, not diagnostic-only, at both cleanup and crash-residue re-projection; a hand-desynced marker can no longer cause an entry it merely names to be silently removed or silently reused. The reserved-namespace mid-run-edit shape is now covered and its defined behavior pinned by test. Ruff and ty are clean; the full projection suite (17 tests, 4 new) and the broader providers/acp suite (49 tests) pass.

## Notes

Ran ruff via `uvx ruff check` (isolated, no venv mutation) per current environment-hazard guidance; `uv run --no-sync pytest`/`ty` were available in the shared venv at the time of this step and used directly. No incidents. Committed with an explicit file pathspec (`git commit -o <files>`) on whatever branch the shared checkout was on at commit time, per the team-lead's reconcile-via-temp-worktree pattern.
