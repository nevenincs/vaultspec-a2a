---
tags:
  - '#exec'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:0e52a8a48061c8192b7a372784b836802aac1d60938ab28f6ca43d8e645b3fcf'
step_id: 'S17'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---
# Render exact frozen provider, model, native controls, and provenance returned for active runs

## Scope

- `frontend/src/stores/server/agent/a2aTeam.ts`
- `frontend/src/app/agent/TeamRunHeader.tsx`
- Frozen-evidence adapter, TCP transport, mounted-header, and localization coverage

## Description

- Replace the future-only outbound-selection projection with a complete frozen execution snapshot that preserves schema, digest, resolved provider/model values, native control values, ordered fallbacks, and the two admitted provenance origins.
- Admit the modern snapshot fail-closed with bounded identifiers, labels, collections, digests, and duplicate identities; discard all unknown raw provenance.
- Render only the authoritative frozen run-status snapshot and never look up current catalog values or defaults.
- Suppress legacy bindings when a present modern snapshot is invalid, and disclose only localized incomplete-evidence state.
- Add real local-TCP run-status transport proof, mounted-header disclosure proof, and negative contract tests.

## Outcome

PASS. The Dashboard presents complete historical provider/model/control evidence only when the modern frozen assignment is valid. The independent closure review found and verified remediation of the one high-integrity issue: a malformed present modern field can no longer fall back to legacy provider/model rows.

Verification passed: TypeScript build; four focused Vitest files with 43 tests; exact Prettier and ESLint for the S17 paths; localization scan with zero source literals; module-size scan; and scoped `git diff --check`. The local-TCP test demonstrates verbatim broker recovery of the refined frozen snapshot while excluding an injected unsafe provenance value.

## Notes

Current A2A run responses still expose legacy profile assignments until P01.S08 and P01.S09 serve the accepted frozen catalog contract. This Dashboard work is strict forward-compatible admission and does not claim assembled cross-project execution; P03.S19 and P03.S20 remain the live integration/restart proof owners.
