---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:ea3338f5807ce399f668200d5cb435ffc46dc88e12f8a393984ac34aac492167'
related: []
---
# `repository-tooling-hardening` audit: `Provider and service friend-test policy review`

## Scope

Independent configuration-only review of the current `pyproject.toml` friend-test execution environments. Compared the working configuration with an isolated archive of `HEAD`, using the same locked Basedpyright executable. Verified that the only configuration delta is `reportPrivateUsage = false` on exactly `src/vaultspec_a2a/providers/tests` and `src/vaultspec_a2a/service_tests`; the global strict profile, inclusion roots, exclusions, interpreter version, and every other rule remain unchanged.

## Findings

### friend-test-residual-strict-diagnostics | low | 873 genuine diagnostics remain after the narrow private-usage policy change

Type: static-analysis debt. Status: open; queued to `W06.P12.S26`. The isolated pre-change configuration reports 1,003 diagnostics in the two friend-test roots, including 130 `reportPrivateUsage` findings. The current configuration reports 873 diagnostics in those roots and zero `reportPrivateUsage` findings: the exact 130-diagnostic reduction. The remaining failures are still active strict checks, led by unknown variable, member, argument, and parameter types; argument and attribute incompatibilities; missing generic parameters; and five `reportPrivateLocalImportUsage` diagnostics. The global profile also continues to report 318 `reportPrivateUsage` diagnostics outside these two roots, proving the exception does not relax the repository-wide private-access rule.

## Recommendations

Keep the two execution environments bounded to the existing friend-test roots and do not add paths, exclusions, or further relaxed rules. In `W06.P12.S26`, repair the remaining 873 test-domain diagnostics through typed real-behavior harnesses, including the five private-local imports, rather than widening this policy or introducing suppressions.
