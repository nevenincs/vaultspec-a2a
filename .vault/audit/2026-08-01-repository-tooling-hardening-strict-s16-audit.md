---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-01'
modified: '2026-08-01'
body_schema: 'body-v1'
body_hash: 'sha256:337e0552bf65e6adedbf0325d972cdc39a7ae4ed37a902617fd070086bfcc942'
related:
  - "[[2026-07-19-repository-tooling-hardening-plan]]"
---
# `repository-tooling-hardening` audit: `hosted sentinel visibility review`

## Scope

Formal read-only review of plan step `W05.P10.S16`: the hosted workflow diff that exposes the deterministic strict-quality sentinels. The review checked sentinel identity and cardinality, advisory semantics, non-cancellation guards, command ownership, trigger preservation, canonical-CI preservation, S17 separation, diff hygiene, and workflow syntax.

## Findings

### hosted-sentinel-visibility | low | Clean review: no release-blocking discrepancy found

The scoped workflow diff adds exactly one independently named advisory step for each deterministic sentinel: `type-strict`, `type-platforms`, `complexity`, `cyclomatic`, `shape`, `limits`, `nesting`, and `size`. Every added step has the exact guard `if: ${{ !cancelled() }}`, `continue-on-error: true`, and only its corresponding named `just lint <target>` command. The diff is whitespace-clean, leaves the existing push and pull-request triggers and the adjacent canonical-CI invocation unchanged, and contains neither duplicate sentinel additions nor the separate duplication/JSCPD step reserved for `W05.P10.S17`. Direct `actionlint` validation of the workflow completed successfully.

### workflow-wrapper-timeout | low | Wrapper validation remains an unproven boundary, not a workflow failure

The project wrapper `just lint workflow` emitted no result and exceeded the bounded 60-second review allowance, ending with timeout exit 124 after approximately 64 seconds. Because direct `actionlint` passed and the timeout does not identify a workflow defect, this is recorded as incomplete wrapper evidence rather than a release-blocking finding.

## Recommendations

Release blocker result: none. The S16 workflow change is clear to proceed; preserve the separate `W05.P10.S17` duplication lane and complete wrapper validation when its execution environment is available.
