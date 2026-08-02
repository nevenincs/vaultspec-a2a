---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:9b9b39477912784d8e6cbc4c7fa1afd355f0b15358c190f2d3b06685b2444ff5'
related: []
---
# `repository-tooling-hardening` audit: `Provider factory canonical interface review`

## Scope

Independent read-only review of the S25 provider-factory canonical-interface repair. Compared the actual diff and current factory seam with the governed plan, inspected all direct capsule-path consumers, and exercised the factory, capsule, desktop-profile, and desktop-serve behavior without modifying source.

## Findings

No findings. `_build_gemini_command` and `_build_acp_command` are deleted; their former tests now directly exercise the retained classifier behavior, including command and metadata facts. `_capsule_node_executable` and `_capsule_acp_entry` are deleted and replaced by exactly one definition each of `capsule_node_executable` and `capsule_acp_entry`; every direct consumer imports those canonical names and no legacy reference or alias remains. The public factory module does not expand `__all__` to mask this direct-module contract. The focused tests construct real on-disk capsule layouts and an isolated interpreter process, with no mocks, patches, monkeypatches, stubs, skips, or expected failures.

Focused evidence: 61 tests passed across factory, capsule-resolution, desktop-profile, desktop path, and desktop-serve suites. Ty, Ruff check, Ruff format check, production focused Basedpyright, and `git diff --check` passed. The broader modified-test Basedpyright invocation retains 27 pre-existing diagnostics, all in the scheduled provider/service-test remediation boundary; no new source diagnostic is present and the changed legacy-builder imports were removed.

## Recommendations

No factory follow-up is required from this review. Preserve the deferred 27-diagnostic test boundary for `W06.P12.S26`; future factory tests should continue exercising classifier behavior directly rather than restoring command-only builders.
