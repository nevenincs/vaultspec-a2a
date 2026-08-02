---
tags:
  - '#audit'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:86dff4675c1cba58fd478b3377fdaa8bc6a573012864728d5bc3361f967dda1f'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
  - "[[2026-08-02-provider-model-catalog-adr]]"
---
# `provider-model-catalog` audit: `Frozen run evidence P02.S17 review`

## Scope

Reviewed the P02.S17 Dashboard frozen-run evidence contract: strict adapter admission, the run-header disclosure, localization, and real local-TCP transport coverage. The audit intentionally excludes concurrent A2A provider and Dashboard Rust clarification work.

## Findings

### invalid-modern-fallback | high | Malformed modern evidence could appear as legacy provider/model rows

A present `frozen_assignment` that failed the complete modern contract was previously indistinguishable from an absent field. `adaptRunStatus` then used legacy `assignments`, which could present partial provider/model rows for a run whose authoritative modern evidence was rejected.

Resolution: the adapter now classifies the field as absent, invalid, or valid. Legacy rows are permitted only when the modern field is absent. A present-invalid field removes bindings and exposes only a localized incomplete-evidence notice; raw content and reasons remain discarded. Run-start carries the same safe invalid marker. Focused adapter and mounted-header tests prove absent-to-legacy recovery and invalid-present suppression.

## Recommendations

- Keep the P01.S09 response contract aligned with Dashboard's complete frozen snapshot: schema version, digest, resolved provider/model/control values, ordered fallbacks, and bounded provenance.
- Re-run the independent review after this remediation and record its verdict here before closing P02.S17.

## Independent closure review

Verdict: **PASS**. No open findings remain.

The remediated adapter distinguishes an absent, invalid, or valid modern snapshot. Legacy `assignments` are admitted only when `frozen_assignment` is truly absent; a present-invalid field suppresses provider/model bindings, discards raw evidence, carries the invalid marker through run-start and run-status, and renders the localized incomplete-evidence state in the run header. Valid evidence remains snapshot-only: schema v1 and digest are checked, identifiers and collections are bounded, duplicate roles/controls/fallback execution identities fail closed, exact provider/model/control `provider_value` and ordered fallbacks are retained, provenance is allowlisted, and no catalog re-resolution or secret-bearing raw fields reach the header.

Independent evidence: 4 focused Vitest files / 43 tests passed, including mounted-header and real local-TCP transport coverage; TypeScript project build passed; exact scoped Prettier and ESLint passed; localization scan reported zero user-facing source literals; scoped `git diff --check` passed. The repository-wide frontend formatter remains outside this verdict because its known failure is an unrelated untouched `ComposerExpertSelection.tsx` baseline file; every P02.S17 path passed its exact formatter check.
