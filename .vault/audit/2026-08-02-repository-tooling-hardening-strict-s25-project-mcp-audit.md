---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:04a5d3688ac7d8640c4de2edab61db79536e55e9f6c2d4d2f6cc256a9b6a391e'
related: []
---
# `repository-tooling-hardening` audit: `ACP project MCP trust boundary review`

## Scope

Independent source-only review of the current ACP project-MCP JSON trust boundary. Reviewed the three ingress modes (typed declared entries, untrusted filesystem JSON, and current/legacy ownership markers), recovery and cleanup invariants, refusal API, placeholder preservation, collision rules, fingerprint handling, and the focused real-filesystem Claude entrypoint evidence. No source was edited during this audit.

## Findings

### marker-schema-field-presence | medium | A malformed current marker can delete a foreign server during cleanup

`_current_marker` reads `base_fingerprint` with `.get()`, so a marker that omits that required current-schema field is accepted exactly as if it contained the explicit JSON value `null`. The cleanup path then trusts its `added` list and removes the named server. A real temporary filesystem reproduction with a foreign `.mcp.json` containing `mcpServers.foreign` and a marker `{ "added": ["foreign"], "base_absent": false }` produced `mcpServers: {}` after cleanup. This violates the never-touch-foreign invariant for a malformed marker. Classification: medium, trust-boundary data-integrity defect. Status: open.

### marker-schema-field-presence | medium | Resolved by fail-closed current-marker validation

Post-repair review confirms `_current_marker` requires membership of `added`, `base_absent`, and `base_fingerprint`, validates every added name as a string and the two scalar field types, accepts explicit JSON `null` only when `base_fingerprint` is present, and leaves extra fields inert. Both cleanup and crash-residue recovery route through that one validator. The added real-filesystem regressions prove a missing fingerprint logs a warning and preserves the exact bytes during cleanup, while re-projection refuses the present declared name and likewise preserves exact bytes. Existing absent-base null output, legacy `true` cleanup, and valid extra-marker-field behavior remain accepted. Focused tests: 27 passed. Production static gates: Basedpyright 0, Ty clean, Ruff check/format clean, and `git diff --check` clean. Status: resolved.

### project-mcp-test-static-debt | low | Test-only strict diagnostics remain owned by the next test-domain step

The reviewed test module still reports 53 Basedpyright diagnostics and 2 Ty diagnostics. They are the established test-harness typing boundary, not introduced by this repair: production `src/vaultspec_a2a/providers/_acp_project_mcp.py` is clean under both analyzers. Classification: low, test static-analysis debt. Status: open; explicitly owned by plan step `W06.P12.S26`.

## Recommendations

- Require presence of every current-marker field before accepting the dict marker, including `base_fingerprint`; keep explicit JSON `null` valid only when the field is actually present. Add a real-filesystem regression that proves malformed current markers leave the complete foreign file byte-for-byte unchanged.
