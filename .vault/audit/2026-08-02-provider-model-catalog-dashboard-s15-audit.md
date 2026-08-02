---
tags:
  - '#audit'
  - '#provider-model-catalog'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:9d5f8e9bf1811e1a675567b2191128265b276ca28e0e513a6422c6fbecb5314a'
related:
  - "[[2026-08-02-provider-model-catalog-plan]]"
---
# `provider-model-catalog` audit: `Dashboard S15 bounded expert selection review`

## Scope

Formal review of the Dashboard bounded expert-selection implementation for
provider-model-catalog plan P02.S15, including the current catalog gate,
run-start payload, expert-control accessibility, and localization.

## Findings

### intercepted-wire-assertion | high | A mocked request capture did not prove the run-start boundary

Status: remediated. The original feature assertion intercepted `fetch` and
inspected a local request capture. The proof now uses the production A2A team
client across a real local TCP listener, covering populated per-role overrides,
ordered fallbacks, retry identity, and omission of empty optional fields.

### mixed-menu-controls | medium | The model popup exposed native controls inside a menu

Status: remediated. The model chooser now exposes a labeled dialog and its
trigger declares a dialog popup; selectable model rows use ordinary pressed
buttons, so native control selects share a truthful interaction container.

### retired-profile-copy | medium | The catalog accessibility label named the retired profile contract

Status: remediated. The provider-model control label now describes the current
catalog contract in English and the supported left-to-right and right-to-left
test resources.

### model-control-scope | high | Lane controls were admitted for unrelated catalog models

Status: remediated. Each served model now carries only its A2A-issued
`native_control_ids`; selection minting, control mutation, picker rendering,
and current-catalog revalidation reject lane controls outside the selected
model. The transport and adapter evidence covers model-scoped controls and
scope drift.

### dialog-focus-lifecycle | medium | The model dialog did not establish and restore keyboard focus

Status: remediated. Opening the dialog moves focus to its first selectable
model, and every dismiss path restores focus to the trigger through the shared
popover focus lifecycle. The render test verifies dialog announcement, initial
focus, Escape dismissal, and trigger restoration.

### role-id-disclosure | medium | Internal required-role identifiers could reach visible or accessible text

Status: remediated. Optional served `required_role_labels` supply authored
labels; missing labels fall back to the localized `Agent {{index}}` ordinal.
Raw A2A role ids remain request keys only and are not rendered in user-facing
text.

### prototype-role-key | medium | Opaque served role ids could collide with Object.prototype

Status: remediated. Role-label and override lookup now require an own property,
and the A2A adapter builds optional role labels in a null-prototype map. The
render proof verifies that an absent `constructor` role uses the localized
ordinal, starts without an override, and emits exactly the owned
`constructor` request key when enabled.

## Closure

Final independent closure review passed with no open findings. Its inspection
reconfirmed the model-scoped control boundary, stale-selection revalidation,
dialog focus restoration, localization, resource bounds, real transport proof,
and prototype-safe opaque role handling. The final focused validation passed 5
files / 35 tests, TypeScript, scoped ESLint, localization scanning, and diff
integrity.

## Recommendations

The cross-repository real-provider and frozen-prompt proof remains owned by
plan P03.S19 through P03.S23. It must run only against an admitted provider
catalog and must not be inferred from this local transport boundary.
