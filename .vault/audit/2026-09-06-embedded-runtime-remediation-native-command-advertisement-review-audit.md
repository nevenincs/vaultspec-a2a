---
tags:
  - '#audit'
  - '#embedded-runtime-remediation'
date: '2026-09-06'
modified: '2026-09-06'
body_schema: 'body-v2'
body_hash: 'sha256:ad4ca2bed8aee2f19f0446074d56b7a171b0e639b3121f8ee2c59570ebfd1b47'
related:
  - "[[2026-09-05-embedded-runtime-remediation-plan]]"
---
# `embedded-runtime-remediation` audit: `ACP native command advertisement review`

## Scope

Reviewed the W03.P08.S37 implementation against the accepted provider abstraction and capability-evidence decisions, the pinned ACP 1 schema shipped with the repository, the no-legacy amendment, and the bounded test evidence.

## Findings

### session-identity-authority | high | One mutable catalog can accept advertisements from the wrong session

`handle_session_update` receives the notification `sessionId`, but the initial implementation stored one context-wide snapshot. Resolved in this pass: catalogs are keyed by the exact validated protocol session identifier, replacement affects only that key, missing or oversized identifiers allocate nothing, and the number of session catalogs is bounded. Cross-session and capacity discriminators pass.

### legal-text-overvalidation | medium | Valid ACP descriptions and hints can be blocked

The initial implementation applied command-identity constraints to display text although ACP 1 only requires strings. Resolved in this pass: command names retain bounded exact-identity validation while descriptions and hints accept the legal bounded string shape, including empty text. The empty-display-text discriminator passes.

### capability-composition-dependency | high | The capability matrix has types but no production composition or served consumer

The prerequisite plan's immutable record types exist, but no production owner composes them from catalog health, exact-lane admission, web proof and permission policy, and no served response carries the result. W03.P08.S35 and S36 therefore remain open, and native command or compaction support must not be promoted into a product capability claim. Status: deferred to the existing `provider-capability-evidence` plan P01.S02 and P02.S03-S04.

## Recommendations

Proceed with the exact session-keyed advertisement catalog as the W03.P08.S37 protocol authority. Keep command execution and all product capability claims blocked until their owning Steps establish argument validation, busy/outcome behavior, effect proof and the missing capability composition.
