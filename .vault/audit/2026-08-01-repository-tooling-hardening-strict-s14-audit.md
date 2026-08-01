---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:4182ac7bea580be7efa64f3eef7325efda311db62e000af2bc65ec7e9570aefb'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---
# `repository-tooling-hardening` audit: `cognitive scope review`

## Scope

Formal read-only review of `W05.P09.S14`: the declarative Complexipy production scope in `dev/toolchain.py`, against the accepted tooling-hardening decision, its plan, and the strict-quality research and reference. The executor supplied one Windows run of the rendered comma-separated exclusion command: 9.2 seconds, 196 production headings, zero excluded-path matches, and only production complexity findings remaining.

## Findings

### production-complexity-scope | low | Corrected lint target is target-local and production-only

The `lint complexity` target invokes Complexipy once on `src/vaultspec_a2a` with a single comma-separated `--exclude` argument constructed from direct and nested `tests`, `service_tests`, `desktop_tests`, `acceptance`, and cache patterns. This preserves the test-focused audit target, makes no `pyproject.toml` threshold or process-global exclusion change, and matches the reference requirement that production scope stay target-local. The supplied run confirms the rendered command excludes no reported test or cache paths while retaining 196 production headings; its remaining red output is therefore the planned production-debt burndown, not a scope failure. Complexipy 6.2's documented root-relative exclusions and Windows normalization support the plan's every-supported-host intent.

### audit-complexity-scope-mismatch | medium | Advisory target labels the test tree but scans the package root

`audit complexity` is described as cognitive complexity over the test tree and as a test-focused investigation command, yet its rendered command is `complexipy src/vaultspec_a2a --failed` with no test-tier selection or production exclusion. It therefore scans the package root rather than the stated test tree. This is advisory and does not weaken the corrected production gate, but it gives misleading investigation scope and conflicts with the governing reference.

## Recommendations

- Preserve the S14 production command and its unchanged configured limit; route its remaining findings to the planned production-complexity remediation and graduation steps.
- Queue a bounded follow-up for the audit target: make its command select only the declared test tiers, then add a real-registry contract assertion that the target description and command scope agree. Keep it advisory and leave the production-only lint target independent.
