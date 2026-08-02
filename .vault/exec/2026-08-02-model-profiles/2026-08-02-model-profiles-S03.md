---
tags:
  - '#exec'
  - '#model-profiles'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:2d9d080c3ab41b235fcf357d7ec3687e1d6c7e68152411bd1d49736a4f04751a'
step_id: 'S03'
related:
  - "[[2026-08-02-model-profiles-plan]]"
---
# Retain desired model and negotiated configuration options in ACP session state

## Scope

ACP configuration state and session setup.

## Description

- Added the resolved desired-model field to the ACP model configuration and chat-model snapshot.
- Preserved adapter-advertised configuration options on successful session setup.

## Outcome

The requested model and the negotiated options now survive from factory construction through session setup, before any prompt is eligible to run.

## Notes

The state is only populated from the real adapter response; there is no guessed configuration identifier.
