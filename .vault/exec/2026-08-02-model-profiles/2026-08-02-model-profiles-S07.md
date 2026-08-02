---
tags:
  - '#exec'
  - '#model-profiles'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:672cf42950dab71240745de5aac7760bdede11bd5ffb34c84707e0d106087192'
step_id: 'S07'
related:
  - "[[2026-08-02-model-profiles-plan]]"
---
# Prove factory compiler and preset resolution preserve explicit low models

## Scope

Factory, profile-resolution, frozen-assignment, and protocol regression tests.

## Description

- Added direct assertions that Claude and Z.ai retain the requested concrete ACP model.
- Guarded complete all-low profile resolution and frozen concrete-name propagation.
- Exercised the real adapter configuration exchange without a prompt.

## Outcome

Focused provider/profile regression tests passed: 56 passed, 1 deselected.

## Notes

The proof imports and executes production resolver and factory code; it adds no mock, stub, or test-owned business logic.
