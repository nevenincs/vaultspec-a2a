---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:3228ff088e5445a7360ecbe88549a38755b8423a7bb788f3b089d0fe2ed6ee73'
related: []
---
# `repository-tooling-hardening` audit: `Control leaf type-boundary review`

## Scope

Independent read-only review of the uncommitted S24 leaf bundle in `control.permission_service`, `control.run_start_policy`, `control.cleanup.executor`, and `control.snapshot` against the accepted strict-boundary contract. The review checked JSON object validation before use, removal of unreachable post-authorization permission branches, explicit empty role sets, non-`None` string checkpoint tool-call identifiers, public-surface preservation, and the absence of new suppressions, unchecked casts, or test shortcuts.

Focused real-behavior evidence: permission rejection journaling, run-start eligibility, cleanup containment, and cleanup independence passed 29 tests. A direct real LangChain `AIMessage` and `ToolMessage` probe confirmed that a valid tool-call id becomes a completed snapshot entry and a `None` id is omitted. Focused BasedPyright and ty checks reported zero diagnostics; Ruff check and format check passed; the scoped diff check passed.

## Findings

No findings. The reviewed changes retain the existing contracts: decoded JSON reaches mapping operations only after the object guard, the idempotency branch uses the already-proven durable permission, missing actor-token coverage is represented by an explicit `set[str]`, and snapshot tool-call ids are accepted only when strings.

## Recommendations

No follow-up action from this review.
