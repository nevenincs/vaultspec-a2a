---
tags:
  - '#audit'
  - '#repository-tooling-hardening'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:70c8aca216b5c6ff0366219f35cd3e2143646e3052b10082cb0730ba9db6bf3f'
related: []
---
# `repository-tooling-hardening` audit: `Model profile persistence and readiness review`

## Scope

Independent read-only review of the S25 `model_profiles` JSON persistence and provider-readiness boundary, including its direct real-behavior test suite. The review verified the `TypeAdapter` closed JSON ingress, malformed-record `None` returns, UTF-8 canonical digest construction, field-precedence and readiness ordering, and the public factory classifier seam. The changed source and direct tests are free of `Any`, casts, suppressions, and formatting defects. Focused Basedpyright and Ty both reported zero diagnostics; the direct suite passed 26 tests.

## Findings

### persisted-digest-not-verified | medium | Persisted frozen assignments accept an unchecked digest

`frozen_from_record` validates that a record is JSON-shaped and reads its supplied digest, but never recomputes the canonical profile-and-roles hash before returning the restored assignment. The gateway consumes that result during restart, so a syntactically valid but tampered profile or roles payload can be treated as frozen despite its digest not matching. The direct round-trip test proves preservation, not integrity. A follow-up contract must decide whether a mismatch fails closed, triggers an explicit migration, or is otherwise surfaced; this review does not repair it.

### malformed-frozen-provider-defaults-claude | medium | Compiler silently converts malformed legacy frozen role records to Claude

The JSON ingress permits role objects without required frozen-assignment fields, while the compiler catches a missing or invalid provider and substitutes `Provider.CLAUDE`. A persisted role record with no usable provider can therefore silently change execution from its recorded selection to Claude, contradicting the frozen-assignment stability claim. A follow-up must define an explicit legacy-record migration or failure policy; this review does not repair it.

## Recommendations

- Define and test digest-verification policy at the persisted-record restore boundary before treating frozen metadata as authoritative.
- Require the compiler-facing frozen role contract to reject or explicitly migrate records without a valid provider instead of silently selecting Claude.
