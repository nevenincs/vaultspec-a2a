---
tags:
  - '#exec'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:519dfe173c40c75fc1cbfab2e9ba709c671bf4962e37086b820f8e66892aadf0'
step_id: 'S13'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---

# Directly migrate the Dashboard store, composer chooser, and obsolete profile fixtures to opaque provider catalogs, structured health, required selection, controls, and frozen assignments

## Scope

- `Y:/code/vaultspec-dashboard-worktrees/main/frontend/src/stores/server/agent/`
- `frontend/src/app/agent/ComposerModelPicker.tsx`
- `frontend/src/app/agent/Composer.tsx`
- `frontend/dev/visual-review/specimens/agent.tsx`

## Description

- Ground the migration in VaultSpec semantic discovery, the accepted provider-owned catalog ADR, its research/reference, the reconciled plan, S01 provider contracts, and S12's Rust boundary.
- Replace profile adapters with A2A-issued provider records, structured health, catalog state, opaque entry/control choices, served selection references, fallbacks/override payload types, and frozen assignment types.
- Gate catalog reads to a selected team, mint selections only from an explicit current selectable lane/revision/entry/control option, and send the required opaque selection at run start.
- Replace the profile chooser with provider-grouped catalog entries and provider-native control inputs; remove the obsolete profile tests and capture.
- Preserve legacy frozen-profile assignment rows exclusively as read-only existing-run evidence while new runs can only use catalog selections.

## Outcome

- Dashboard contains no product profile picker, profile wire adapter, concrete external model identifier, or cross-provider level map on the new-run path.
- Omitted, stale, or internally inconsistent provider health is unselectable; changed catalog revisions and invalid native control values invalidate a held browser selection before run start.
- Focused provider-store, real loopback transport, feature, and composer evidence passed: 48 tests. Dashboard TypeScript typecheck, targeted lint, formatting, and whitespace checks passed.
- Formal review found three medium migration findings: legacy assignment display, unsolicited catalog query, and wire-regression coverage. All were remediated and the closure review passed with no critical or high findings.

## Notes

- The provider-catalog API serializer and frozen assignment status wrapper remain owned by P01.S07 through P01.S09. Dashboard uses the accepted normalized contract and keeps absent/future data unselectable until those routes serve it.
- No real provider completion or credentials were used. The transport proof uses a local TCP listener and the product remains blocked by A2A membership validation until the remaining backend steps land.
