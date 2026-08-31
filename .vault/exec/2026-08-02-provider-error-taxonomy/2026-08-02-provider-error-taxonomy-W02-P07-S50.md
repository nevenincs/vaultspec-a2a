---
tags:
  - '#exec'
  - '#provider-error-taxonomy'
date: '2026-08-03'
modified: '2026-08-03'
body_schema: 'body-v1'
body_hash: 'sha256:521f46b28d982d48f82b2c180adeebbd7763592a8844028aec87fd719ed348c1'
step_id: 'S50'
related:
  - "[[2026-08-02-provider-error-taxonomy-plan]]"
---
# Prove the condition round-trips through the session store

## Scope

- `engine/crates/vaultspec-api/src/authoring/session/tests.rs`

## Description

- Prove a settled condition survives a write, a read, and a store reopen.
- Prove an unrecognised value is refused and records nothing.
- Prove a completed run cannot carry one.
- Prove a record predating the field still loads.

## Outcome

Landed and re-verified after the fact. Four properties, each driven through the
real store rather than around it, with all nine members admitted through the same
boundary that refuses an invented one.

Two details make these non-tautological. The round-trip fixture carries a reason
that deliberately CONTRADICTS its condition, so a future implementation that
derived one from the other would fail here rather than pass. And the
old-record case asserts both that the value reads as absent AND that the
serialized record contains no key for it, which is the difference between
proving compatibility and asserting a default.

## Notes

A concurrent writer's commit swept this Step's staged files before its own commit
ran, so the content landed inside a commit whose message describes frontend
localization. The content is intact and was verified in place rather than from
memory; separating it would be a history rewrite and was correctly declined.

Re-verified at a later HEAD after five further commits landed on shared files,
because a green that predates the commits it shares files with is not evidence
about the current tree. That re-run began with a clean rebuild of both crates,
after the first pass returned in about a second - a cache report rather than a
verification. All four properties still assert what they claim, read from the
committed file rather than recalled.
