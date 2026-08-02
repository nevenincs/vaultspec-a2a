---
tags:
  - '#exec'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:ca329805b7d8daa9995283490198fd66e296cbdfc95cc69af6bdd13098545614'
step_id: 'S15'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---
# Add bounded per-role model and control overrides and explicit served fallbacks without arbitrary role keys or model values

## Scope

- `frontend/src/app/agent/Composer.tsx`
- `frontend/src/app/agent/ComposerExpertSelection.tsx`
- `frontend/src/app/agent/ComposerModelPicker.tsx`
- `frontend/src/app/kit/DropdownButton.tsx`
- `frontend/src/app/kit/Popover.tsx`
- `frontend/src/stores/server/agent/a2aProviderCatalog.ts`
- `frontend/src/stores/server/agent/a2aTeam.ts`
- Focused component, adapter, transport, localization, and visual-review coverage

## Description

- Add the opt-in expert disclosure beside the required whole-team chooser.
- Derive unique override keys exclusively from served required roles and cap them at 64.
- Keep an explicitly ordered fallback list capped at 8 and mint every selection from the current served catalog.
- Reconcile retained overrides and fallbacks whenever preset, provider, revision, selectability, entry, or model-scoped native control membership changes.
- Omit both optional wire fields when they contain no retained values.
- Restrict every entry to its served `native_control_ids`; reject lane controls outside the selected model during mint, mutate, render, and revalidation.
- Use a dialog interaction model for model/native-control choices, with initial model focus and trigger restoration on dismissal.
- Render only served role labels or a localized ordinal; read opaque role ids as own properties and preserve served labels in a null-prototype map.
- Replace the intercepted request assertion with a real local TCP transport proof for populated and empty optional fields.

## Outcome

- Per-role and fallback selections cannot introduce Dashboard-authored provider, model, control, or role identifiers.
- The simple whole-team selection remains required while expert controls are explicit, localized, and safe for prototype-colliding served role ids.
- The focused suite passed 5 files / 35 tests. TypeScript, scoped ESLint, localization scanning, and whitespace checks passed.
- Two independent review passes surfaced and remediated two high and five medium findings. The final independent closure review passed with no open findings.

## Notes

- A provider completion was not issued. The admitted-provider, frozen prompt-setup, refresh, restart, and cross-repository proof remain the bounded P03 integration work.
