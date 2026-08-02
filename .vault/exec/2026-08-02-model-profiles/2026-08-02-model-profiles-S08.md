---
tags:
  - '#exec'
  - '#model-profiles'
date: '2026-08-02'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:6e15b20294d214db7b26c18fffae5997d8f0fd0196a16b4407cdf047dd5178a0'
step_id: 'S08'
related:
  - "[[2026-08-02-model-profiles-plan]]"
---
# Route real provider tests through fast or direct Model.LOW with pre-spawn guards

## Scope

Cost-bearing service and provider live-test entry points.

## Description

- Fixed research and solo-coder service harnesses to their committed all-low `fast` profiles.
- Removed the ambient profile override that could select a higher tier.
- Set direct Claude, Z.ai, and Codex provider tests to the low capability.
- Sent the explicit low Codex model in raw thread and turn protocol requests.

## Outcome

The live-test search found no remaining targeted soft edge that defaults to `team-defaults`, accepts the removed override, or sends an unspecified model for these providers.

## Notes

The raw Codex low-tier web-retrieval turn passed live.
