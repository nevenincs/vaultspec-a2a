---
tags:
  - '#exec'
  - '#model-profiles'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:2cd71feb211c527985ad30770e9a833dd4e40d5d31e6e08f04d29f375e2a75be'
step_id: 'S09'
related:
  - "[[2026-08-02-model-profiles-plan]]"
---
# Run a real ACP configuration handshake without prompting and reaping subprocesses

## Scope

Installed Claude ACP adapter protocol proof.

## Description

- Spawned the real installed adapter.
- Opened a real session, discovered the model configuration option, selected the low value, verified the confirmation, and reaped the subprocess before prompting.

## Outcome

The production adapter accepted and reported the selected low model without incurring an inference turn.

## Notes

This is the drift detector for adapter protocol updates; full provider turns remain separately credential and quota dependent.
