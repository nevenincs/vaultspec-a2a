---
tags:
  - '#exec'
  - '#model-profiles'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:afcbc85bd3bbd9addd47095aecf71080006241f48075d90565984ada2ebbeab6'
step_id: 'S05'
related:
  - "[[2026-08-02-model-profiles-plan]]"
---
# Remove obsolete ACP session set model transport and malformed setter

## Scope

Legacy ACP selection API surface.

## Description

- Removed the obsolete `session/set_model` transport and its request identifier.
- Removed the malformed generic configuration setter that used an unsupported request shape.

## Outcome

Model selection has one supported, internal, negotiated path; callers cannot retain or invoke obsolete transport.

## Notes

A repository scan found no remaining supported runtime reference to the removed interface.
