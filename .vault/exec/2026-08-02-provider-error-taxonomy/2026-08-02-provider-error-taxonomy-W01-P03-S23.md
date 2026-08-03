---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-02'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:becb056af4f02865b1cdbb308976479d6150397b189faaeecd345518eb7ba125'
step_id: 'S23'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---

# Project the condition onto the run-status response

## Scope

- `src/vaultspec_a2a/api/routes/gateway.py`

## Description

- Pass the snapshot's condition onto the run-status response.

## Outcome

Closes the last hop. The response is assembled from explicit keyword arguments
rather than validated from the snapshot, which means nothing here is dropped
silently - but equally, nothing arrives without being written by hand. That is
the failure mode this line addresses: the reason itself was persisted, carried
to this constructor, and then simply never named on it.

With this the value is readable end to end from a real failure: the lane
resolves it, the ingest catch-all reports and retains it, the terminal carries
it, the gateway persists it, the capture reads it back, and this response serves
it to a client that has no live stream.

## Notes

The file carries a large unrelated in-flight change from a concurrent writer, so
only this hunk was staged and committed; the rest of that writer's work was left
untouched in the working tree.
